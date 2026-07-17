from __future__ import annotations

import structlog
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class SMTPSettings:
    host: str
    port: int
    user: str
    password: str
    from_email: str
    tls: bool


async def get_smtp_config(db=None) -> SMTPSettings | None:
    """Lee la config SMTP exclusivamente del .env (variables de entorno)."""
    from app.core.config import get_settings
    s = get_settings()
    if s.SMTP_HOST and s.SMTP_USER and s.SMTP_PASSWORD:
        return SMTPSettings(
            host=s.SMTP_HOST, port=s.SMTP_PORT, user=s.SMTP_USER,
            password=s.SMTP_PASSWORD, from_email=s.SMTP_FROM or s.SMTP_USER,
            tls=s.SMTP_TLS,
        )
    return None


async def send_invitation_email(*, to: str, role: str | None = None, invite_url: str, invited_by: str | None = None) -> bool:
    """Envía el correo de invitación con el enlace de registro."""
    from app.services.notifications import templates as tpl

    subject = "Invitación de acceso"
    intro = "Ha recibido una invitación para acceder a la plataforma de gestión de la Universidad de Sonsonate."

    content = tpl.paragraph(intro)
    detail = {}
    if invited_by:
        detail["Invitado por"] = invited_by
    if role:
        detail["Rol asignado"] = role
    if detail:
        content += tpl.detail_table(detail, heading_text="Detalle de la invitación")
    content += tpl.paragraph("Para crear su cuenta y establecer su contraseña, acceda al siguiente enlace:")
    content += tpl.button("Aceptar invitación", invite_url)
    content += tpl.muted_note(
        f"Si el enlace no funciona, copie y pegue esta dirección en su navegador: {invite_url}"
    )
    content += tpl.muted_note(
        "Por seguridad, este enlace caduca en poco tiempo. Si no esperaba esta invitación, ignore este mensaje."
    )

    body_html = tpl.render_email(title=subject, content=content, preheader=intro)
    body_text = (
        f"{intro}\n\nAcepte su invitación en el siguiente enlace:\n{invite_url}\n\n"
        f"{tpl.BRAND_NAME}."
    )
    return await send_email(to=to, subject=subject, body_html=body_html, body_text=body_text)


async def send_email(
    *,
    to: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    _config: SMTPSettings | None = None,
    db=None,
) -> bool:
    cfg = _config or await get_smtp_config(db)
    if not cfg:
        log.warning("smtp.not_configured")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.from_email
    msg["To"] = to

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            start_tls=cfg.tls,
        )
        log.info("smtp.sent", to=to, subject=subject)
        return True
    except aiosmtplib.SMTPAuthenticationError as exc:
        log.error("smtp.auth_failed", host=cfg.host, user=cfg.user, error=exc.message)
        return False
    except aiosmtplib.SMTPConnectError as exc:
        log.error("smtp.connect_failed", host=cfg.host, port=cfg.port, error=exc.message)
        return False
    except aiosmtplib.SMTPTimeoutError as exc:
        log.error("smtp.timeout", host=cfg.host, port=cfg.port, error=exc.message)
        return False
    except aiosmtplib.SMTPNotSupported as exc:
        log.error("smtp.tls_not_supported", host=cfg.host, tls=cfg.tls, error=exc.message)
        return False
    except aiosmtplib.SMTPException as exc:
        log.error("smtp.protocol_error", host=cfg.host, error=str(exc))
        return False
    except OSError as exc:
        log.error("smtp.network_error", host=cfg.host, port=cfg.port, error=str(exc))
        return False
    except Exception as exc:
        log.error("smtp.unexpected_error", error=str(exc))
        return False
