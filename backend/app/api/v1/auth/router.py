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
from app.core.security import decode_token, hash_password, verify_password
from app.services.system import rbac as rbac_service
from app.core.token_revocation import is_jti_revoked, is_token_stale, revoke_jti
from app.db.session import get_db
from app.models.chat_message import ChatMessage
from app.models.enums import ReviewStatus
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.models.source import Source
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.schemas.common import OperationStatus
from app.services.users import service as user_service
from app.services.system.audit import log_action

router = APIRouter(prefix="/auth", tags=["auth"])

# Bearer scheme local para /logout — opcional (auto_error=False) porque en
# modo cookie el access token no viaja en el header. Un token ya expirado o de
# una cuenta desactivada igual debe poder "cerrar sesión".
_bearer = HTTPBearer(auto_error=False)

async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(GlobalSetting.value).where(GlobalSetting.key == key))
    row = result.scalar_one_or_none()
    return row


async def _enforce_auth_rate_limit(request: Request, scope: str, max_per_min: int) -> None:
    """Limita intentos por IP en endpoints de autenticación (anti fuerza bruta).

    Primero intenta Redis. Si Redis no está disponible, activa el contador en
    memoria como fallback secundario para mantener protección básica contra
    fuerza bruta incluso cuando Redis cae.
    """
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


class AuthProviders(BaseModel):
    credentials: bool
    microsoft: bool
    microsoft_client_id: str | None = None
    microsoft_tenant_id: str | None = None


@router.get("/providers", response_model=AuthProviders)
async def get_providers(db: AsyncSession = Depends(get_db)):
    """Endpoint público (sin auth) que indica qué métodos de login están activos.

    El frontend lo consume en /login para renderizar condicionalmente el
    formulario de credenciales y/o el botón de Microsoft SSO. Credenciales
    de Microsoft vienen del .env; el toggle activo/inactivo vive en la DB.
    """
    credentials_raw = await _get_setting(db, "auth_credentials_enabled")
    credentials_enabled = bool(credentials_raw) if credentials_raw is not None else True

    # Credenciales de Microsoft vienen del .env (no de la DB)
    settings = get_settings()
    client_id = settings.MICROSOFT_CLIENT_ID
    client_secret = settings.MICROSOFT_CLIENT_SECRET
    tenant_id = settings.MICROSOFT_TENANT_ID or ""
    is_active = bool(await _get_setting(db, "oauth_active") or False)

    microsoft_ready = bool(is_active and client_id and client_secret and tenant_id)

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
    """Recibe el authorization code de Microsoft, lo intercambia por tokens,
    obtiene el email del id_token y devuelve un par JWT propio del sistema.

    Crea el usuario automáticamente si no existe y su dominio está permitido.
    """
    from app.services.auth import sso as sso_service

    await _enforce_auth_rate_limit(request, "sso", get_settings().RATE_LIMIT_LOGIN_PER_MIN)
    return await sso_service.handle_microsoft_callback(
        db, request=request, code=body.code, redirect_uri=body.redirect_uri,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Autentica al usuario y emite par access/refresh JWT.

    Cada intento (exitoso o no) queda registrado en audit_log para detección de
    fuerza bruta. Cuentas deshabilitadas reciben 403 distintivo del 401 normal.
    """
    await _enforce_auth_rate_limit(request, "login", get_settings().RATE_LIMIT_LOGIN_PER_MIN)

    # Enforce credentials_enabled setting — reject at the backend level
    credentials_raw = await _get_setting(db, "auth_credentials_enabled")
    if credentials_raw is not None and not bool(credentials_raw):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El acceso por credenciales está deshabilitado. Use Microsoft SSO.",
        )

    user = await user_service.authenticate(db, body.email, body.password)
    client_ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    if not user:
        # Audit the failed attempt so security metrics can detect brute-force.
        # Store the attempted email in meta so the admin can group by target user.
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
    """Rota un refresh token válido por un par nuevo de access/refresh.

    Usado por el interceptor de axios al detectar un 401 en una llamada normal.
    """
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

    # Detección de reuso: un refresh ya rotado (su jti está en la denylist) no
    # puede volver a usarse. Esto bloquea el replay de un refresh robado tras
    # una rotación legítima.
    if await is_jti_revoked(payload.get("jti")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ya utilizado",
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

    # Rotación: invalida el refresh entrante para que no pueda reutilizarse.
    exp = payload.get("exp")
    if payload.get("jti") and exp:
        await revoke_jti(payload["jti"], datetime.datetime.fromtimestamp(exp, tz=datetime.timezone.utc))

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
    """Revoca el access token actual y el refresh token.

    Ambos jti se añaden a la denylist en Redis hasta su expiración natural.
    No falla si no hay token: cerrar sesión siempre debe "tener éxito".
    """
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


@router.post("/change-password", response_model=UserResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

    if verify_password(body.new_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contraseña debe ser diferente a la actual")

    current_user.hashed_password = hash_password(body.new_password)
    current_user.must_change_password = False
    # Invalida TODAS las sesiones previas (access + refresh) emitidas antes de
    # este instante. Cualquier token robado deja de servir tras el cambio.
    current_user.tokens_valid_after = datetime.datetime.now(datetime.timezone.utc)
    await log_action(
        db, action="auth.change_password", resource_type="user",
        actor_id=current_user.id, resource_id=str(current_user.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    return UserResponse.model_validate(current_user)



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
    """Marca el wizard como dismissed para este usuario.

    El frontend deja de mostrarlo aunque el sistema no esté completamente
    operativo. Útil cuando el admin ya conoce el flujo y quiere ir directo al
    panel.
    """
    current_user.onboarding_dismissed = True
    await db.commit()
    return OperationStatus()
