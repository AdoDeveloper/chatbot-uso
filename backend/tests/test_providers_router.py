"""Tests para app/api/v1/providers/router.py — no tenía ningún test.

Los endpoints /test, /models y /{id}/test llaman a proveedores LLM externos
reales (llm_gateway.test_connection / fetch_models) — se mockean con
monkeypatch para no hacer llamadas HTTP de verdad ni depender de que un
proveedor externo esté disponible.
"""
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


class TestListModels:
    async def test_ad_hoc_models(self, client, admin_user, auth_headers, monkeypatch):
        async def _fake_fetch_models(**kwargs):
            return [{"id": "llama-3.1-70b", "name": "Llama 3.1 70B"}]

        from app.api.v1.providers import router as providers_router
        monkeypatch.setattr(providers_router, "fetch_models", _fake_fetch_models)

        r = await client.post(
            "/api/v1/providers/models",
            json={"provider_type": "groq", "api_key": "sk-x"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["models"] == [{"id": "llama-3.1-70b", "name": "Llama 3.1 70B"}]

    async def test_ad_hoc_models_invalid_provider_returns_422(self, client, admin_user, auth_headers, monkeypatch):
        async def _fake_fetch_models(**kwargs):
            raise ValueError("URL base desconocida")

        from app.api.v1.providers import router as providers_router
        monkeypatch.setattr(providers_router, "fetch_models", _fake_fetch_models)

        r = await client.post(
            "/api/v1/providers/models",
            json={"provider_type": "inventado"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_saved_provider_models_not_found(self, client, admin_user, auth_headers):
        r = await client.get(
            f"/api/v1/providers/{uuid.uuid4()}/models", headers=auth_headers(admin_user),
        )
        assert r.status_code == 404
