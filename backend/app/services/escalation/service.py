from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationEvent
from app.services.escalation import lifecycle as escalation_lifecycle
from app.services.notifications.service import send_notification

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
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id)
            await escalation_lifecycle.mark_escalated(
                db, conversation_id=conv_uuid,
                trigger_type=trigger_type,
                meta={"reason": reason, "question": question[:500] if question else None},
            )
        except Exception as e:
            log.warning("escalation.lifecycle_mark_failed", error=str(e), conversation_id=conversation_id)

    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "question": question,
        "reason": reason,
        **{k: v for k, v in (extra or {}).items() if k != "contact_info"},
    }
    contact_info = (extra or {}).get("contact_info")
    if isinstance(contact_info, dict):
        key = "contact_email" if contact_info.get("type") == "email" else "contact_whatsapp"
        payload = {key: str(contact_info.get("value", "")), **payload}

    await send_notification(db, event=NotificationEvent.escalation, payload=payload)
    log.info("escalation.dispatched", reason=reason)
