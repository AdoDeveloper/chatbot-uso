"""Lifecycle de conversaciones escaladas - funciones esenciales."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, EscalationEventType
from app.models.escalation_event import EscalationEvent

log = structlog.get_logger()


async def _load(db: AsyncSession, conversation_id: uuid.UUID) -> ChatConversation:
    result = await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada")
    return conv


async def mark_escalated(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    trigger_type: str | None = None,
    meta: dict | None = None,
) -> ChatConversation:
    """Marca la conversación como escalada cuando el usuario da su consentimiento."""
    conv = await _load(db, conversation_id)
    if conv.status == ConversationStatus.escalated:
        if meta and meta.get("contact"):
            last = (await db.execute(
                select(EscalationEvent)
                .where(EscalationEvent.conversation_id == conv.id)
                .where(EscalationEvent.event_type == EscalationEventType.escalated)
                .order_by(EscalationEvent.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if last:
                last.meta_json = {**(last.meta_json or {}), "contact": meta["contact"]}
                await db.commit()
        return conv
    conv.status = ConversationStatus.escalated
    conv.escalated_at = datetime.now(timezone.utc)
    ev = EscalationEvent(
        conversation_id=conv.id,
        event_type=EscalationEventType.escalated,
        actor_user_id=None,
        meta_json=meta,
        trigger_type=trigger_type,
    )
    db.add(ev)
    await db.commit()
    return conv


async def record_csat(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    score: int,
    comment: str | None = None,
    reasons: list[str] | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> ChatConversation:
    if not (1 <= score <= 5):
        raise HTTPException(status_code=400, detail="CSAT debe estar entre 1 y 5")
    conv = await _load(db, conversation_id)
    conv.csat_score = score
    conv.csat_comment = comment or None
    conv.csat_reasons = reasons or []
    ev = EscalationEvent(
        conversation_id=conv.id,
        event_type=EscalationEventType.csat_recorded,
        actor_user_id=actor_user_id,
        meta_json={
            "score": score,
            **({"comment": comment} if comment else {}),
            **({"reasons": reasons} if reasons else {}),
        },
    )
    db.add(ev)
    await db.commit()
    return conv


async def latest_contacts(db: AsyncSession, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Contacto que dejó el visitante al escalar, por conversación."""
    if not conversation_ids:
        return {}
    rows = (await db.execute(
        select(EscalationEvent.conversation_id, EscalationEvent.meta_json)
        .where(EscalationEvent.conversation_id.in_(conversation_ids))
        .where(EscalationEvent.event_type == EscalationEventType.escalated)
        .order_by(EscalationEvent.created_at.desc())
    )).all()
    contacts: dict[uuid.UUID, dict] = {}
    for conv_id, meta in rows:
        contact = (meta or {}).get("contact")
        if conv_id not in contacts and isinstance(contact, dict) and contact.get("value"):
            contacts[conv_id] = {"type": str(contact.get("type", "")), "value": str(contact["value"])}
    return contacts
