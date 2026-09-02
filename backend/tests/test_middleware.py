from __future__ import annotations

import pytest

from app.core.config import get_settings


class TestSecurityHeaders:
    async def test_response_carries_security_headers(self, client):
        r = await client.get("/api/v1/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in r.headers


class TestSplitCORS:
    async def test_public_route_reflects_any_origin(self, client):
        r = await client.options(
            "/api/v1/widget/public/config",
            headers={
                "Origin": "https://anywhere.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 204
        assert r.headers["Access-Control-Allow-Origin"] == "https://anywhere.example"

    async def test_admin_route_rejects_unknown_origin(self, client):
        r = await client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "https://not-allowed.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 403

    async def test_public_get_response_has_cors_header(self, client):
        r = await client.get(
            "/api/v1/health",
            headers={"Origin": "https://anywhere.example"},
        )
        assert r.headers.get("Access-Control-Allow-Origin") == "https://anywhere.example"


class TestJsonBodyValidation:
    async def test_oversized_json_body_rejected(self, client):
        settings = get_settings()
        oversized = "a" * (int(settings.MAX_JSON_BODY_SIZE_MB * 1024 * 1024) + 1)
        r = await client.post(
            "/api/v1/auth/login",
            content=f'{{"email":"a@b.com","password":"{oversized}"}}'.encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413

    async def test_malformed_json_rejected(self, client):
        r = await client.post(
            "/api/v1/auth/login",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    async def test_valid_json_reaches_endpoint(self, client):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        assert r.status_code in (401, 422)
