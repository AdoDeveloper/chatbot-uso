"""Tests para collect_digest_stats (resumen del evento unanswered_digest)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, UnansweredStatus
from app.models.unanswered_question import UnansweredQuestion
from app.services.notifications.digest import collect_digest_stats


def _make_question(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        question="¿Cuándo inician las clases?",
        status=UnansweredStatus.open,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return UnansweredQuestion(**defaults)


def _make_conversation(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        session_id=str(uuid.uuid4()),
        status=ConversationStatus.active,
    )
    defaults.update(overrides)
    return ChatConversation(**defaults)


class TestCollectDigestStats:
    async def test_empty_db_returns_zeroes(self, db_session):
        stats = await collect_digest_stats(db_session)

        assert stats["total_open"] == 0
        assert stats["new_open"] == 0
        assert stats["resolved_today"] == 0
        assert stats["top_topics"] == []
        assert stats["recent_questions"] == []
        assert stats["escalated_today"] == 0
        assert stats["conversations_resolved_today"] == 0
        assert "date" in stats

    async def test_counts_open_and_new_questions(self, db_session):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)

        db_session.add_all([
            _make_question(created_at=now),
            _make_question(created_at=old),
            _make_question(status=UnansweredStatus.resolved, resolved_at=now, created_at=old),
        ])
        await db_session.commit()

        stats = await collect_digest_stats(db_session)

        assert stats["total_open"] == 2
        assert stats["new_open"] == 1
        assert stats["resolved_today"] == 1

    async def test_top_topics_orders_by_frequency(self, db_session):
        db_session.add_all([
            _make_question(detected_topic="becas"),
            _make_question(detected_topic="becas"),
            _make_question(detected_topic="matricula"),
            _make_question(detected_topic=None),
            _make_question(detected_topic=""),
        ])
        await db_session.commit()

        stats = await collect_digest_stats(db_session)

        assert stats["top_topics"][0] == ("becas", 2)
        assert ("matricula", 1) in stats["top_topics"]
        assert len(stats["top_topics"]) == 2

    async def test_recent_questions_limited_and_ordered(self, db_session):
        now = datetime.now(timezone.utc)
        for i in range(7):
            db_session.add(_make_question(
                question=f"Pregunta {i}",
                created_at=now - timedelta(minutes=i),
            ))
        await db_session.commit()

        stats = await collect_digest_stats(db_session)

        assert len(stats["recent_questions"]) == 5
        assert stats["recent_questions"][0] == "Pregunta 0"

    async def test_conversation_metrics(self, db_session):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)

        db_session.add_all([
            _make_conversation(escalated_at=now),
            _make_conversation(escalated_at=old),
            _make_conversation(status=ConversationStatus.resolved, resolved_at=now),
            _make_conversation(status=ConversationStatus.active, resolved_at=now),
        ])
        await db_session.commit()

        stats = await collect_digest_stats(db_session)

        assert stats["escalated_today"] == 1
        assert stats["conversations_resolved_today"] == 1
