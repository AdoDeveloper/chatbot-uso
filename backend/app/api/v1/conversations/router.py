from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field as _Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.db.session import get_db
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus
from app.models.user import User
from app.schemas.chat_history import ChatConversationDetail, ChatConversationOut, FeedbackUpdate
from app.services.chat import history as svc
from app.services.escalation import lifecycle as lifecycle_svc
from app.services.ingestion.export import excel_response, pdf_response
from pydantic import BaseModel as _BM


class AnnotateRequest(_BM):
    annotation: str  # correct, incorrect, hallucination, partial
    note: str | None = None


class _TagsBody(_BM):
    tags: list[str]


class _BulkBody(_BM):
    conversation_ids: list[uuid.UUID] = _Field(..., max_length=200)
    action: str  # "resolve" | "add_tag" | "remove_tag" | "set_tags"
    tag: str | None = None
    tags: list[str] | None = None
    note: str | None = None


class ConversationStatusUpdate(_BM):
    status: ConversationStatus
    resolution_note: str | None = None

router = APIRouter(prefix="/conversations", tags=["conversations"])

_SourceQ = Query("production", pattern="^(production|playground)$")


@router.get("", response_model=dict)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    status_filter: ConversationStatus | None = Query(None, alias="status"),
    tag: str | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    convs, total = await svc.list_conversations(
        db, page=page, page_size=page_size,
        search=search, date_from=date_from, date_to=date_to,
        status_filter=status_filter, tag=tag, source=source,
    )
    conv_ids = [c.id for c in convs]
    first_msgs = await svc.fetch_first_user_messages(db, conv_ids)
    cnt_rows = await db.execute(
        select(ChatMessage.conversation_id, func.count().label("n"))
        .where(ChatMessage.conversation_id.in_(conv_ids))
        .group_by(ChatMessage.conversation_id)
    )
    counts = {row.conversation_id: row.n for row in cnt_rows}
    items = []
    for c in convs:
        out = ChatConversationOut.model_validate(c)
        out.message_count = counts.get(c.id, 0)
        preview = first_msgs.get(c.id)
        if preview:
            out.first_user_message = preview[:160]
        items.append(out.model_dump())
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/export")
async def export_conversations(
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    search: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    """Exporta conversaciones como Excel o PDF."""
    try:
        await check_rate_limit(
            "chat:export", str(current_user.id),
            max_requests=20, window_seconds=3600,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiadas exportaciones. Reintenta en {exc.retry_after}s.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    convs_page, _ = await svc.list_conversations(
        db, page=1, page_size=5000,
        search=search, date_from=date_from, date_to=date_to, source=source,
    )
    conv_ids = [c.id for c in convs_page]

    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.id.in_(conv_ids))
        .options(selectinload(ChatConversation.messages))
        .order_by(ChatConversation.started_at.desc())
    )
    convs = result.scalars().all()

    rows = []
    for conv in convs:
        for msg in conv.messages:
            rows.append({
                "Conversación ID": str(conv.id),
                "Sesión": conv.session_id,
                "Dispositivo": conv.device or "",
                "Inicio": str(conv.started_at)[:19],
                "Rol": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "Contenido": msg.content,
                "Latencia ms": msg.latency_ms,
                "Ruta RAG": msg.rag_route or "",
                "Valoración": {"positive": "Positiva", "negative": "Negativa"}.get(
                    (msg.feedback.value if hasattr(msg.feedback, "value") else str(msg.feedback)) if msg.feedback else "",
                    "") if msg.feedback else "",
                "Fecha mensaje": str(msg.created_at)[:19],
            })

    if format == "pdf":
        return pdf_response(rows, "conversaciones", title="Historial de Conversaciones")
    return excel_response(rows, "conversaciones", sheet_name="Conversaciones")


