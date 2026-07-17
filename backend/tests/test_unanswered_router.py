"""Tests de caracterización para app/api/v1/unanswered/router.py.

test_unanswered_api.py solo cubre GET /unanswered (list_grouped). Los
endpoints resolve_question, create_faq_from_unanswered y root_cause
(este último con 4 heurísticas de diagnóstico) no tenían ningún test.
Se fijan aquí antes de mover root_cause a servicio.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageRole, UnansweredStatus
from app.models.unanswered_question import UnansweredQuestion


@pytest.fixture
async def make_question(db_session):
    async def _factory(*, question="¿Cuál es el horario?", conversation_id=None, detected_topic=None):
        q = UnansweredQuestion(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            question=question,
            detected_topic=detected_topic,
            status=UnansweredStatus.open,
        )
        db_session.add(q)
        await db_session.commit()
        await db_session.refresh(q)
        return q
    return _factory


@pytest.fixture
async def make_conversation(db_session):
    async def _factory():
        c = ChatConversation(id=uuid.uuid4(), session_id=f"sess-{uuid.uuid4().hex[:8]}", status=ConversationStatus.active)
        db_session.add(c)
        await db_session.commit()
        await db_session.refresh(c)
        return c
    return _factory


@pytest.fixture
async def make_message(db_session):
    async def _factory(*, conversation_id, role, content, rag_route=None, sources_json=None):
        m = ChatMessage(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            rag_route=rag_route,
            sources_json=sources_json or [],
        )
        db_session.add(m)
        await db_session.commit()
        await db_session.refresh(m)
        return m
    return _factory


class TestResolveQuestion:
    async def test_resolve_not_found(self, client, admin_user, auth_headers):
        r = await client.post(f"/api/v1/unanswered/{uuid.uuid4()}/resolve", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_resolve_marks_resolved(self, client, admin_user, auth_headers, make_question, db_session):
        q = await make_question()
        r = await client.post(f"/api/v1/unanswered/{q.id}/resolve", headers=auth_headers(admin_user))
        assert r.status_code == 204

        await db_session.refresh(q)
        assert q.status == UnansweredStatus.resolved
        assert q.resolved_by_id == admin_user.id
        assert q.resolved_at is not None


class TestCreateFaqFromUnanswered:
    async def test_create_faq_not_found(self, client, admin_user, auth_headers):
        r = await client.post(
            f"/api/v1/unanswered/{uuid.uuid4()}/create-faq",
            json={"answer": "La respuesta es X", "tags": []},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_create_faq_resolves_question(self, client, admin_user, auth_headers, make_question, db_session, monkeypatch):
        q = await make_question(question="¿Horario de biblioteca?")

        class _FakeEntry:
            id = uuid.uuid4()

        async def _fake_create_faq(db, *, question, answer, tags, created_by_id):
            return _FakeEntry()

        import app.services.knowledge.faq as faq_svc
        monkeypatch.setattr(faq_svc, "create_faq", _fake_create_faq)

        r = await client.post(
            f"/api/v1/unanswered/{q.id}/create-faq",
            json={"answer": "8am a 6pm", "tags": ["horarios"]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        assert "faq_id" in r.json()

        await db_session.refresh(q)
        assert q.status == UnansweredStatus.resolved


class TestRootCause:
    async def test_root_cause_not_found(self, client, admin_user, auth_headers):
        r = await client.get(f"/api/v1/unanswered/{uuid.uuid4()}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_root_cause_indeterminate_when_no_conversation(self, client, admin_user, auth_headers, make_question):
        q = await make_question(question="pregunta única sin conversación")
        r = await client.get(f"/api/v1/unanswered/{q.id}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        codes = [c["code"] for c in body["causes"]]
        assert codes == ["indeterminate"]

    async def test_root_cause_recurring_question(self, client, admin_user, auth_headers, make_question):
        text = "¿Cómo me inscribo?"
        await make_question(question=text)
        await make_question(question=text)
        q3 = await make_question(question=text)

        r = await client.get(f"/api/v1/unanswered/{q3.id}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        codes = [c["code"] for c in body["causes"]]
        assert "recurring" in codes

    async def test_root_cause_no_coverage(self, client, admin_user, auth_headers, make_question, make_conversation, make_message):
        conv = await make_conversation()
        await make_message(conversation_id=conv.id, role=MessageRole.user, content="pregunta")
        await make_message(conversation_id=conv.id, role=MessageRole.assistant, content="no sé", rag_route="no_context")
        q = await make_question(question="pregunta sin cobertura", conversation_id=conv.id)

        r = await client.get(f"/api/v1/unanswered/{q.id}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 200
        codes = [c["code"] for c in r.json()["causes"]]
        assert "no_coverage" in codes

    async def test_root_cause_loop_detected(self, client, admin_user, auth_headers, make_question, make_conversation, make_message):
        conv = await make_conversation()
        await make_message(conversation_id=conv.id, role=MessageRole.user, content="pregunta 1")
        await make_message(conversation_id=conv.id, role=MessageRole.assistant, content="misma respuesta", rag_route="hybrid")
        await make_message(conversation_id=conv.id, role=MessageRole.user, content="pregunta 2")
        await make_message(conversation_id=conv.id, role=MessageRole.assistant, content="misma respuesta", rag_route="hybrid")
        q = await make_question(question="pregunta en bucle", conversation_id=conv.id)

        r = await client.get(f"/api/v1/unanswered/{q.id}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 200
        codes = [c["code"] for c in r.json()["causes"]]
        assert "loop" in codes

    async def test_root_cause_low_confidence(self, client, admin_user, auth_headers, make_question, make_conversation, make_message):
        conv = await make_conversation()
        await make_message(conversation_id=conv.id, role=MessageRole.user, content="pregunta")
        await make_message(
            conversation_id=conv.id, role=MessageRole.assistant, content="respuesta débil",
            rag_route="hybrid", sources_json=[{"score": 0.12}],
        )
        q = await make_question(question="pregunta con baja confianza", conversation_id=conv.id)

        r = await client.get(f"/api/v1/unanswered/{q.id}/root-cause", headers=auth_headers(admin_user))
        assert r.status_code == 200
        codes = [c["code"] for c in r.json()["causes"]]
        assert "low_confidence" in codes
