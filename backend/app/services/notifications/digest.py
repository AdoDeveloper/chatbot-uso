from __future__ import annotations

"""Recopilación de estadísticas para el resumen diario (unanswered_daily).

Reúne, en una sola pasada por la base de datos, las métricas que componen el
correo de resumen: preguntas sin responder (nuevas vs acumuladas), temas más
frecuentes, las preguntas más recientes y la actividad de escalamiento y
resolución del día.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, UnansweredStatus
from app.models.unanswered_question import UnansweredQuestion

# Cuántas preguntas recientes listar en el correo.
_RECENT_LIMIT = 5
# Cuántos temas frecuentes listar.
_TOPIC_LIMIT = 5


async def collect_daily_digest_stats(db: AsyncSession) -> dict[str, Any]:
    """Devuelve el payload completo del resumen diario.

    Las claves se consumen en `service._html_body` para el evento
    unanswered_daily.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    # Preguntas sin responder: acumuladas (open) y nuevas en las últimas 24 h.
    total_open = (await db.execute(
        select(func.count(UnansweredQuestion.id))
        .where(UnansweredQuestion.status == UnansweredStatus.open)
    )).scalar_one()

    new_open = (await db.execute(
        select(func.count(UnansweredQuestion.id))
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .where(UnansweredQuestion.created_at >= since)
    )).scalar_one()

    # Resueltas en el día.
    resolved_today = (await db.execute(
        select(func.count(UnansweredQuestion.id))
        .where(UnansweredQuestion.status == UnansweredStatus.resolved)
        .where(UnansweredQuestion.resolved_at >= since)
    )).scalar_one()

    # Temas más frecuentes entre las preguntas open (excluye sin tema).
    topic_rows = (await db.execute(
        select(UnansweredQuestion.detected_topic, func.count(UnansweredQuestion.id).label("n"))
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .where(UnansweredQuestion.detected_topic.isnot(None))
        .where(UnansweredQuestion.detected_topic != "")
        .group_by(UnansweredQuestion.detected_topic)
        .order_by(func.count(UnansweredQuestion.id).desc())
        .limit(_TOPIC_LIMIT)
    )).all()
    top_topics = [(topic, n) for topic, n in topic_rows]

    # Preguntas más recientes sin responder.
    recent_rows = (await db.execute(
        select(UnansweredQuestion.question)
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .order_by(UnansweredQuestion.created_at.desc())
        .limit(_RECENT_LIMIT)
    )).all()
    recent_questions = [q for (q,) in recent_rows]

    # Conversaciones escaladas y resueltas en el día.
    escalated_today = (await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.escalated_at >= since)
    )).scalar_one()

    conversations_resolved_today = (await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.resolved_at >= since)
        .where(ChatConversation.status == ConversationStatus.resolved)
    )).scalar_one()

    return {
        "date": now.strftime("%Y-%m-%d"),
        "total_open": total_open,
        "new_open": new_open,
        "resolved_today": resolved_today,
        "top_topics": top_topics,
        "recent_questions": recent_questions,
        "escalated_today": escalated_today,
        "conversations_resolved_today": conversations_resolved_today,
    }
