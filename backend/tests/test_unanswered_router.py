"""Tests de caracterización para app/api/v1/unanswered/router.py.

test_unanswered_api.py solo cubre GET /unanswered (list_grouped). Los
endpoints resolve_question y create_faq_from_unanswered no tenían ningún test.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import UnansweredStatus
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

    async def test_create_faq_requires_knowledge_create_not_only_conversations_update(
        self, client, make_user, auth_headers, make_question, db_session,
    ):
        from app.models.rbac import Role, Permission, RolePermission
        from sqlalchemy import select

        role_name = f"convs-only-{uuid.uuid4().hex[:8]}"
        db_session.add(Role(name=role_name, display_name="Solo conversaciones", is_system=False))
        await db_session.commit()

        perm = await db_session.scalar(
            select(Permission).where(Permission.name == "conversations.update")
        )
        assert perm is not None, "seed_rbac debe haber corrido ya (fixture db_session)"
        db_session.add(RolePermission(role=role_name, permission_id=perm.id))
        await db_session.commit()

        limited_user = await make_user(role=role_name)
        q = await make_question(question="¿Horario de biblioteca?")

        r = await client.post(
            f"/api/v1/unanswered/{q.id}/create-faq",
            json={"answer": "8am a 6pm", "tags": []},
            headers=auth_headers(limited_user),
        )
        assert r.status_code == 403
