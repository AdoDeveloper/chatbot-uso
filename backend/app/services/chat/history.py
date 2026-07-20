from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import or_

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageRole

from app.core.constants import PLAYGROUND_BROWSERS

log = structlog.get_logger()


def _conv_lock_key(session_id: str) -> str:
    return f"conv_lock:{hashlib.sha256(session_id.encode()).hexdigest()[:16]}"


async def acquire_session_lock(session_id: str, *, timeout: float = 5.0) -> bool:
    """Serializa la persistencia de turnos concurrentes con el mismo session_id
    para evitar conversaciones duplicadas. Fail-open si Redis no está."""
    import asyncio
    from app.core.redis import get_redis
    try:
        redis = get_redis()
        key = _conv_lock_key(session_id)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await redis.set(key, "1", nx=True, ex=15):
                return True
            await asyncio.sleep(0.05)
        return False
    except Exception:
        return False


async def release_session_lock(session_id: str) -> None:
    from app.core.redis import get_redis
    try:
        await get_redis().delete(_conv_lock_key(session_id))
    except Exception:
        pass


_REOPEN_WINDOW_HOURS = 2  # ventana para reabrir una conversación auto-resuelta por inactividad


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: uuid.UUID | None = None,
    device: str | None = None,
    browser: str | None = None,
    origin_url: str | None = None,
) -> ChatConversation:
    async def _find() -> ChatConversation | None:
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.session_id == session_id)
            .where(ChatConversation.status == ConversationStatus.active)
            .order_by(ChatConversation.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_reopenable() -> ChatConversation | None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_REOPEN_WINDOW_HOURS)
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.session_id == session_id)
            .where(ChatConversation.status == ConversationStatus.resolved)
            .where(ChatConversation.resolved_by_user_id.is_(None))
            .where(ChatConversation.last_message_at >= cutoff)
            .order_by(ChatConversation.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    conv = await _find()
    if conv:
        return conv

    acquired = await acquire_session_lock(session_id)
    try:
        if acquired:
            await db.rollback()
            conv = await _find()
            if conv:
                return conv

        reopened = await _find_reopenable()
        if reopened:
            reopened.status = ConversationStatus.active
            reopened.resolved_at = None
            if acquired:
                await db.commit()
                await db.refresh(reopened)
            else:
                await db.flush()
            return reopened

        conv = ChatConversation(
            session_id=session_id,
            user_id=user_id,
            device=device,
            browser=browser,
            origin_url=origin_url,
            status=ConversationStatus.active,
        )
        db.add(conv)
        if acquired:
            await db.commit()
            await db.refresh(conv)
        else:
            await db.flush()
        return conv
    finally:
        if acquired:
            await release_session_lock(session_id)


async def add_message(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    sources: list[dict] | None = None,
    latency_ms: int | None = None,
    rag_route: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources_json=sources or [],
        latency_ms=latency_ms,
        rag_route=rag_route,
    )
    db.add(msg)

    await db.execute(
        ChatConversation.__table__.update()
        .where(ChatConversation.id == conversation_id)
        .values(last_message_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return msg


async def list_conversations(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_filter: ConversationStatus | None = None,
    tag: str | None = None,
    source: str = "production",
) -> tuple[list[ChatConversation], int]:
    offset = (page - 1) * page_size

    base = select(ChatConversation)
    count_base = select(func.count(ChatConversation.id))

    if source == "production":
        prod_filter = or_(
            ChatConversation.browser.is_(None),
            ChatConversation.browser.notin_(PLAYGROUND_BROWSERS),
        )
        base = base.where(prod_filter)
        count_base = count_base.where(prod_filter)
    elif source == "playground":
        playground_filter = ChatConversation.browser.in_(PLAYGROUND_BROWSERS)
        base = base.where(playground_filter)
        count_base = count_base.where(playground_filter)

    if status_filter is not None:
        base = base.where(ChatConversation.status == status_filter)
        count_base = count_base.where(ChatConversation.status == status_filter)

    # Text search: find conversations containing matching messages
    if search and search.strip():
        from sqlalchemy import exists
        term = f"%{search.strip()}%"
        msg_filter = exists(
            select(ChatMessage.id)
            .where(ChatMessage.conversation_id == ChatConversation.id)
            .where(ChatMessage.content.ilike(term))
        )
        base = base.where(msg_filter)
        count_base = count_base.where(msg_filter)

    if date_from:
        base = base.where(ChatConversation.started_at >= date_from)
        count_base = count_base.where(ChatConversation.started_at >= date_from)
    if date_to:
        base = base.where(ChatConversation.started_at <= date_to)
        count_base = count_base.where(ChatConversation.started_at <= date_to)

    if tag and tag.strip():
        t = tag.strip().lower()
        # MySQL JSON: json_contains(tags, json_quote(value))
        base = base.where(func.json_contains(ChatConversation.tags, func.json_quote(t)))
        count_base = count_base.where(func.json_contains(ChatConversation.tags, func.json_quote(t)))

    total_result = await db.execute(count_base)
    total = total_result.scalar_one()

    result = await db.execute(
        base.order_by(ChatConversation.last_message_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = list(result.scalars().all())
    return rows, total


async def fetch_first_user_messages(
    db: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Return the first user message content for each conversation (for list previews)."""
    if not conversation_ids:
        return {}
    min_q = (
        select(
            ChatMessage.conversation_id,
            func.min(ChatMessage.created_at).label("first_at"),
        )
        .where(ChatMessage.conversation_id.in_(conversation_ids))
        .where(ChatMessage.role == MessageRole.user)
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    stmt = select(ChatMessage.conversation_id, ChatMessage.content).join(
        min_q,
        (ChatMessage.conversation_id == min_q.c.conversation_id)
        & (ChatMessage.created_at == min_q.c.first_at),
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def get_conversation(
    db: AsyncSession, conversation_id: uuid.UUID
) -> ChatConversation | None:
    result = await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def auto_resolve_stale_conversations(
    db: AsyncSession, *, inactive_minutes: int
) -> int:
    """Marca como `resolved` las conversaciones `active` sin actividad reciente."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=inactive_minutes)
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.status == ConversationStatus.active,
            ChatConversation.last_message_at < cutoff,
        )
    )
    stale = list(result.scalars().all())
    for conv in stale:
        conv.status = ConversationStatus.resolved
        conv.resolved_by_user_id = None
    if stale:
        await db.commit()
    return len(stale)


