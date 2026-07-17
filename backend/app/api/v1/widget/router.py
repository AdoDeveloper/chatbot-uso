from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.core.deps import get_client_ip, require_perm
from app.core.permissions import P
from app.core.widget_auth import require_widget_key, verify_widget_access
from app.db.session import get_db
from app.models.widget_config import WidgetConfig
from app.schemas.chat_history import FeedbackUpdate
from app.schemas.widget import (
    EmbedCodeOut,
    WidgetConfigOut,
    WidgetConfigUpdate,
    WidgetPublicConfigOut,
)
from app.services.widget import service as svc
from app.services.escalation import lifecycle as lifecycle_svc

log = structlog.get_logger()


class _PublicCsatBody(BaseModel):
    conversation_id: uuid.UUID
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=500)


class _PublicEscalationContactBody(BaseModel):
    conversation_id: uuid.UUID | None = None
    contact_type: str = Field(..., pattern="^(email|whatsapp)$")
    contact_value: str = Field(..., min_length=1, max_length=200)


router = APIRouter(prefix="/widget", tags=["widget"])

_reader = require_perm(P.BOT_SETTINGS_READ)
_admin  = require_perm(P.BOT_SETTINGS_UPDATE)


@router.get("/config", response_model=WidgetConfigOut)
async def get_config(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_reader),
):
    cfg = await svc.get_or_create(db)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.put("/config", response_model=WidgetConfigOut)
async def update_config(
    body: WidgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    cfg = await svc.update_config(db, body.model_dump(exclude_unset=True))
    await db.commit()
    # Refresh to ensure server-side `onupdate=func.now()` columns (updated_at)
    # are loaded into the instance before Pydantic serializes it. Without this,
    # accessing the expired attribute during response validation triggers a
    # lazy DB hit in an already-closing async context, which fails with
    # MissingGreenlet/DetachedInstanceError.
    await db.refresh(cfg)
    return cfg


@router.get("/embed-code", response_model=EmbedCodeOut)
async def embed_code(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    cfg = await svc.get_or_create(db)
    await db.commit()
    return svc.generate_embed_code(cfg)


@router.post("/regenerate-key", response_model=WidgetConfigOut)
async def regenerate_key(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    cfg = await svc.regenerate_api_key(db)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.get("/public/config", response_model=WidgetPublicConfigOut)
async def public_config(
    response: Response,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(require_widget_key),
):
    # Sin esto, el navegador puede cachear heurísticamente esta respuesta y
    # seguir sirviendo apariencia/config vieja al widget embebido después de
    # publicar cambios, ya que es un GET simple sin encabezados de caché.
    response.headers["Cache-Control"] = "no-store"
    from app.services.monitoring.versions import get_published_widget_config
    published = await get_published_widget_config(db)
    if published:
        return published
    # Fallback: sistema sin ningún deploy previo — usa la config en vivo
    return widget


@router.post("/public/chat", response_model=None)
async def public_chat(
    request: Request,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(verify_widget_access),
):
    from app.api.v1.chat.router import (
        ChatRequest,
        run_chat,
        _llm_semaphore,
        _LLM_QUEUE_TIMEOUT,
    )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")
    from pydantic import ValidationError
    try:
        chat_req = ChatRequest(**body)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        field = " → ".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg", "Datos inválidos")
        raise HTTPException(status_code=422, detail=f"{field}: {msg}" if field else msg)
    # Force production mode regardless of what the client sends.
    # browser/source_scope are admin-only fields; a malicious user could send
    # {"browser": "playground"} to bypass the aprobada filter and access
    # draft configs or unapproved documents.
    chat_req.browser = None
    chat_req.source_scope = None
    # Enforce per-widget caps before even running the pipeline — fail fast
    # so the abusive client gets a 429, not a half-processed response.
    await svc.enforce_widget_caps(widget, chat_req.session_id or "")
    client_ip = get_client_ip(request)
    origin_url = request.headers.get("Referer") or request.headers.get("Origin")

    # Adquirir el semáforo de concurrencia LLM (misma precondición que el
    # endpoint admin chat()). run_chat lo libera en su finally, así que
    # SIEMPRE debe adquirirse aquí antes de invocarlo; de lo contrario el
    # contador crece sin límite y la protección de cuota del proveedor deja
    # de funcionar en el chat público del widget.
    try:
        await asyncio.wait_for(_llm_semaphore.acquire(), timeout=_LLM_QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("widget.chat.llm_queue_timeout", session_id=chat_req.session_id)
        raise HTTPException(
            status_code=503,
            detail="El asistente está muy solicitado en este momento. Inténtalo de nuevo en unos segundos.",
        )

    return await run_chat(chat_req, db, client_ip, origin_url)


@router.patch("/public/messages/{message_id}/feedback", status_code=204)
async def public_feedback(
    message_id: uuid.UUID,
    body: FeedbackUpdate,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(verify_widget_access),
):
    from app.models.chat_message import ChatMessage

    msg = await db.get(ChatMessage, message_id)
    if msg:
        msg.feedback = body.feedback
        await db.commit()


@router.post("/public/escalation/contact", status_code=204)
async def public_escalation_contact(
    body: _PublicEscalationContactBody,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(verify_widget_access),
):
    """Registra el consentimiento del usuario para ser contactado."""
    await svc.handle_escalation_consent(
        db,
        conversation_id=body.conversation_id,
        contact_type=body.contact_type,
        contact_value=body.contact_value,
    )


@router.post("/public/csat", status_code=204)
async def public_csat(
    body: _PublicCsatBody,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(verify_widget_access),
):
    """Submit a CSAT rating from the widget (no user auth required, only widget key)."""
    if not widget.enable_csat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSAT no habilitado para este widget.",
        )
    await lifecycle_svc.record_csat(
        db, conversation_id=body.conversation_id, score=body.score,
        comment=body.comment, actor_user_id=None,
    )
