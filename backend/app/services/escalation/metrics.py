"""Métricas y agregados de escalaciones para la bandeja de Historial."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, EscalationEventType
from app.models.escalation_event import EscalationEvent


_ESCALATION_STATES = (
    ConversationStatus.escalated,
    ConversationStatus.resolved,
)


async def get_metrics(
    db: AsyncSession, *, days: int = 30, until: datetime | None = None,
) -> dict:
    """KPIs globales del módulo de escalaciones para los últimos N días.

    Retorna:
    - total: cuántas conversaciones fueron escaladas en el periodo
    - by_status: desglose por estado actual
    - by_trigger: desglose por tipo de trigger
    - avg_resolution_seconds: tiempo promedio de resolución (solo cerradas)
    - resolution_rate: % resueltas vs total cerradas (resueltas / (resueltas + abandonadas))
    - csat_avg: promedio de CSAT entre los que tienen score
    """
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=max(1, days))

    total_q = select(func.count(ChatConversation.id)).where(
        ChatConversation.escalated_at.is_not(None),
        ChatConversation.escalated_at >= since,
        ChatConversation.escalated_at < _until,
    )
    total = (await db.execute(total_q)).scalar_one()

    by_status_q = (
        select(ChatConversation.status, func.count(ChatConversation.id))
        .where(ChatConversation.escalated_at.is_not(None))
        .where(ChatConversation.escalated_at >= since)
        .where(ChatConversation.escalated_at < _until)
        .group_by(ChatConversation.status)
    )
    by_status = {
        row[0].value: row[1]
        for row in (await db.execute(by_status_q)).all()
        if row[0] in _ESCALATION_STATES
    }

    by_trigger_q = (
        select(EscalationEvent.trigger_type, func.count(EscalationEvent.id))
        .where(EscalationEvent.event_type == EscalationEventType.escalated)
        .where(EscalationEvent.created_at >= since)
        .where(EscalationEvent.created_at < _until)
        .group_by(EscalationEvent.trigger_type)
    )
    by_trigger = {
        (row[0] or "manual"): row[1]
        for row in (await db.execute(by_trigger_q)).all()
    }

    # Tiempo promedio de resolución en segundos, portable MySQL/SQLite.
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        diff_seconds = (
            func.julianday(ChatConversation.resolved_at)
            - func.julianday(ChatConversation.escalated_at)
        ) * 86400.0
    else:
        diff_seconds = func.timestampdiff(
            literal_column("SECOND"),
            ChatConversation.escalated_at,
            ChatConversation.resolved_at,
        )
    avg_q = select(func.avg(diff_seconds)).where(
        ChatConversation.escalated_at.is_not(None),
        ChatConversation.escalated_at >= since,
        ChatConversation.escalated_at < _until,
        ChatConversation.resolved_at.is_not(None),
        ChatConversation.status == ConversationStatus.resolved,
    )
    avg_seconds = (await db.execute(avg_q)).scalar_one_or_none()

    closed_q = select(
        func.sum(case((ChatConversation.status == ConversationStatus.resolved, 1), else_=0)).label("resolved"),
    ).where(
        ChatConversation.escalated_at.is_not(None),
        ChatConversation.escalated_at >= since,
        ChatConversation.escalated_at < _until,
    )
    row = (await db.execute(closed_q)).one()
    resolved_count = int(row.resolved or 0)
    resolution_rate = (resolved_count / total) if total > 0 else None

    csat_q = select(func.avg(ChatConversation.csat_score)).where(
        ChatConversation.escalated_at.is_not(None),
        ChatConversation.escalated_at >= since,
        ChatConversation.escalated_at < _until,
        ChatConversation.csat_score.is_not(None),
    )
    csat_avg = (await db.execute(csat_q)).scalar_one_or_none()

    return {
        "days": days,
        "total": int(total or 0),
        "by_status": by_status,
        "by_trigger": by_trigger,
        "avg_resolution_seconds": float(avg_seconds) if avg_seconds is not None else None,
        "resolved_count": resolved_count,
        "resolution_rate": float(resolution_rate) if resolution_rate is not None else None,
        "csat_avg": float(csat_avg) if csat_avg is not None else None,
    }
