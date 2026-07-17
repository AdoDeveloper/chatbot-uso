"""Sanity check that the test infrastructure (DB, client, auth) wires up.

If any of these fail, every higher-level integration test will too — keeping
this file tiny means the failure points right at the fixture, not the code
under test.
"""
from __future__ import annotations


class TestFixtures:
    async def test_db_session_can_query(self, db_session):
        from sqlalchemy import text
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

    async def test_make_user_persists(self, make_user, db_session):
        from sqlalchemy import select
        from app.models.user import User

        u = await make_user(email="alice@example.com")
        rows = (await db_session.execute(select(User))).scalars().all()
        assert any(r.email == "alice@example.com" for r in rows)
        assert u.is_active is True

    async def test_client_returns_404_on_missing_route(self, client):
        # Just exercise the ASGI transport.
        r = await client.get("/api/v1/__definitely_not_a_route__")
        assert r.status_code == 404

    async def test_health_endpoint(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200

    async def test_unauth_request_is_rejected(self, client):
        r = await client.get("/api/v1/faq")
        assert r.status_code in (401, 403)

    async def test_authed_request_passes(self, client, make_user, auth_headers):
        u = await make_user()
        r = await client.get("/api/v1/faq", headers=auth_headers(u))
        assert r.status_code == 200
        assert isinstance(r.json(), list)
