from __future__ import annotations

import datetime
import uuid

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_client_ip, get_current_user
from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.core.security import decode_token, hash_password_async, verify_password_async
from app.core.token_revocation import (
    claim_jti,
    is_token_stale,
    revocation_cutoff,
    revoke_jti,
)
from app.db.session import get_db
from app.models.chat_message import ChatMessage
from app.models.enums import ReviewStatus
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.models.source import Source
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import OperationStatus
from app.services.system import rbac as rbac_service
from app.services.system.audit import log_action
from app.services.users import service as user_service

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=False)
_SSO_PER_MIN = 30

async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(GlobalSetting.value).where(GlobalSetting.key == key))
    row = result.scalar_one_or_none()
    return row


async def _enforce_auth_rate_limit(request: Request, scope: str, max_per_min: int) -> None:
    """Limita intentos por IP en endpoints de autenticación (anti fuerza bruta)."""
    client_ip = get_client_ip(request)
    try:
        await check_rate_limit(f"auth:{scope}", client_ip, max_requests=max_per_min, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espere un momento y vuelva a intentarlo.",
            headers={"Retry-After": str(exc.retry_after)},
        )


def _token_response(user, access: str, refresh: str) -> TokenResponse:
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse.model_validate(user),
    )


async def _microsoft_ready(db: AsyncSession) -> bool:
    settings = get_settings()
    is_active = bool(await _get_setting(db, "oauth_active") or False)
    return bool(
        is_active and settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET
        and settings.MICROSOFT_TENANT_ID
    )


async def _credentials_enabled(db: AsyncSession, microsoft_ready: bool) -> bool:
    """Sin Microsoft operativo la contraseña queda habilitada, para no dejar a nadie fuera."""
    raw = await _get_setting(db, "auth_credentials_enabled")
    return raw is None or bool(raw) or not microsoft_ready


class AuthProviders(BaseModel):
    credentials: bool
    microsoft: bool
    microsoft_client_id: str | None = None
    microsoft_tenant_id: str | None = None


@router.get("/providers", response_model=AuthProviders)
async def get_providers(db: AsyncSession = Depends(get_db)):
    """Endpoint público (sin auth) que indica qué métodos de login están activos."""
    settings = get_settings()
    client_id = settings.MICROSOFT_CLIENT_ID
    tenant_id = settings.MICROSOFT_TENANT_ID or ""
    microsoft_ready = await _microsoft_ready(db)
    credentials_enabled = await _credentials_enabled(db, microsoft_ready)

    return AuthProviders(
        credentials=credentials_enabled,
        microsoft=microsoft_ready,
        microsoft_client_id=client_id if microsoft_ready else None,
        microsoft_tenant_id=tenant_id if microsoft_ready else None,
    )


class MicrosoftCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


