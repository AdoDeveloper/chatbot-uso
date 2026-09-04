from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_ip, require_perm
from app.core.permissions import P
from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.db.session import get_db
from app.models.global_setting import GlobalSetting
from app.services.notifications import smtp

router = APIRouter(prefix="/integrations", tags=["integrations"])

_reader = require_perm(P.SYSTEM_READ)
_admin  = require_perm(P.SYSTEM_UPDATE)


async def _get_row(db: AsyncSession, key: str) -> str | None:
    row = await db.get(GlobalSetting, key)
    return row.value if row else None


async def _set_row(db: AsyncSession, key: str, value: object) -> None:
    row = await db.get(GlobalSetting, key)
    if row:
        row.value = value
    else:
        db.add(GlobalSetting(key=key, value=value))


class SMTPConfigOut(BaseModel):
    host: str
    port: int
    user: str
    from_email: str
    tls: bool
    configured: bool


class SMTPTestRequest(BaseModel):
    to: EmailStr


class SMTPTestResult(BaseModel):
    success: bool
    message: str


@router.get("/smtp", response_model=SMTPConfigOut)
async def get_smtp(
    _: object = Depends(_reader),
):
    from app.core.config import get_settings
    s = get_settings()
    return SMTPConfigOut(
        host=s.SMTP_HOST,
        port=s.SMTP_PORT,
        user=s.SMTP_USER or "",
        from_email=s.SMTP_FROM or s.SMTP_USER or "",
        tls=s.SMTP_TLS,
        configured=bool(s.SMTP_HOST and s.SMTP_USER and s.SMTP_PASSWORD),
    )


class AuthMethodsConfig(BaseModel):
    credentials_enabled: bool = True


class AuthMethodsConfigOut(BaseModel):
    credentials_enabled: bool


@router.get("/auth-methods", response_model=AuthMethodsConfigOut)
async def get_auth_methods(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_reader),
):
    raw = await _get_row(db, "auth_credentials_enabled")
    enabled = raw if raw is not None else True
    return AuthMethodsConfigOut(credentials_enabled=bool(enabled))


@router.put("/auth-methods", response_model=AuthMethodsConfigOut)
async def update_auth_methods(
    body: AuthMethodsConfig,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    await _set_row(db, "auth_credentials_enabled", body.credentials_enabled)
    await db.commit()
    return AuthMethodsConfigOut(credentials_enabled=body.credentials_enabled)


OAUTH_PROVIDERS = ["microsoft"]


class OAuthConfig(BaseModel):
    provider: str = ""
    client_id: str = ""
    client_secret: str = ""
    tenant_id: str = ""
    allowed_domains: list[str] = []
    is_active: bool = False


class OAuthConfigOut(BaseModel):
    provider: str
    has_client_id: bool
    has_client_secret: bool
    tenant_id: str
    allowed_domains: list[str]
    is_active: bool
    configured: bool


@router.get("/oauth", response_model=OAuthConfigOut)
async def get_oauth(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_reader),
):
    from app.core.config import get_settings
    settings = get_settings()
    domains = await _get_row(db, "oauth_allowed_domains") or []
    is_active = bool(await _get_row(db, "oauth_active") or False)
    has_client_id = bool(settings.MICROSOFT_CLIENT_ID)
    has_client_secret = bool(settings.MICROSOFT_CLIENT_SECRET)
    tenant_id = settings.MICROSOFT_TENANT_ID or ""
    return OAuthConfigOut(
        provider="microsoft",
        has_client_id=has_client_id,
        has_client_secret=has_client_secret,
        tenant_id=tenant_id,
        allowed_domains=domains,
        is_active=is_active,
        configured=bool(has_client_id and has_client_secret and tenant_id),
    )


@router.put("/oauth", response_model=OAuthConfigOut)
async def update_oauth(
    body: OAuthConfig,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    await _set_row(db, "oauth_allowed_domains", body.allowed_domains)
    await _set_row(db, "oauth_active", body.is_active)
    await db.commit()

    from app.core.config import get_settings
    settings = get_settings()
    has_client_id = bool(settings.MICROSOFT_CLIENT_ID)
    has_client_secret = bool(settings.MICROSOFT_CLIENT_SECRET)
    tenant_id = settings.MICROSOFT_TENANT_ID or ""
    return OAuthConfigOut(
        provider="microsoft",
        has_client_id=has_client_id,
        has_client_secret=has_client_secret,
        tenant_id=tenant_id,
        allowed_domains=body.allowed_domains,
        is_active=body.is_active,
        configured=bool(has_client_id and has_client_secret and tenant_id),
    )


@router.post("/smtp/test", response_model=SMTPTestResult)
async def test_smtp(
    body: SMTPTestRequest,
    request: Request,
    _: object = Depends(_admin),
):
    # El destinatario es libre, asi que se acota el ritmo de envio para que
    # la prueba no sirva como via de reenvio hacia direcciones externas.
    try:
        await check_rate_limit(
            "integrations:smtp_test", get_client_ip(request),
            max_requests=5, window_seconds=60,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas pruebas de correo. Espere un momento y vuelva a intentarlo.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    cfg = await smtp.get_smtp_config()
    if not cfg:
        return SMTPTestResult(success=False, message="SMTP no configurado en el servidor.")

    from app.services.notifications import templates as tpl

    intro = "Este es un mensaje de prueba enviado desde la plataforma de gestión de la Universidad de Sonsonate."
    content = tpl.paragraph(intro)
    content += tpl.paragraph(
        "Si ha recibido este mensaje, la configuración del servidor de correo es correcta "
        "y el sistema puede enviar notificaciones."
    )
    content += tpl.detail_table(
        {"Servidor": f"{cfg.host}:{cfg.port}", "Remitente": cfg.from_email,
         "Cifrado": "STARTTLS" if cfg.tls else "Sin cifrado"},
        heading_text="Parámetros utilizados",
    )
    ok = await smtp.send_email(
        to=body.to,
        subject="Prueba de configuración de correo",
        body_html=tpl.render_email(
            title="Prueba de configuración de correo", content=content, preheader=intro,
        ),
        body_text=f"{intro}\nSi ha recibido este mensaje, la configuración de correo es correcta.",
        _config=cfg,
    )
    return SMTPTestResult(
        success=ok,
        message="Email enviado correctamente." if ok else "No se pudo enviar el correo. Revise la configuración SMTP del servidor.",
    )
