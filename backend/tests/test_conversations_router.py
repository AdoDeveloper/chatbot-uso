"""Tests para app/api/v1/conversations/router.py.

Cubre lo que no tenía ningún test: get_conversation, update status, CSAT,
feedback/annotate de mensajes, tags, y bulk_action (optimizado hoy de N
SELECTs a un solo IN() — este archivo fija el contrato para que una futura
regresión de performance o de lógica no pase desapercibida).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageFeedback, MessageRole, UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _make_conversation(db_session, *, status=ConversationStatus.active) -> ChatConversation:
    conv = ChatConversation(
        id=uuid.uuid4(), session_id=f"sess-{uuid.uuid4().hex[:8]}", status=status,
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _make_message(db_session, conv: ChatConversation, *, role=MessageRole.assistant) -> ChatMessage:
    msg = ChatMessage(
        id=uuid.uuid4(), conversation_id=conv.id, role=role, content="hola",
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


class TestGetConversation:
    async def test_requires_auth(self, client):
        r = await client.get(f"/api/v1/conversations/{uuid.uuid4()}")
        assert r.status_code == 401

    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.get(f"/api/v1/conversations/{uuid.uuid4()}", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_returns_conversation_with_message_count(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)
        await _make_message(db_session, conv)
        await _make_message(db_session, conv, role=MessageRole.user)

        r = await client.get(f"/api/v1/conversations/{conv.id}", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(conv.id)
        assert body["message_count"] == 2
        assert len(body["messages"]) == 2


class TestUpdateConversationStatus:
    async def test_requires_perm(self, client, viewer_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)
        r = await client.patch(
            f"/api/v1/conversations/{conv.id}/status",
            json={"status": "resolved"},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            f"/api/v1/conversations/{uuid.uuid4()}/status",
            json={"status": "resolved"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_resolving_sets_resolved_at_and_user(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)

        r = await client.patch(
            f"/api/v1/conversations/{conv.id}/status",
            json={"status": "resolved"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"

        await db_session.refresh(conv)
        assert conv.resolved_at is not None
        assert conv.resolved_by_user_id == admin_user.id


class TestRecordCsat:
    async def test_requires_auth(self, client):
        r = await client.post(f"/api/v1/conversations/{uuid.uuid4()}/csat", json={"score": 5})
        assert r.status_code == 401

    async def test_records_score(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)
        r = await client.post(
            f"/api/v1/conversations/{conv.id}/csat",
            json={"score": 4},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["csat_score"] == 4


class TestMessageFeedback:
    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            f"/api/v1/conversations/messages/{uuid.uuid4()}/feedback",
            json={"feedback": "positive"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_sets_feedback(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)
        msg = await _make_message(db_session, conv)

        r = await client.patch(
            f"/api/v1/conversations/messages/{msg.id}/feedback",
            json={"feedback": "positive"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 204
        await db_session.refresh(msg)
        assert msg.feedback == MessageFeedback.positive


class TestMessageAnnotate:
    async def test_sets_annotation_and_note(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)
        msg = await _make_message(db_session, conv)

        r = await client.patch(
            f"/api/v1/conversations/messages/{msg.id}/annotate",
            json={"annotation": "hallucination", "note": "inventó un teléfono"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 204
        await db_session.refresh(msg)
        assert msg.annotation == "hallucination"
        assert msg.annotation_note == "inventó un teléfono"


class TestConversationTags:
    async def test_replaces_tags_normalized(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)

        r = await client.put(
            f"/api/v1/conversations/{conv.id}/tags",
            json={"tags": ["  Becas ", "matricula", "becas"]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        await db_session.refresh(conv)
        assert conv.tags == ["becas", "matricula"]


class TestBulkAction:
    async def test_empty_ids_returns_zero_affected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/conversations/bulk",
            json={"conversation_ids": [], "action": "resolve"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json() == {"affected": 0, "errors": []}

    async def test_unsupported_action_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/conversations/bulk",
            json={"conversation_ids": [str(uuid.uuid4())], "action": "delete_everything"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_resolve_multiple_conversations_in_one_call(self, client, admin_user, auth_headers, db_session):
        conv1 = await _make_conversation(db_session)
        conv2 = await _make_conversation(db_session)
        missing_id = uuid.uuid4()

        r = await client.post(
            "/api/v1/conversations/bulk",
            json={
                "conversation_ids": [str(conv1.id), str(conv2.id), str(missing_id)],
                "action": "resolve",
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["affected"] == 2
        assert len(body["errors"]) == 1
        assert body["errors"][0]["id"] == str(missing_id)

        await db_session.refresh(conv1)
        await db_session.refresh(conv2)
        assert conv1.status == ConversationStatus.resolved
        assert conv2.status == ConversationStatus.resolved

    async def test_set_tags_bulk(self, client, admin_user, auth_headers, db_session):
        conv = await _make_conversation(db_session)

        r = await client.post(
            "/api/v1/conversations/bulk",
            json={
                "conversation_ids": [str(conv.id)],
                "action": "set_tags",
                "tags": ["urgente", "Becas"],
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["affected"] == 1
        await db_session.refresh(conv)
        assert conv.tags == ["becas", "urgente"]
