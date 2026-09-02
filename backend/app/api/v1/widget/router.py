from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field, field_validator

from app.core.deps import get_client_ip, require_perm
from app.core.permissions import P
from app.core.widget_auth import require_widget_key, verify_widget_access
from app.db.session import get_db
from app.models.enums import MessageFeedback
from app.models.widget_config import WidgetConfig
from app.schemas.widget import (
    EmbedCodeOut,
    WidgetConfigOut,
    WidgetConfigUpdate,
    WidgetPublicConfigOut,
)
from app.services.widget import service as svc
from app.services.widget import csat_reasons as csat_reasons_svc
from app.services.escalation import lifecycle as lifecycle_svc

log = structlog.get_logger()

_MAX_CSAT_REASONS = 20  # cota defensiva de payload; la lista real es la que administra el admin


class _PublicCsatBody(BaseModel):
    conversation_id: uuid.UUID
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=500)
    reasons: list[str] = Field(default_factory=list, max_length=_MAX_CSAT_REASONS)

    @field_validator("reasons")
    @classmethod
    def _dedupe_reasons(cls, v: list[str]) -> list[str]:
        # sin duplicados, preservando el primer orden de aparición
        seen: set[str] = set()
        out = []
        for r in v:
            if r not in seen:
                seen.add(r)
                out.append(r)
        return out


class _PublicEscalationContactBody(BaseModel):
    conversation_id: uuid.UUID | None = None
    contact_type: str = Field(..., pattern="^(email|whatsapp)$")
    contact_value: str = Field(..., min_length=1, max_length=200)


class _PublicFeedbackBody(BaseModel):
    feedback: MessageFeedback
    conversation_id: uuid.UUID


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


class CsatReasonOut(BaseModel):
    id: str
    label: str
    enabled: bool = True


class CsatReasonCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True


class CsatReasonUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=120)
    enabled: bool | None = None


class CsatReasonReorder(BaseModel):
    ordered_ids: list[str]


@router.get("/csat-reasons", response_model=list[CsatReasonOut])
async def list_csat_reasons(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_reader),
):
    return await csat_reasons_svc.list_reasons(db)


@router.post("/csat-reasons", response_model=CsatReasonOut, status_code=201)
async def create_csat_reason(
    body: CsatReasonCreate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    return await csat_reasons_svc.create_reason(db, label=body.label, enabled=body.enabled)


@router.patch("/csat-reasons/{reason_id}", response_model=CsatReasonOut)
async def update_csat_reason(
    reason_id: str,
    body: CsatReasonUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    return await csat_reasons_svc.update_reason(
        db, reason_id=reason_id, changes=body.model_dump(exclude_unset=True)
    )


@router.delete("/csat-reasons/{reason_id}", status_code=204)
async def delete_csat_reason(
    reason_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    await csat_reasons_svc.delete_reason(db, reason_id=reason_id)


@router.put("/csat-reasons/reorder", response_model=list[CsatReasonOut])
async def reorder_csat_reasons(
    body: CsatReasonReorder,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(_admin),
):
    return await csat_reasons_svc.reorder_reasons(db, ordered_ids=body.ordered_ids)


@router.get("/public/config", response_model=WidgetPublicConfigOut)
async def public_config(
    response: Response,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(require_widget_key),
):
    response.headers["Cache-Control"] = "no-store"
    from app.services.monitoring.versions import get_published_widget_config
    from app.services.system.settings import get_runtime_overrides
    published = await get_published_widget_config(db)
    source = published if published else widget  # sin deploy previo: usa la config en vivo

    out = WidgetPublicConfigOut.model_validate(source, from_attributes=True)
    enabled = await csat_reasons_svc.list_reasons(db, only_enabled=True)
    out.csat_reasons = {str(r["id"]): r["label"] for r in enabled}
    overrides = await get_runtime_overrides(db)
    out.max_input_chars = overrides["max_input_chars"]
    return out


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
    chat_req.browser = None
    chat_req.source_scope = None
    await svc.enforce_widget_caps(widget, chat_req.session_id or "")
    client_ip = get_client_ip(request)
    origin_url = request.headers.get("Referer") or request.headers.get("Origin")

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
    body: _PublicFeedbackBody,
    db: AsyncSession = Depends(get_db),
    widget: WidgetConfig = Depends(verify_widget_access),
):
    from app.models.chat_message import ChatMessage
    msg = await db.get(ChatMessage, message_id)
    if msg and msg.conversation_id != body.conversation_id:
        msg = None
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
    if not widget.enable_escalation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Escalamiento a un humano no habilitado para este widget.",
        )
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
    """Envía una calificación CSAT desde el widget (sin auth de usuario, solo widget key)."""
    if not widget.enable_csat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSAT no habilitado para este widget.",
        )
    if body.reasons:
        valid = await csat_reasons_svc.valid_ids(db)
        unknown = [r for r in body.reasons if r not in valid]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Motivos desconocidos o deshabilitados: {', '.join(unknown)}",
            )
    await lifecycle_svc.record_csat(
        db, conversation_id=body.conversation_id, score=body.score,
        comment=body.comment, reasons=body.reasons, actor_user_id=None,
    )
