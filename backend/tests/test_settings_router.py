"""Tests para app/api/v1/settings/router.py — no tenía ningún test.

Cubre get/update settings (con warnings por parámetros riesgosos) y el
ciclo completo export -> import, incluyendo las validaciones de import
(extensión, content-type, tamaño, JSON malformado, versión incompatible).
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


class TestGetSettings:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/settings")
        assert r.status_code == 401

    async def test_returns_defaults(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/settings", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert "system_prompt" in r.json()


class TestUpdateSettings:
    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/settings", headers=auth_headers(viewer_user))
        current = r.json()
        r2 = await client.put("/api/v1/settings", json=current, headers=auth_headers(viewer_user))
        assert r2.status_code == 403

    async def test_updates_and_returns_no_warnings_for_sane_values(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/settings", headers=auth_headers(admin_user))
        current = r.json()
        current["temperature"] = 0.5
        current["top_k"] = 8
        current["score_threshold"] = 0.1

        r2 = await client.put("/api/v1/settings", json=current, headers=auth_headers(admin_user))
        assert r2.status_code == 200
        assert r2.json()["warnings"] == []

    async def test_returns_warnings_for_risky_values(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/settings", headers=auth_headers(admin_user))
        current = r.json()
        current["temperature"] = 1.9
        current["top_k"] = 20
        current["score_threshold"] = 0.99

        r2 = await client.put("/api/v1/settings", json=current, headers=auth_headers(admin_user))
        assert r2.status_code == 200
        warnings = r2.json()["warnings"]
        assert len(warnings) == 3


class TestExportSettings:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/settings/export")
        assert r.status_code == 401

    async def test_returns_downloadable_json(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/settings/export", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
        body = json.loads(r.content)
        assert body["version"] == "1"
        assert "system_prompt" in body["settings"]


class TestImportSettings:
    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", b'{"version":"1","settings":{}}', "application/json")},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_rejects_non_json_extension(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.txt", b"contenido", "text/plain")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_rejects_malformed_json(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", b"{esto no es json", "application/json")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_rejects_incompatible_version(self, client, admin_user, auth_headers):
        payload = json.dumps({"version": "99", "settings": {}}).encode()
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", payload, "application/json")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_rejects_file_over_size_limit(self, client, admin_user, auth_headers):
        huge = b"a" * (1024 * 1024 + 10)
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", huge, "application/json")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 413

    async def test_rejects_invalid_settings_shape(self, client, admin_user, auth_headers):
        payload = json.dumps({"version": "1", "settings": {"temperature": "no-es-un-numero"}}).encode()
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", payload, "application/json")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_roundtrip_export_then_import_succeeds(self, client, admin_user, auth_headers):
        exported = await client.get("/api/v1/settings/export", headers=auth_headers(admin_user))
        r = await client.post(
            "/api/v1/settings/import",
            files={"file": ("cfg.json", exported.content, "application/json")},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
