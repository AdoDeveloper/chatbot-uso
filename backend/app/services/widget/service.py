from __future__ import annotations

import hashlib
import secrets

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.models.widget_config import WidgetConfig
from app.schemas.widget import EmbedCodeOut


async def get_or_create(db: AsyncSession) -> WidgetConfig:
    result = await db.execute(select(WidgetConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = WidgetConfig()
        db.add(cfg)
        await db.flush()
    return cfg


async def get_by_api_key(db: AsyncSession, api_key: str) -> WidgetConfig | None:
    result = await db.execute(
        select(WidgetConfig).where(WidgetConfig.api_key == api_key)
    )
    return result.scalar_one_or_none()


async def update_config(db: AsyncSession, updates: dict) -> WidgetConfig:
    cfg = await get_or_create(db)
    columns = WidgetConfig.__table__.columns
    for key, val in updates.items():
        if key == "api_key" or key not in columns:
            continue
        # null vacía un campo opcional (sin límite, sin logo); en los obligatorios se ignora.
        if val is None and not columns[key].nullable:
            continue
        setattr(cfg, key, val)
    await db.flush()
    return cfg


async def regenerate_api_key(db: AsyncSession) -> WidgetConfig:
    cfg = await get_or_create(db)
    cfg.api_key = "wk_" + secrets.token_hex(16)
    await db.flush()
    return cfg


def generate_embed_code(cfg: WidgetConfig) -> EmbedCodeOut:
    """Posición e ícono no van como atributos data-*."""
    settings = get_settings()
    base = settings.WIDGET_BASE_URL
    script_tag = (
        f'<script src="{base}/widget/widget.js" '
        f'data-api-url="{base}" '
        f'data-api-key="{cfg.api_key}" '
        f'defer></script>'
    )
    return EmbedCodeOut(script_tag=script_tag, api_key=cfg.api_key)


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


async def enforce_widget_caps(widget: WidgetConfig, session_id: str) -> None:
    """Apply per-widget abuse caps (max_chats_per_session / per_day)."""
    if widget.max_chats_per_session:
        if not session_id:
            # El límite es por sesión individual; sin session_id no hay identificador que limitar.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_id es requerido para este widget.",
            )
        try:
            await check_rate_limit(
                f"widget:{_key_fingerprint(widget.api_key)}:session", session_id,
                max_requests=widget.max_chats_per_session,
                window_seconds=4 * 3600,
            )
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Ha alcanzado el límite de mensajes de esta conversación. Finalice el chat e inicie uno nuevo para continuar.",
                headers={"Retry-After": str(exc.retry_after)},
            )
    if widget.max_chats_per_day:
        try:
            await check_rate_limit(
                f"widget:{_key_fingerprint(widget.api_key)}:day", "global",
                max_requests=widget.max_chats_per_day,
                window_seconds=24 * 3600,
            )
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="El asistente alcanzó el límite de consultas de hoy. Por favor, inténtelo de nuevo mañana.",
                headers={"Retry-After": str(exc.retry_after)},
            )


async def handle_escalation_consent(
    db: AsyncSession, *, conversation_id, contact_type: str, contact_value: str,
) -> None:
    """Registra el consentimiento del usuario para ser contactado."""
    from sqlalchemy import select as sa_select

    from app.core.constants import PANEL_AUTHENTICATED_BROWSERS
    from app.models.chat_conversation import ChatConversation
    from app.models.chat_message import ChatMessage
    from app.models.enums import MessageRole
    from app.services.escalation.service import dispatch_escalation

    contact_info = {"type": contact_type, "value": contact_value}

    if conversation_id:
        conv = await db.get(ChatConversation, conversation_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversación no encontrada.",
            )

        # Obtener el último mensaje del usuario para incluirlo en la notificación
        last_q_result = await db.execute(
            sa_select(ChatMessage.content)
            .where(ChatMessage.conversation_id == conv.id)
            .where(ChatMessage.role == MessageRole.user)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_question = last_q_result.scalar() or ""
        reason = conv.escalation_trigger_reason or "Solicitud de contacto del usuario"
        conv_id_str = str(conv.id)

        await dispatch_escalation(
            db,
            conversation_id=conv_id_str,
            question=last_question,
            reason=reason,
            trigger_type="user_consent",
            extra={"contact_info": contact_info},
            is_test=(conv.browser or "") in PANEL_AUTHENTICATED_BROWSERS,
        )

        if conv.escalation_pending:
            conv.escalation_pending = False
        await db.commit()
    else:
        # Sin conversación activa - solicitud manual antes de iniciar chat
        await dispatch_escalation(
            db,
            conversation_id="",
            question="",
            reason="Solicitud de contacto manual",
            trigger_type="user_consent",
            extra={"contact_info": contact_info},
        )
