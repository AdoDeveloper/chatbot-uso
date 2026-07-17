from __future__ import annotations


class TestRateLimitConfig:
    async def test_get_config_requires_auth(self, client):
        r = await client.get("/api/v1/rate-limits/config")
        assert r.status_code == 401

    async def test_get_config_returns_env_defaults(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/rate-limits/config",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["chat_per_min"] == 10
        assert body["chat_per_hour"] == 100

    async def test_patch_overrides_are_effective(self, client, admin_user, auth_headers):
        """El valor guardado desde el panel debe SOBREESCRIBIR el del .env."""
        headers = auth_headers(admin_user)
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 25, "chat_per_hour": 300},
            headers=headers,
        )
        assert r.status_code == 200

        r = await client.get("/api/v1/rate-limits/config", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["chat_per_min"] == 25
        assert body["chat_per_hour"] == 300

    async def test_runtime_overrides_feed_the_limiter(self, client, admin_user, auth_headers, db_session):
        """get_runtime_overrides (lo que consume el rate limiter) refleja el override."""
        from app.services.system.settings import get_runtime_overrides, invalidate_runtime_overrides

        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 7, "chat_per_hour": 70},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        invalidate_runtime_overrides()
        overrides = await get_runtime_overrides(db_session)
        assert overrides["rate_limit_chat_per_min"] == 7
        assert overrides["rate_limit_chat_per_hour"] == 70
        assert overrides["semantic_cache_enabled"] is True
