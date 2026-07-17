from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.chat_message import ChatMessage
from app.models.enums import MessageRole
from app.models.unanswered_question import UnansweredQuestion


async def root_cause_analysis(db: AsyncSession, *, question_id: uuid.UUID) -> dict:
    """Análisis automático del motivo por el que el bot no respondió.

    Heurísticas:
    - Si la última respuesta del bot tuvo `rag_route='no_context'` → "Sin cobertura"
    - Si tuvo score < 0.3 (chunks de baja confianza) → "Confianza baja en chunks"
    - Si el bot repitió la misma respuesta 2+ veces → "Bucle de respuestas"
    - Si la pregunta ya apareció N veces → "Pregunta recurrente"
    - Default → "Indeterminado"
    """
    result = await db.execute(select(UnansweredQuestion).where(UnansweredQuestion.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise NotFoundError("Pregunta no encontrada")

    causes: list[dict] = []
    suggestions: list[str] = []

    # Frecuencia: misma pregunta repetida
    text = (q.question or "").strip().lower()
    if text:
        rep_q = await db.execute(
            select(func.count(UnansweredQuestion.id))
            .where(func.lower(UnansweredQuestion.question) == text)
        )
        rep = int(rep_q.scalar_one() or 0)
        if rep >= 3:
            causes.append({
                "code": "recurring",
                "label": "Pregunta recurrente",
                "detail": f"Esta pregunta apareció {rep} veces sin respuesta satisfactoria.",
            })
            suggestions.append("Convertir en FAQ formal o agregar una fuente que la cubra.")

    # Análisis de la conversación origen
    if q.conversation_id:
        msgs_q = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == q.conversation_id)
            .order_by(ChatMessage.created_at.asc())
        )
        msgs = list(msgs_q.scalars().all())
        bot_msgs = [m for m in msgs if m.role == MessageRole.assistant]

        if bot_msgs:
            last = bot_msgs[-1]
            route = (last.rag_route or "").lower()
            if "no_context" in route or "no_match" in route:
                causes.append({
                    "code": "no_coverage",
                    "label": "Sin cobertura RAG",
                    "detail": f"La última respuesta usó la ruta '{route}', sin chunks recuperados con confianza suficiente.",
                })
                suggestions.append(
                    f"Agregar un documento que cubra el tema {q.detected_topic or '(sin clasificar)'}."
                )

            # Detectar bucle: 2+ respuestas idénticas seguidas
            if len(bot_msgs) >= 2:
                tail = [(m.content or "").strip().lower() for m in bot_msgs[-3:]]
                if len(tail) >= 2 and tail[-1] == tail[-2]:
                    causes.append({
                        "code": "loop",
                        "label": "Bucle de respuestas",
                        "detail": "El bot devolvió la misma respuesta varias veces seguidas.",
                    })
                    suggestions.append("Revisar el prompt o agregar un trigger de escalación 'loop_detected'.")

            # Score bajo en sources
            try:
                sources = last.sources_json or []
                if sources:
                    scores = [float(s.get("score") or 0) for s in sources if isinstance(s, dict)]
                    if scores and max(scores) < 0.3:
                        causes.append({
                            "code": "low_confidence",
                            "label": "Confianza baja en chunks",
                            "detail": f"Mejor chunk con score {max(scores):.2f} (umbral típico 0.5+).",
                        })
                        suggestions.append("Aumentar el umbral de score_threshold o reformular la consulta.")
            except Exception:
                pass

    if not causes:
        causes.append({
            "code": "indeterminate",
            "label": "Indeterminado",
            "detail": "No se identificó una causa raíz automática. Revisa la conversación original.",
        })

    return {
        "question_id": str(q.id),
        "detected_topic": q.detected_topic,
        "causes": causes,
        "suggestions": suggestions,
    }