@router.get("/tags", response_model=list[dict])
async def list_known_tags(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    """Lista de tags únicos en uso, con su frecuencia."""
    from collections import Counter
    result = await db.execute(
        select(ChatConversation.tags).limit(5000)
    )
    counter: Counter = Counter()
    for (tags,) in result.all():
        if isinstance(tags, list):
            counter.update(t for t in tags if t)
    return [{"tag": t, "count": c} for t, c in counter.most_common(100)]


@router.post("/bulk", response_model=dict)
async def bulk_action(
    body: _BulkBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    """Aplica una acción a múltiples conversaciones de una sola vez."""
    if not body.conversation_ids:
        return {"affected": 0, "errors": []}
    if body.action not in {"resolve", "add_tag", "remove_tag", "set_tags"}:
        raise HTTPException(status_code=400, detail=f"Acción no soportada: {body.action}")

    result = await db.execute(
        select(ChatConversation).where(ChatConversation.id.in_(body.conversation_ids))
    )
    convs_by_id = {conv.id: conv for conv in result.scalars().all()}

    affected = 0
    errors: list[dict] = []
    for cid in body.conversation_ids:
        conv = convs_by_id.get(cid)
        if not conv:
            errors.append({"id": str(cid), "error": "no encontrada"})
            continue
        try:
            if body.action == "resolve":
                conv.status = ConversationStatus.resolved
                conv.resolved_at = datetime.now(timezone.utc)
                conv.resolved_by_user_id = current_user.id
            else:
                current_tags = list(conv.tags or [])
                if body.action == "add_tag" and body.tag:
                    t = body.tag.strip().lower()
                    if t and t not in current_tags:
                        current_tags.append(t)
                elif body.action == "remove_tag" and body.tag:
                    t = body.tag.strip().lower()
                    current_tags = [x for x in current_tags if x != t]
                elif body.action == "set_tags" and body.tags is not None:
                    current_tags = sorted(set(t.strip().lower() for t in body.tags if t.strip()))
                conv.tags = current_tags
            affected += 1
        except HTTPException as e:
            errors.append({"id": str(cid), "error": e.detail})
        except Exception as e:
            errors.append({"id": str(cid), "error": str(e)[:120]})
    await db.commit()
    return {"affected": affected, "errors": errors, "action": body.action}


@router.get("/{conversation_id}", response_model=ChatConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_READ)),
):
    conv = await svc.get_conversation(db, conversation_id)
    if not conv:
        raise NotFoundError("Conversación no encontrada")
    await db.refresh(conv, ["messages"])
    count = len(conv.messages)
    out = ChatConversationDetail.model_validate(conv)
    out.message_count = count
    return out


@router.patch("/{conversation_id}/status", response_model=dict)
async def update_conversation_status(
    conversation_id: uuid.UUID,
    body: ConversationStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    result = await db.execute(select(ChatConversation).where(ChatConversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversación no encontrada")
    conv.status = body.status
    if body.status == ConversationStatus.resolved:
        conv.resolved_at = datetime.now(timezone.utc)
        conv.resolved_by_user_id = current_user.id
    await db.commit()
    return {"id": str(conv.id), "status": conv.status.value}


class _CsatBody(_BM):
    score: int


@router.post("/{conversation_id}/csat", response_model=dict)
async def record_csat(
    conversation_id: uuid.UUID,
    body: _CsatBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    conv = await lifecycle_svc.record_csat(
        db, conversation_id=conversation_id, score=body.score, actor_user_id=current_user.id,
    )
    return {"id": str(conv.id), "csat_score": conv.csat_score}


@router.patch("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def set_feedback(
    message_id: uuid.UUID,
    body: FeedbackUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise NotFoundError("Mensaje no encontrado")
    msg.feedback = body.feedback
    await db.commit()


@router.patch("/messages/{message_id}/annotate", status_code=status.HTTP_204_NO_CONTENT)
async def annotate_message(
    message_id: uuid.UUID,
    body: AnnotateRequest,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise NotFoundError("Mensaje no encontrado")
    msg.annotation = body.annotation
    msg.annotation_note = body.note
    await db.commit()


@router.put("/{conversation_id}/tags", response_model=dict)
async def set_conversation_tags(
    conversation_id: uuid.UUID,
    body: _TagsBody,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.CONVERSATIONS_UPDATE)),
):
    """Reemplaza completamente la lista de tags de una conversación."""
    result = await db.execute(select(ChatConversation).where(ChatConversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversación no encontrada")
    cleaned = sorted(set(t.strip().lower() for t in body.tags if t.strip()))
    conv.tags = cleaned
    await db.commit()
    return {"id": str(conv.id), "tags": conv.tags}
