"""Tests unitarios directos para app/services/chat/history.py.

Usan db_session (MySQL real vía fixture) para sembrar datos y llaman las
funciones del servicio directamente, verificando el estado resultante en BD.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageRole
from app.services.chat import history

pytestmark = pytest.mark.asyncio


async def _make_conversation(
    db_session,
    *,
    session_id: str | None = None,
    status: ConversationStatus = ConversationStatus.active,
    browser: str | None = None,
    last_message_at: datetime | None = None,
    resolved_by_user_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
) -> ChatConversation:
    conv = ChatConversation(
        session_id=session_id or f"sess-{uuid.uuid4().hex[:8]}",
        status=status,
        browser=browser,
        resolved_by_user_id=resolved_by_user_id,
    )
    if last_message_at is not None:
        conv.last_message_at = last_message_at
    if started_at is not None:
        conv.started_at = started_at
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _make_message(
    db_session,
    conversation_id: uuid.UUID,
    *,
    role: MessageRole = MessageRole.user,
    content: str = "hola",
) -> ChatMessage:
    msg = ChatMessage(conversation_id=conversation_id, role=role, content=content)
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


# --- get_or_create_conversation ---------------------------------------


async def test_get_or_create_conversation_creates_new(db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    conv = await history.get_or_create_conversation(db_session, session_id=session_id)

    assert conv.id is not None
    assert conv.session_id == session_id
    assert conv.status == ConversationStatus.active

    row = (
        await db_session.execute(
            select(ChatConversation).where(ChatConversation.id == conv.id)
        )
    ).scalar_one()
    assert row.session_id == session_id


async def test_get_or_create_conversation_returns_existing_active(db_session):
    existing = await _make_conversation(db_session, status=ConversationStatus.active)

    conv = await history.get_or_create_conversation(
        db_session, session_id=existing.session_id
    )

    assert conv.id == existing.id

    count = (
        await db_session.execute(
            select(ChatConversation).where(
                ChatConversation.session_id == existing.session_id
            )
        )
    ).scalars().all()
    assert len(count) == 1


async def test_get_or_create_conversation_reopens_within_window(db_session):
    recent = datetime.now(timezone.utc) - timedelta(minutes=30)
    resolved = await _make_conversation(
        db_session,
        status=ConversationStatus.resolved,
        last_message_at=recent,
        resolved_by_user_id=None,
    )

    conv = await history.get_or_create_conversation(
        db_session, session_id=resolved.session_id
    )

    assert conv.id == resolved.id
    assert conv.status == ConversationStatus.active
    assert conv.resolved_at is None

    row = (
        await db_session.execute(
            select(ChatConversation).where(ChatConversation.id == resolved.id)
        )
    ).scalar_one()
    assert row.status == ConversationStatus.active


async def test_get_or_create_conversation_does_not_reopen_outside_window(db_session):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    resolved = await _make_conversation(
        db_session,
        status=ConversationStatus.resolved,
        last_message_at=old,
        resolved_by_user_id=None,
    )

    conv = await history.get_or_create_conversation(
        db_session, session_id=resolved.session_id
    )

    assert conv.id != resolved.id
    assert conv.status == ConversationStatus.active

    rows = (
        await db_session.execute(
            select(ChatConversation).where(
                ChatConversation.session_id == resolved.session_id
            )
        )
    ).scalars().all()
    assert len(rows) == 2


async def test_get_or_create_conversation_does_not_reopen_manually_resolved(db_session, make_user):
    """resolved_by_user_id no-NULL significa cierre manual de un agente: no debe reabrirse."""
    agent = await make_user()
    recent = datetime.now(timezone.utc) - timedelta(minutes=10)
    resolved = await _make_conversation(
        db_session,
        status=ConversationStatus.resolved,
        last_message_at=recent,
        resolved_by_user_id=agent.id,
    )

    conv = await history.get_or_create_conversation(
        db_session, session_id=resolved.session_id
    )

    assert conv.id != resolved.id
    assert conv.status == ConversationStatus.active


# --- add_message ---------------------------------------------------------


async def test_add_message_persists_and_updates_last_message_at(db_session):
    conv = await _make_conversation(
        db_session, last_message_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    old_last_message_at = conv.last_message_at

    msg = await history.add_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.user,
        content="Hola, necesito ayuda",
    )

    assert msg.id is not None
    assert msg.content == "Hola, necesito ayuda"
    assert msg.sources_json == []

    row = (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.id == msg.id)
        )
    ).scalar_one()
    assert row.content == "Hola, necesito ayuda"

    # add_message actualiza last_message_at con un UPDATE de Core (no ORM), así
    # que el objeto `conv` ya cargado en el identity map de la sesión no se
    # entera solo — hay que refrescarlo explícitamente antes de comparar.
    await db_session.refresh(conv)
    assert conv.last_message_at > old_last_message_at


async def test_add_message_with_sources_and_latency(db_session):
    conv = await _make_conversation(db_session)

    sources = [{"title": "Manual", "url": "http://example.com/doc"}]
    msg = await history.add_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="Respuesta con fuentes",
        sources=sources,
        latency_ms=1234,
        rag_route="faq",
    )

    row = (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.id == msg.id)
        )
    ).scalar_one()
    assert row.sources_json == sources
    assert row.latency_ms == 1234
    assert row.rag_route == "faq"
    assert row.role == MessageRole.assistant


# --- list_conversations ---------------------------------------------------


async def test_list_conversations_pagination_and_total(db_session):
    for _ in range(3):
        await _make_conversation(db_session)

    rows, total = await history.list_conversations(db_session, page=1, page_size=2)

    assert total == 3
    assert len(rows) == 2


async def test_list_conversations_filters_production_source(db_session):
    prod = await _make_conversation(db_session, browser="chrome")
    playground = await _make_conversation(db_session, browser="playground")

    rows, total = await history.list_conversations(db_session, source="production")

    ids = {r.id for r in rows}
    assert prod.id in ids
    assert playground.id not in ids
    assert total == 1


async def test_list_conversations_filters_playground_source(db_session):
    prod = await _make_conversation(db_session, browser="chrome")
    playground = await _make_conversation(db_session, browser="admin")

    rows, total = await history.list_conversations(db_session, source="playground")

    ids = {r.id for r in rows}
    assert playground.id in ids
    assert prod.id not in ids
    assert total == 1


async def test_list_conversations_filters_by_status(db_session, make_user):
    agent = await make_user()
    active = await _make_conversation(db_session, status=ConversationStatus.active)
    resolved = await _make_conversation(
        db_session,
        status=ConversationStatus.resolved,
        resolved_by_user_id=agent.id,
    )

    rows, total = await history.list_conversations(
        db_session, status_filter=ConversationStatus.resolved
    )

    ids = {r.id for r in rows}
    assert resolved.id in ids
    assert active.id not in ids
    assert total == 1


async def test_list_conversations_search_matches_message_content(db_session):
    conv_match = await _make_conversation(db_session)
    conv_nomatch = await _make_conversation(db_session)
    await _make_message(db_session, conv_match.id, content="necesito el reglamento de becas")
    await _make_message(db_session, conv_nomatch.id, content="hola buenas tardes")

    rows, total = await history.list_conversations(db_session, search="reglamento")

    ids = {r.id for r in rows}
    assert conv_match.id in ids
    assert conv_nomatch.id not in ids
    assert total == 1


async def test_list_conversations_search_blank_is_noop(db_session):
    await _make_conversation(db_session)
    await _make_conversation(db_session)

    rows, total = await history.list_conversations(db_session, search="   ")

    assert total == 2


async def test_list_conversations_date_range_filter(db_session):
    now = datetime.now(timezone.utc)
    old = await _make_conversation(db_session, started_at=now - timedelta(days=10))
    recent = await _make_conversation(db_session, started_at=now - timedelta(hours=1))

    rows, total = await history.list_conversations(
        db_session, date_from=now - timedelta(days=1), date_to=now + timedelta(hours=1)
    )

    ids = {r.id for r in rows}
    assert recent.id in ids
    assert old.id not in ids
    assert total == 1


async def test_list_conversations_tag_filter(db_session):
    tagged = await _make_conversation(db_session)
    tagged.tags = ["urgente"]
    untagged = await _make_conversation(db_session)
    db_session.add(tagged)
    await db_session.commit()

    rows, total = await history.list_conversations(db_session, tag="urgente")

    ids = {r.id for r in rows}
    assert tagged.id in ids
    assert untagged.id not in ids
    assert total == 1


async def test_list_conversations_ordered_by_last_message_desc(db_session):
    older = await _make_conversation(
        db_session, last_message_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    newer = await _make_conversation(
        db_session, last_message_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    rows, total = await history.list_conversations(db_session)

    assert total == 2
    assert rows[0].id == newer.id
    assert rows[1].id == older.id


# --- fetch_first_user_messages -------------------------------------------


async def test_fetch_first_user_messages_returns_earliest_per_conversation(db_session):
    conv = await _make_conversation(db_session)
    first = await _make_message(db_session, conv.id, role=MessageRole.user, content="primer mensaje")
    await _make_message(db_session, conv.id, role=MessageRole.assistant, content="respuesta bot")
    await _make_message(db_session, conv.id, role=MessageRole.user, content="segundo mensaje usuario")

    result = await history.fetch_first_user_messages(db_session, [conv.id])

    assert result[conv.id] == "primer mensaje"


async def test_fetch_first_user_messages_empty_ids_returns_empty_dict(db_session):
    result = await history.fetch_first_user_messages(db_session, [])
    assert result == {}


async def test_fetch_first_user_messages_no_user_messages(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(db_session, conv.id, role=MessageRole.assistant, content="solo bot")

    result = await history.fetch_first_user_messages(db_session, [conv.id])

    assert conv.id not in result


# --- get_conversation -----------------------------------------------------


async def test_get_conversation_found(db_session):
    conv = await _make_conversation(db_session)

    result = await history.get_conversation(db_session, conv.id)

    assert result is not None
    assert result.id == conv.id


async def test_get_conversation_not_found(db_session):
    result = await history.get_conversation(db_session, uuid.uuid4())
    assert result is None


# --- auto_resolve_stale_conversations --------------------------------------


async def test_auto_resolve_stale_conversations_resolves_inactive(db_session):
    stale = await _make_conversation(
        db_session,
        status=ConversationStatus.active,
        last_message_at=datetime.now(timezone.utc) - timedelta(minutes=60),
    )
    active_recent = await _make_conversation(
        db_session,
        status=ConversationStatus.active,
        last_message_at=datetime.now(timezone.utc),
    )

    count = await history.auto_resolve_stale_conversations(db_session, inactive_minutes=30)

    assert count == 1

    stale_row = (
        await db_session.execute(
            select(ChatConversation).where(ChatConversation.id == stale.id)
        )
    ).scalar_one()
    assert stale_row.status == ConversationStatus.resolved
    assert stale_row.resolved_by_user_id is None

    active_row = (
        await db_session.execute(
            select(ChatConversation).where(ChatConversation.id == active_recent.id)
        )
    ).scalar_one()
    assert active_row.status == ConversationStatus.active


async def test_auto_resolve_stale_conversations_no_stale_returns_zero(db_session):
    await _make_conversation(
        db_session,
        status=ConversationStatus.active,
        last_message_at=datetime.now(timezone.utc),
    )

    count = await history.auto_resolve_stale_conversations(db_session, inactive_minutes=30)

    assert count == 0


async def test_auto_resolve_stale_conversations_ignores_non_active(db_session, make_user):
    agent = await make_user()
    resolved = await _make_conversation(
        db_session,
        status=ConversationStatus.resolved,
        last_message_at=datetime.now(timezone.utc) - timedelta(hours=5),
        resolved_by_user_id=agent.id,
    )

    count = await history.auto_resolve_stale_conversations(db_session, inactive_minutes=30)

    assert count == 0

    row = (
        await db_session.execute(
            select(ChatConversation).where(ChatConversation.id == resolved.id)
        )
    ).scalar_one()
    assert row.status == ConversationStatus.resolved


# --- lock helpers (fail-open when Redis unavailable / basic behavior) ------


async def test_acquire_and_release_session_lock_roundtrip(monkeypatch):
    # acquire/release_session_lock hacen `from app.core.redis import get_redis`
    # dentro de la propia función (import perezoso), así que hay que parchear
    # el binding en su módulo origen — la fixture `client` no aplica aquí
    # porque este test no pasa por el override de FastAPI.
    import fakeredis.aioredis
    import app.core.redis as redis_mod
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)

    session_id = f"lock-{uuid.uuid4().hex[:8]}"
    acquired = await history.acquire_session_lock(session_id, timeout=1.0)
    assert acquired is True
    await history.release_session_lock(session_id)
    await fake.aclose()


async def test_acquire_session_lock_fails_open_on_redis_error(monkeypatch):
    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(history, "get_redis", _boom, raising=False)
    import app.core.redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis", _boom)

    result = await history.acquire_session_lock(f"lock-{uuid.uuid4().hex[:8]}", timeout=0.5)
    assert result is False


async def test_release_session_lock_swallows_redis_error(monkeypatch):
    def _boom():
        raise RuntimeError("redis down")

    import app.core.redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis", _boom)

    # Should not raise.
    await history.release_session_lock(f"lock-{uuid.uuid4().hex[:8]}")
