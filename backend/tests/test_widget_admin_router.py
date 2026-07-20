"""Tests para los endpoints administrativos (protegidos) de
app/api/v1/widget/router.py: GET/PUT /config, GET /embed-code y
POST /regenerate-key.

test_widget_public.py y test_widget_public_extra.py ya cubren los
endpoints públicos (/public/*, autenticados solo por X-Widget-Key). Estos
cuatro endpoints, en cambio, requieren sesión de usuario con permisos RBAC
(bot_settings.read / bot_settings.update) y no tenían ninguna prueba.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


class TestGetConfig:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/widget/config")
        assert r.status_code == 401

    async def test_admin_gets_config_creating_default_if_missing(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["chatbot_name"]
        assert "api_key" in body

    async def test_returns_existing_singleton_config(self, client, admin_user, auth_headers, db_session):
        from app.models.widget_config import WidgetConfig

        wc = WidgetConfig(
            id=uuid.uuid4(), chatbot_name="Mi Bot", welcome_message="Hola",
            primary_color="#123456", position="left", api_key="wk_existing",
            domain_allowlist=["*"], show_sources=True, enable_feedback_icons=True,
            show_bot_icon=True, suggestions=[], proactive_message="",
            enable_csat=False, csat_question="",
        )
        db_session.add(wc)
        await db_session.commit()

        r = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["chatbot_name"] == "Mi Bot"
        assert r.json()["api_key"] == "wk_existing"


class TestUpdateConfig:
    async def test_requires_auth(self, client):
        r = await client.put("/api/v1/widget/config", json={"chatbot_name": "X"})
        assert r.status_code == 401

    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={"chatbot_name": "X"},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_admin_updates_fields(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={
                "chatbot_name": "Nuevo Nombre",
                "primary_color": "#ABC",
                "welcome_message": "Bienvenido",
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["chatbot_name"] == "Nuevo Nombre"
        assert body["primary_color"] == "#aabbcc"
        assert body["welcome_message"] == "Bienvenido"

    async def test_update_persists_across_requests(self, client, admin_user, auth_headers):
        r1 = await client.put(
            "/api/v1/widget/config",
            json={"chatbot_name": "Persistente"},
            headers=auth_headers(admin_user),
        )
        assert r1.status_code == 200

        r2 = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        assert r2.status_code == 200
        assert r2.json()["chatbot_name"] == "Persistente"

    async def test_invalid_primary_color_is_422(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={"primary_color": "not-a-color"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_update_does_not_change_api_key(self, client, admin_user, auth_headers):
        r0 = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        original_key = r0.json()["api_key"]

        r = await client.put(
            "/api/v1/widget/config",
            json={"chatbot_name": "Otra Vez"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["api_key"] == original_key

    async def test_suggestions_are_deduplicated_and_trimmed(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={"suggestions": ["hola", "hola", "adios"]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["suggestions"] == ["hola", "adios"]


class TestEmbedCode:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/widget/embed-code")
        assert r.status_code == 401

    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/widget/embed-code", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_admin_gets_embed_code(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/widget/embed-code", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert "script_tag" in body
        assert "iframe_tag" in body
        assert body["api_key"] in body["script_tag"]
        assert body["api_key"] in body["iframe_tag"]


class TestRegenerateKey:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/widget/regenerate-key")
        assert r.status_code == 401

    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.post("/api/v1/widget/regenerate-key", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_admin_regenerates_key(self, client, admin_user, auth_headers):
        r0 = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        original_key = r0.json()["api_key"]

        r = await client.post("/api/v1/widget/regenerate-key", headers=auth_headers(admin_user))
        assert r.status_code == 200
        new_key = r.json()["api_key"]
        assert new_key != original_key
        assert new_key.startswith("wk_")

    async def test_old_key_is_invalidated_for_public_endpoints(self, client, admin_user, auth_headers):
        r0 = await client.get("/api/v1/widget/config", headers=auth_headers(admin_user))
        original_key = r0.json()["api_key"]

        r = await client.post("/api/v1/widget/regenerate-key", headers=auth_headers(admin_user))
        assert r.status_code == 200

        r_old = await client.get(
            "/api/v1/widget/public/config",
            headers={"X-Widget-Key": original_key},
        )
        assert r_old.status_code == 403

        new_key = r.json()["api_key"]
        r_new = await client.get(
            "/api/v1/widget/public/config",
            headers={"X-Widget-Key": new_key},
        )
        assert r_new.status_code == 200
