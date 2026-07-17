from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.enums import UnansweredStatus
from app.models.unanswered_question import UnansweredQuestion
from app.models.user import User
from app.schemas.unanswered import CreateFAQFromUnanswered, UnansweredGroup, UnansweredGroupList, UnansweredQuestionOut

router = APIRouter(prefix="/unanswered", tags=["unanswered"])


@router.get("", response_model=UnansweredGroupList)
async def list_grouped(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    """Devuelve las preguntas sin respuesta agrupadas por tema detectado.

    Solo incluye preguntas en estado distinto a `resuelto`. El frontend usa
    este endpoint para que el editor convierta cada pregunta en FAQ o la
    marque como resuelta tras añadir la fuente correspondiente.
    """
    result = await db.execute(
        select(UnansweredQuestion)
        .where(UnansweredQuestion.status != UnansweredStatus.resolved)
        .order_by(UnansweredQuestion.created_at.desc())
    )
    questions = list(result.scalars().all())

    groups: dict[str, list[UnansweredQuestion]] = {}
    for q in questions:
        # Normalizamos el tópico para evitar duplicados por capitalización en el UI
        topic = (q.detected_topic or "Sin clasificar").strip().title()
        groups.setdefault(topic, []).append(q)

    group_list = []
    # Ordenamos por los más recientes primero para el Dashboard
    for topic, qs in sorted(groups.items(), key=lambda x: max(q.created_at for q in x[1]), reverse=True):
        group_list.append(
            UnansweredGroup(
                topic=topic,
                count=len(qs),
                first_seen=min(q.created_at for q in qs),
                last_seen=max(q.created_at for q in qs),
                questions=[UnansweredQuestionOut.model_validate(q) for q in qs],
            )
        )

    return UnansweredGroupList(groups=group_list, total=len(questions))


@router.post("/{question_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_question(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    """Marca una pregunta como resuelta sin crear FAQ.

    Útil cuando el editor ya añadió un documento que cubre la pregunta y solo
    necesita limpiar la cola de pendientes.
    """
    result = await db.execute(select(UnansweredQuestion).where(UnansweredQuestion.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise NotFoundError("Pregunta no encontrada")
    q.status = UnansweredStatus.resolved
    q.resolved_by_id = current_user.id
    q.resolved_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/{question_id}/create-faq", status_code=status.HTTP_201_CREATED)
async def create_faq_from_unanswered(
    question_id: uuid.UUID,
    body: CreateFAQFromUnanswered,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    """Convierte una pregunta sin respuesta en una FAQ y la marca como resuelta.

    Crea automáticamente:
      - Un FAQEntry con la pregunta original + respuesta proporcionada.
      - Una Source de tipo `faq` con sus chunks embedidos en Qdrant.
    De esa forma la próxima vez que un usuario pregunte algo similar, el bot
    encuentra la FAQ vía retrieval semántico.
    """
    from app.services.knowledge import faq as faq_svc

    result = await db.execute(select(UnansweredQuestion).where(UnansweredQuestion.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise NotFoundError("Pregunta no encontrada")

    entry = await faq_svc.create_faq(
        db,
        question=q.question,
        answer=body.answer,
        tags=body.tags,
        created_by_id=current_user.id,
    )
    q.status = UnansweredStatus.resolved
    q.resolved_by_id = current_user.id
    q.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"faq_id": str(entry.id)}



@router.get("/{question_id}/root-cause", response_model=dict)
async def root_cause(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    """Análisis automático del motivo por el que el bot no respondió."""
    from app.services.knowledge import unanswered_diagnostics

    return await unanswered_diagnostics.root_cause_analysis(db, question_id=question_id)
