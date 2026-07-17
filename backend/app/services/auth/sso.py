from __future__ import annotations

import datetime

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_client_ip
from app.models.global_setting import GlobalSetting
from app.schemas.auth import TokenResponse, UserResponse
from app.services.system import rbac as rbac_service
from app.services.system.audit import log_action
from app.services.users import service as user_service


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    from sqlalchemy import select
    result = await db.execute(select(GlobalSetting.value).where(GlobalSetting.key == key))
    row = result.scalar_one_or_none()
    return row


def _token_response(user, access: str, refresh: str) -> TokenResponse:
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse.model_validate(user),
    )


async def handle_microsoft_callback(
    db: AsyncSession, *, request: Request, code: str, redirect_uri: str,
) -> TokenResponse:
    """Recibe el authorization code de Microsoft, lo intercambia por tokens,
    obtiene el email del id_token y devuelve un par JWT propio del sistema.

    Crea el usuario automáticamente si no existe y su dominio está permitido.
    """
    # Credenciales vienen del .env; is_active y allowed_domains de la DB
    settings = get_settings()
    client_id = settings.MICROSOFT_CLIENT_ID
    client_secret = settings.MICROSOFT_CLIENT_SECRET
    tenant_id = settings.MICROSOFT_TENANT_ID or ""
    _raw_domains = await _get_setting(db, "oauth_allowed_domains")
    allowed_domains: list[str] = _raw_domains if isinstance(_raw_domains, list) else []
    is_active = bool(await _get_setting(db, "oauth_active") or False)

    _GENERIC = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales incorrectas",
    )
    client_ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    if not is_active or not client_id or not client_secret or not tenant_id:
        raise _GENERIC

    allowed_redirect = settings.MICROSOFT_REDIRECT_URI
    if allowed_redirect:
        redirect_valid = redirect_uri == allowed_redirect
    else:
        allowed = set(settings.ALLOWED_ORIGINS)
        redirect_valid = any(redirect_uri == o or redirect_uri.startswith(o + "/") for o in allowed)
    if not redirect_valid:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": "invalid_redirect_uri",
                               "redirect_uri": redirect_uri[:200]})
        await db.commit()
        raise _GENERIC

    # Exchange authorization code for tokens
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(token_url, data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "scope": "openid email profile",
            })
    except Exception as exc:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": f"token_exchange_error: {exc}"})
        await db.commit()
        raise _GENERIC

    if resp.status_code != 200:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": f"ms_token_error: {resp.status_code}"})
        await db.commit()
        raise _GENERIC

    id_token = resp.json().get("id_token")
    if not id_token:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": "no_id_token"})
        await db.commit()
        raise _GENERIC

    try:
        # Verify the id_token signature using Microsoft's public JWKS.
        # PyJWT 2.x PyJWKClient fetches the key set from the OIDC discovery endpoint.
        from jwt import PyJWKClient
        jwks_url = (
            f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}"
            "/discovery/v2.0/keys"
        )
        jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        import jwt as _pyjwt
        claims = _pyjwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.MICROSOFT_CLIENT_ID,
        )
    except Exception as exc:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": f"id_token_decode_error: {exc}"})
        await db.commit()
        raise _GENERIC

    email = (claims.get("email") or claims.get("preferred_username") or "").lower().strip()
    if not email or "@" not in email:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": "no_email_in_claims"})
        await db.commit()
        raise _GENERIC

    if allowed_domains:
        domain = "@" + email.split("@")[1]
        if domain not in allowed_domains:
            await log_action(db, action="auth.login_sso_failed", resource_type="user",
                             actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                             meta={"provider": "microsoft", "reason": "domain_not_allowed",
                                   "email": email, "domain": domain})
            await db.commit()
            raise _GENERIC

    user = await user_service.get_by_email(db, email)
    if not user:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=None, resource_id=None, ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": "user_not_found", "email": email})
        await db.commit()
        raise _GENERIC

    if not user.is_active:
        await log_action(db, action="auth.login_sso_failed", resource_type="user",
                         actor_id=user.id, resource_id=str(user.id), ip=client_ip, user_agent=ua,
                         meta={"provider": "microsoft", "reason": "account_disabled", "email": email})
        await db.commit()
        raise _GENERIC

    user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    await log_action(
        db, action="auth.login_sso", resource_type="user",
        actor_id=user.id, resource_id=str(user.id),
        ip=client_ip, user_agent=ua,
        meta={"provider": "microsoft", "email": email},
    )
    await db.commit()

    return _token_response(
        user, *await rbac_service.issue_user_tokens(db, user)
    )
