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


def test_testing_a_provider_does_not_create_a_config_version():
    from app.core.versioning import _match_route

    assert _match_route("POST", "/api/v1/providers/test") is None
    assert _match_route("POST", "/api/v1/providers/7f0c/test") is None
    assert _match_route("POST", "/api/v1/providers/reorder") == "providers"
    assert _match_route("PATCH", "/api/v1/providers/7f0c") == "providers"


def test_public_uploads_only_serve_images(tmp_path):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from app.main import _ImagesOnlyStaticFiles

    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "reglamento.pdf").write_bytes(b"%PDF-1.4")
    app = Starlette()
    app.mount("/uploads", _ImagesOnlyStaticFiles(directory=str(tmp_path)))
    client = TestClient(app)

    assert client.get("/uploads/logo.png").status_code == 200
    assert client.get("/uploads/reglamento.pdf").status_code == 404


async def test_deeply_nested_json_is_rejected_without_500(client):
    body = "[" * 5000 + "]" * 5000
    r = await client.post(
        "/api/v1/auth/login", content=body, headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
