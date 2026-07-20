from __future__ import annotations

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
    for key, val in updates.items():
        if val is not None and hasattr(cfg, key) and key != "api_key":
            setattr(cfg, key, val)
    await db.flush()
    return cfg


async def regenerate_api_key(db: AsyncSession) -> WidgetConfig:
    cfg = await get_or_create(db)
    cfg.api_key = "wk_" + secrets.token_hex(16)
    await db.flush()
    return cfg


def generate_embed_code(cfg: WidgetConfig) -> EmbedCodeOut:
    settings = get_settings()
    base = settings.WIDGET_BASE_URL
    show_icon_attr = "true" if cfg.show_bot_icon else "false"
    script_tag = (
        f'<script src="{base}/widget/widget.js" '
        f'data-api-url="{base}" '
        f'data-api-key="{cfg.api_key}" '
        f'data-position="{cfg.position}" '
        f'data-show-bot-icon="{show_icon_attr}" '
        f'defer></script>'
    )
    iframe_tag = (
        f'<iframe src="{base}/widget/embed?key={cfg.api_key}" '
        f'width="400" height="600" frameborder="0"></iframe>'
    )
    return EmbedCodeOut(script_tag=script_tag, iframe_tag=iframe_tag, api_key=cfg.api_key)


async def enforce_widget_caps(widget: WidgetConfig, session_id: str) -> None:
    """Apply per-widget abuse caps (max_chats_per_session / per_day).

    Both are independent of the global IP rate limit — they let the admin
    cap THIS widget's usage regardless of whether the limits in
    core.rate_limit kick in (límite de chats por sesión / por día).
    """
    if widget.max_chats_per_session and session_id:
        try:
            await check_rate_limit(
                f"widget:{widget.api_key}:session", session_id,
                max_requests=widget.max_chats_per_session,
                window_seconds=4 * 3600,
            )
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Has alcanzado el límite de mensajes para esta sesión.",
                headers={"Retry-After": str(exc.retry_after)},
            )
    if widget.max_chats_per_day:
        try:
            await check_rate_limit(
                f"widget:{widget.api_key}:day", "global",
                max_requests=widget.max_chats_per_day,
                window_seconds=24 * 3600,
            )
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="El chatbot ha alcanzado su límite diario de mensajes.",
                headers={"Retry-After": str(exc.retry_after)},
            )


async def handle_escalation_consent(
    db: AsyncSession, *, conversation_id, contact_type: str, contact_value: str,
) -> None:
    """Registra el consentimiento del usuario para ser contactado.

    Solo procede si la conversación tiene un escalamiento pendiente de
    confirmación (escalation_pending=True). Almacena el contacto, despacha
    la notificación al área responsable y limpia el flag pending.
    """
    from sqlalchemy import select as sa_select
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

        if not conv.escalation_pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No hay un escalamiento pendiente para esta conversación.",
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
        )

        conv.escalation_pending = False
        await db.commit()
    else:
        # Sin conversación activa — solicitud manual antes de iniciar chat
        await dispatch_escalation(
            db,
            conversation_id="",
            question="",
            reason="Solicitud de contacto manual",
            trigger_type="user_consent",
            extra={"contact_info": contact_info},
        )
