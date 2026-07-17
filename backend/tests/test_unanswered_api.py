from __future__ import annotations

import uuid



class TestUnansweredList:
    async def test_list_requires_auth(self, client):
        r = await client.get("/api/v1/unanswered")
        assert r.status_code == 401

    async def test_list_returns_empty_when_no_questions(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/unanswered",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["groups"] == []

    async def test_list_groups_by_detected_topic(self, client, admin_user, auth_headers, db_session):
        from app.models.unanswered_question import UnansweredQuestion

        db_session.add(UnansweredQuestion(
            id=uuid.uuid4(), question="¿Cuándo inician las clases?", detected_topic="calendario",
        ))
        db_session.add(UnansweredQuestion(
            id=uuid.uuid4(), question="¿Cuál es la fecha de matrícula?", detected_topic="calendario",
        ))
        db_session.add(UnansweredQuestion(
            id=uuid.uuid4(), question="¿Cuánto cuesta la mensualidad?", detected_topic=None,
        ))
        await db_session.commit()

        r = await client.get(
            "/api/v1/unanswered",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        by_topic = {g["topic"]: g for g in body["groups"]}
        assert by_topic["Calendario"]["count"] == 2
        assert by_topic["Sin Clasificar"]["count"] == 1
