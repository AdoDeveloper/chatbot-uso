"""Tests para app/api/v1/system/cache/router.py — no tenía ningún test.

Cubre stats, listado de entradas, borrado (total y por key) y actualización
de config del caché semántico. Usa el Redis fake (fakeredis) inyectado por
el fixture `client` para poblar entradas reales vía app.services.ai.semantic_cache,
sin mockear los endpoints.
"""
from __future__ import annotations

import json

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


@pytest.fixture(autouse=True)
def _patch_cache_svc_redis(client, monkeypatch):
    """El fixture `client` mockea `app.core.redis.get_redis` con un FakeRedis,
    pero app/services/ai/semantic_cache.py hace `from app.core.redis import
    get_redis` (import directo) — ese binding ya quedó resuelto al importar
    el módulo, así que el monkeypatch de conftest no lo alcanza. Reapuntamos
    `cache_svc.get_redis` al mismo `get_redis` (ya parcheado) para que el
    router de cache y este helper de seed usen la misma instancia FakeRedis.
    """
    from app.core import redis as redis_mod
    from app.services.ai import semantic_cache as cache_svc

    monkeypatch.setattr(cache_svc, "get_redis", redis_mod.get_redis)


async def _seed_cache_entry(key: str = "semcache:v2:prod:abc123", question: str = "¿Cuándo es la matrícula?") -> None:
    """Crea una entrada real en el Redis fake usado por el cliente de test."""
    from app.services.ai import semantic_cache as cache_svc

    redis = cache_svc.get_redis()
    await redis.hset(key, mapping={
        "question": question,
        "embedding": json.dumps([0.1, 0.2, 0.3]),
        "sources": json.dumps([]),
        "content": "La matrícula es del 1 al 15 de marzo.",
        "source_ids": "[]",
    })


class TestGetStats:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/cache/stats")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/cache/stats", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_zero_entries_when_empty(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total_entries"] == 0
        assert "enabled" in body
        assert "ttl_seconds" in body
        assert "similarity_threshold" in body

    async def test_counts_seeded_entries(self, client, admin_user, auth_headers):
        await _seed_cache_entry("semcache:v2:prod:one")
        await _seed_cache_entry("semcache:v2:prod:two", question="¿Requisitos de admisión?")

        r = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["total_entries"] == 2

    async def test_reflects_config_overrides(self, client, admin_user, auth_headers):
        await client.patch(
            "/api/v1/cache/config",
            json={"enabled": False, "ttl_seconds": 3600, "similarity_threshold": 0.8},
            headers=auth_headers(admin_user),
        )
        r = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["ttl_seconds"] == 3600
        assert body["similarity_threshold"] == 0.8


class TestListEntries:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/cache/entries")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/cache/entries", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_empty_list_when_no_entries(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/cache/entries", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_returns_seeded_entries(self, client, admin_user, auth_headers):
        await _seed_cache_entry("semcache:v2:prod:one", question="¿Cuándo es la matrícula?")

        r = await client.get("/api/v1/cache/entries", headers=auth_headers(admin_user))
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) == 1
        assert entries[0]["key"] == "semcache:v2:prod:one"
        assert entries[0]["question"] == "¿Cuándo es la matrícula?"

    async def test_respects_page_size(self, client, admin_user, auth_headers):
        for i in range(5):
            await _seed_cache_entry(f"semcache:v2:prod:{i}", question=f"pregunta {i}")

        r = await client.get("/api/v1/cache/entries?page_size=2", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_rejects_page_size_over_limit(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/cache/entries?page_size=1000", headers=auth_headers(admin_user))
        assert r.status_code == 422

    async def test_rejects_page_size_below_minimum(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/cache/entries?page_size=0", headers=auth_headers(admin_user))
        assert r.status_code == 422


class TestClearCache:
    async def test_requires_auth(self, client):
        r = await client.delete("/api/v1/cache/clear")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.delete("/api/v1/cache/clear", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_clears_all_entries(self, client, admin_user, auth_headers):
        await _seed_cache_entry("semcache:v2:prod:one")
        await _seed_cache_entry("semcache:v2:prod:two", question="otra pregunta")

        r = await client.delete("/api/v1/cache/clear", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["deleted"] == 2

        stats = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert stats.json()["total_entries"] == 0

    async def test_clear_when_empty_returns_zero(self, client, admin_user, auth_headers):
        r = await client.delete("/api/v1/cache/clear", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["deleted"] == 0


class TestDeleteEntry:
    async def test_requires_auth(self, client):
        r = await client.delete("/api/v1/cache/entry/some-key")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.delete("/api/v1/cache/entry/some-key", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_deletes_existing_entry(self, client, admin_user, auth_headers):
        await _seed_cache_entry("semcache:v2:prod:target", question="pregunta objetivo")
        await _seed_cache_entry("semcache:v2:prod:other", question="otra pregunta")

        r = await client.delete("/api/v1/cache/entry/semcache:v2:prod:target", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["ok"] is True

        listed = await client.get("/api/v1/cache/entries", headers=auth_headers(admin_user))
        keys = [e["key"] for e in listed.json()]
        assert "semcache:v2:prod:target" not in keys
        assert "semcache:v2:prod:other" in keys

    async def test_deleting_nonexistent_key_is_a_noop_success(self, client, admin_user, auth_headers):
        r = await client.delete("/api/v1/cache/entry/semcache:v2:prod:no-existe", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestUpdateConfig:
    async def test_requires_auth(self, client):
        r = await client.patch("/api/v1/cache/config", json={"enabled": False})
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.patch(
            "/api/v1/cache/config", json={"enabled": False}, headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_updates_enabled_flag(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/cache/config", json={"enabled": False}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        stats = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert stats.json()["enabled"] is False

    async def test_updates_ttl_and_threshold(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/cache/config",
            json={"ttl_seconds": 7200, "similarity_threshold": 0.85},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        stats = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        body = stats.json()
        assert body["ttl_seconds"] == 7200
        assert body["similarity_threshold"] == 0.85

    async def test_empty_body_is_a_noop(self, client, admin_user, auth_headers):
        before = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        r = await client.patch("/api/v1/cache/config", json={}, headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["ok"] is True

        after = await client.get("/api/v1/cache/stats", headers=auth_headers(admin_user))
        assert before.json() == after.json()

    async def test_rejects_invalid_types(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/cache/config",
            json={"enabled": "no-es-booleano"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422
