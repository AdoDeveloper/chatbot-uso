from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationChannel, UserRole
from app.models.notification_log import NotificationLog
from app.models.user import User
from app.services.escalation import lifecycle as escalation_lifecycle
from app.services.notifications import smtp
from app.services.notifications import templates as tpl

log = structlog.get_logger()


async def dispatch_escalation(
    db: AsyncSession,
    *,
    conversation_id: str,
    question: str,
    reason: str,
    trigger_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    # Marcar la conversación como escalada antes de enviar correos — así el
    # estado en DB es consistente aunque falle la entrega de algún email.
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id)
            await escalation_lifecycle.mark_escalated(
                db, conversation_id=conv_uuid,
                trigger_type=trigger_type,
                meta={"reason": reason, "question": question[:500] if question else None},
            )
        except (ValueError, Exception) as e:
            log.warning("escalation.lifecycle_mark_failed", error=str(e), conversation_id=conversation_id)

    result = await db.execute(
        select(User).where(User.is_active.is_(True), User.role == UserRole.admin)
    )
    admins = result.scalars().all()

    payload = {
        "conversation_id": conversation_id,
        "question": question,
        "reason": reason,
        **(extra or {}),
    }
    body = _build_html(payload)
    subject = f"Conversación escalada: {reason}"

    sent = 0
    for admin in admins:
        if not admin.email:
            continue
        ok = False
        error_message = None
        try:
            ok = await smtp.send_email(to=admin.email, subject=subject, body_html=body)
            if ok:
                sent += 1
            else:
                error_message = "No se pudo enviar el correo (ver logs del servidor para el detalle)."
        except Exception as exc:
            log.warning("escalation.email_failed", user_id=str(admin.id), error=str(exc))
            error_message = str(exc)[:500]
        db.add(NotificationLog(
            event="escalation",
            channel=NotificationChannel.email.value,
            target=admin.email,
            status="sent" if ok else "failed",
            error_message=error_message,
            payload_json=payload,
        ))

    db.add(NotificationLog(
        event="escalation",
        channel=NotificationChannel.in_app.value,
        target="in_app",
        status="sent",
        error_message=None,
        payload_json=payload,
    ))

    await db.commit()
    log.info("escalation.dispatched", recipients=sent, total_admins=len(admins), reason=reason)


_ESC_FIELD_LABELS = {
    "conversation_id": "Identificador de conversación",
    "question": "Pregunta del usuario",
    "reason": "Motivo del escalamiento",
}


def _build_html(payload: dict[str, Any]) -> str:
    title = "Conversación escalada"
    intro = (
        "Un usuario solicitó ser contactado por una persona del equipo. "
        "A continuación se incluyen sus datos y el contexto de la conversación."
    )

    content = tpl.paragraph(intro)

    rows = {
        _ESC_FIELD_LABELS.get(k, k.replace("_", " ").capitalize()): v
        for k, v in payload.items()
        if k != "contact_info"
    }

    contact_info = payload.get("contact_info")
    if contact_info and isinstance(contact_info, dict):
        is_email = contact_info.get("type") == "email"
        label = "Contacto por correo electrónico" if is_email else "Contacto por WhatsApp"
        rows = {label: str(contact_info.get("value", "")), **rows}

    if rows:
        content += tpl.detail_table(rows, heading_text="Detalle de la conversación")

    content += tpl.paragraph(
        "Le solicitamos comunicarse con el usuario a la brevedad utilizando los datos de contacto proporcionados."
    )

    return tpl.render_email(title=title, content=content, preheader=intro)