@router.post("/microsoft/callback", response_model=TokenResponse)
async def microsoft_callback(
    body: MicrosoftCallbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Recibe el authorization code de Microsoft."""
    from app.services.auth import sso as sso_service

    # El canje suele llegar desde el servidor del panel (una sola IP para toda la organización)
    # y el código de Microsoft es de un solo uso: no es un vector de adivinación de contraseñas.
    await _enforce_auth_rate_limit(request, "sso", max(get_settings().RATE_LIMIT_LOGIN_PER_MIN, _SSO_PER_MIN))
    return await sso_service.handle_microsoft_callback(
        db, request=request, code=body.code, redirect_uri=body.redirect_uri,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Autentica al usuario y emite par access/refresh JWT."""
    await _enforce_auth_rate_limit(request, "login", get_settings().RATE_LIMIT_LOGIN_PER_MIN)

    # Aplica el setting credentials_enabled - rechaza a nivel de backend
    if not await _credentials_enabled(db, await _microsoft_ready(db)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El acceso por credenciales está deshabilitado. Use Microsoft SSO.",
        )

    user = await user_service.authenticate(db, body.email, body.password)
    client_ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    if not user:
        await log_action(
            db, action="auth.login_failed", resource_type="user",
            actor_id=None, resource_id=None,
            ip=client_ip, user_agent=ua,
            meta={"attempted_email": body.email.lower()[:120]},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        await log_action(
            db, action="auth.login_failed", resource_type="user",
            actor_id=user.id, resource_id=str(user.id),
            ip=client_ip, user_agent=ua,
            meta={"attempted_email": body.email.lower()[:120], "reason": "account_disabled"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Su cuenta está desactivada.",
        )

    user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    await log_action(
        db, action="auth.login", resource_type="user",
        actor_id=user.id, resource_id=str(user.id),
        ip=client_ip, user_agent=ua,
    )
    await db.commit()

    return _token_response(
        user, *await rbac_service.issue_user_tokens(db, user)
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Rota un refresh token válido por un par nuevo de access/refresh."""
    await _enforce_auth_rate_limit(request, "refresh", get_settings().RATE_LIMIT_REFRESH_PER_MIN)

    refresh_token = body.refresh_token
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(refresh_token)
    except pyjwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await user_service.get_by_id(db, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_token_stale(payload, user.tokens_valid_after):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión expirada por cambio de credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp = datetime.datetime.fromtimestamp(payload.get("exp", 0), tz=datetime.timezone.utc)
    if not await claim_jti(payload.get("jti"), exp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ya utilizado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _token_response(
        user, *await rbac_service.issue_user_tokens(db, user)
    )


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


@router.post("/logout", response_model=OperationStatus)
async def logout(
    body: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Revoca el access token actual y el refresh token."""
    access_token = credentials.credentials if credentials else None
    if access_token:
        try:
            ap = decode_token(access_token)
        except pyjwt.PyJWTError:
            ap = None
        if ap and ap.get("jti") and ap.get("exp"):
            await revoke_jti(ap["jti"], datetime.datetime.fromtimestamp(ap["exp"], tz=datetime.timezone.utc))

    refresh_token = body.refresh_token if body else None
    if refresh_token:
        try:
            rp = decode_token(refresh_token)
        except pyjwt.PyJWTError:
            rp = None
        if rp and rp.get("type") == "refresh" and rp.get("jti") and rp.get("exp"):
            await revoke_jti(rp["jti"], datetime.datetime.fromtimestamp(rp["exp"], tz=datetime.timezone.utc))

    return OperationStatus()


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    """Devuelve los datos del usuario detrás del access token actual."""
    return UserResponse.model_validate(current_user)


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _enforce_auth_rate_limit(request, "change_password", get_settings().RATE_LIMIT_LOGIN_PER_MIN)

    if not await verify_password_async(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

    if await verify_password_async(body.new_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contraseña debe ser diferente a la actual")

    current_user.hashed_password = await hash_password_async(body.new_password)
    current_user.must_change_password = False
    current_user.tokens_valid_after = revocation_cutoff()
    await log_action(
        db, action="auth.change_password", resource_type="user",
        actor_id=current_user.id, resource_id=str(current_user.id),
        ip=get_client_ip(request),
    )
    await db.commit()

    return _token_response(
        current_user, *await rbac_service.issue_user_tokens(db, current_user)
    )


class OnboardingStatus(BaseModel):
    step: int | str
    providers_configured: bool
    providers_active: bool
    sources_uploaded: bool
    sources_approved: bool
    messages_sent: int
    dismissed: bool


@router.get("/onboarding-status", response_model=OnboardingStatus)
async def onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> OnboardingStatus:
    """Calcula el progreso del wizard en función del estado real del sistema."""
    providers_count = (await db.execute(
        select(func.count(LLMProvider.id))
    )).scalar_one()

    providers_active = (await db.execute(
        select(func.count(LLMProvider.id)).where(LLMProvider.is_active.is_(True))
    )).scalar_one()

    sources_count = (await db.execute(
        select(func.count(Source.id)).where(Source.deleted_at.is_(None))
    )).scalar_one()

    sources_approved = (await db.execute(
        select(func.count(Source.id))
        .where(Source.deleted_at.is_(None))
        .where(Source.review_status == ReviewStatus.aprobada)
    )).scalar_one()

    messages_sent = (await db.execute(
        select(func.count(ChatMessage.id))
    )).scalar_one()

    if providers_count == 0:
        step: int | str = 1
    elif providers_active == 0:
        step = 2
    elif sources_count == 0:
        step = 3
    elif sources_approved == 0:
        step = 4
    elif messages_sent == 0:
        step = 5
    else:
        step = "done"

    return OnboardingStatus(
        step=step,
        providers_configured=providers_count > 0,
        providers_active=providers_active > 0,
        sources_uploaded=sources_count > 0,
        sources_approved=sources_approved > 0,
        messages_sent=messages_sent,
        dismissed=current_user.onboarding_dismissed,
    )


@router.post("/onboarding-dismiss", response_model=OperationStatus)
async def onboarding_dismiss(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> OperationStatus:
    """Marca el wizard como dismissed para este usuario."""
    current_user.onboarding_dismissed = True
    await db.commit()
    return OperationStatus()


@router.post("/onboarding-reset", response_model=OperationStatus)
async def onboarding_reset(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> OperationStatus:
    """Vuelve a mostrar el wizard para este usuario (inverso de dismiss)."""
    current_user.onboarding_dismissed = False
    await db.commit()
    return OperationStatus()
