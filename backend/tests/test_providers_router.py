"""Tests para app/api/v1/providers/router.py - no tenía ningún test."""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _create_provider(client, admin_user, auth_headers, **overrides) -> dict:
    payload = {
        "name": "Groq principal",
        "provider_type": "groq",
        "model_name": "llama-3.1-70b",
        "api_key": "sk-test-123",
        "priority": 1,
    }
    payload.update(overrides)
    r = await client.post("/api/v1/providers", json=payload, headers=auth_headers(admin_user))
    assert r.status_code == 201, r.text
    return r.json()


class TestListProviders:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/providers")
        assert r.status_code == 401

    async def test_empty_list(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/providers", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_flags_a_key_that_cannot_be_read(self, client, admin_user, auth_headers, db_session):
        from app.models.llm_provider import LLMProvider

        created = await _create_provider(client, admin_user, auth_headers)
        provider = await db_session.get(LLMProvider, uuid.UUID(created["id"]))
        provider.api_key_encrypted = "gAAAAAclave-cifrada-con-otra-secret-key"
        await db_session.commit()

        r = await client.get("/api/v1/providers", headers=auth_headers(admin_user))

        assert r.json()[0]["api_key_unreadable"] is True


class TestCreateProvider:
    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/providers",
            json={"name": "x", "provider_type": "groq", "model_name": "m"},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_creates_provider_without_exposing_api_key(self, client, admin_user, auth_headers):
        body = await _create_provider(client, admin_user, auth_headers)
        assert body["name"] == "Groq principal"
        assert body["has_api_key"] is True
        assert "api_key" not in body


class TestRevealApiKey:
    async def test_admin_sees_the_saved_key(self, client, admin_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)

        r = await client.get(f"/api/v1/providers/{created['id']}/api-key", headers=auth_headers(admin_user))

        assert r.status_code == 200
        assert r.json() == {"api_key": "sk-test-123"}

    async def test_reader_cannot_see_the_key(self, client, admin_user, viewer_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)

        r = await client.get(f"/api/v1/providers/{created['id']}/api-key", headers=auth_headers(viewer_user))

        assert r.status_code == 403

    async def test_revealing_is_audited(self, client, admin_user, auth_headers, db_session):
        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        created = await _create_provider(client, admin_user, auth_headers)
        await client.get(f"/api/v1/providers/{created['id']}/api-key", headers=auth_headers(admin_user))

        actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert "provider.api_key_revealed" in actions


class TestChainPriorities:
    async def test_deleting_the_main_provider_promotes_the_next_one(self, client, admin_user, auth_headers):
        main = await _create_provider(client, admin_user, auth_headers, name="Principal", priority=1)
        await _create_provider(client, admin_user, auth_headers, name="Respaldo", priority=2)

        await client.delete(f"/api/v1/providers/{main['id']}", headers=auth_headers(admin_user))

        body = (await client.get("/api/v1/providers", headers=auth_headers(admin_user))).json()
        assert [(p["name"], p["priority"]) for p in body] == [("Respaldo", 1)]

    async def test_removing_from_the_chain_closes_the_gap(self, client, admin_user, auth_headers):
        first = await _create_provider(client, admin_user, auth_headers, name="Uno", priority=1)
        await _create_provider(client, admin_user, auth_headers, name="Dos", priority=2)

        await client.patch(f"/api/v1/providers/{first['id']}", json={"priority": None}, headers=auth_headers(admin_user))

        body = (await client.get("/api/v1/providers", headers=auth_headers(admin_user))).json()
        assert {p["name"]: p["priority"] for p in body} == {"Dos": 1, "Uno": None}


class TestUpdateProvider:
    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            f"/api/v1/providers/{uuid.uuid4()}",
            json={"name": "nuevo nombre"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_updates_name(self, client, admin_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)
        r = await client.patch(
            f"/api/v1/providers/{created['id']}",
            json={"name": "Groq secundario"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Groq secundario"

    async def test_editing_a_blocked_provider_unblocks_it(self, client, admin_user, auth_headers, monkeypatch):
        from app.services.ai import llm_gateway as gw

        monkeypatch.setattr(gw, "_breaker", gw.CircuitBreaker())
        created = await _create_provider(client, admin_user, auth_headers)
        gw._breaker.force_open(created["id"])

        r = await client.patch(
            f"/api/v1/providers/{created['id']}",
            json={"api_key": "clave-corregida"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert gw._breaker.is_open(created["id"]) is False

    async def test_rejects_api_base_over_max_length(self, client, admin_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)
        r = await client.patch(
            f"/api/v1/providers/{created['id']}",
            json={"api_base": "https://example.com/" + "x" * 500},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_dashboard_url_over_max_length(self, client, admin_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)
        r = await client.patch(
            f"/api/v1/providers/{created['id']}",
            json={"dashboard_url": "https://example.com/" + "x" * 500},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422


class TestDeleteProvider:
    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.delete(f"/api/v1/providers/{uuid.uuid4()}", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_deletes_provider(self, client, admin_user, auth_headers):
        created = await _create_provider(client, admin_user, auth_headers)
        r = await client.delete(f"/api/v1/providers/{created['id']}", headers=auth_headers(admin_user))
        assert r.status_code == 204

        listed = await client.get("/api/v1/providers", headers=auth_headers(admin_user))
        assert listed.json() == []


class TestReorderProviders:
    async def test_reorders_priority(self, client, admin_user, auth_headers):
        p1 = await _create_provider(client, admin_user, auth_headers, name="P1", priority=1)
        p2 = await _create_provider(client, admin_user, auth_headers, name="P2", priority=2)

        r = await client.post(
            "/api/v1/providers/reorder",
            json={"items": [{"id": p1["id"], "priority": 2}, {"id": p2["id"], "priority": 1}]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        by_id = {item["id"]: item["priority"] for item in r.json()}
        assert by_id[p1["id"]] == 2
        assert by_id[p2["id"]] == 1


class TestTestConnection:
    async def test_ad_hoc_test_success(self, client, admin_user, auth_headers, monkeypatch):
        async def _fake_test_connection(**kwargs):
            return {"success": True, "latency_ms": 123, "error": None}

        from app.api.v1.providers import router as providers_router
        monkeypatch.setattr(providers_router, "test_connection", _fake_test_connection)

        r = await client.post(
            "/api/v1/providers/test",
            json={"provider_type": "groq", "model_name": "llama-3.1-70b", "api_key": "sk-x"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json() == {"success": True, "latency_ms": 123, "error": None}

    async def test_saved_provider_test_persists_result(self, client, admin_user, auth_headers, monkeypatch, db_session):
        async def _fake_test_connection(**kwargs):
            return {"success": False, "latency_ms": None, "error": "timeout"}

        from app.api.v1.providers import router as providers_router
        monkeypatch.setattr(providers_router, "test_connection", _fake_test_connection)

        created = await _create_provider(client, admin_user, auth_headers)
        r = await client.post(
            f"/api/v1/providers/{created['id']}/test", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["success"] is False

        listed = await client.get("/api/v1/providers", headers=auth_headers(admin_user))
        saved = next(p for p in listed.json() if p["id"] == created["id"])
        assert saved["last_test_ok"] is False
        assert saved["last_test_error"] == "timeout"

    async def test_saved_provider_test_not_found(self, client, admin_user, auth_headers):
        r = await client.post(
            f"/api/v1/providers/{uuid.uuid4()}/test", headers=auth_headers(admin_user),
        )
        assert r.status_code == 404


