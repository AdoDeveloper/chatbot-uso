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


@pytest.fixture
async def widget_config(db_session):
    from app.models.widget_config import WidgetConfig
    wc = WidgetConfig(
        id=uuid.uuid4(),
        chatbot_name="Test Bot",
        welcome_message="Hola",
        primary_color="#2563EB",
        position="right",
        api_key="test-widget-key-admin",
        domain_allowlist=["*"],
        show_sources=True,
        enable_feedback_icons=True,
        show_bot_icon=True,
        suggestions=[],
        proactive_message="",
        enable_csat=True,
        csat_question="¿Qué tan útil fue?",
    )
    db_session.add(wc)
    await db_session.commit()
    return wc


@pytest.fixture
async def make_conversation(db_session):
    from app.models.chat_conversation import ChatConversation
    from app.models.enums import ConversationStatus

    async def _factory():
        c = ChatConversation(
            id=uuid.uuid4(), session_id=f"sess-{uuid.uuid4().hex[:8]}",
            status=ConversationStatus.active,
        )
        db_session.add(c)
        await db_session.commit()
        await db_session.refresh(c)
        return c
    return _factory


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

    async def test_rejects_chatbot_name_over_max_length(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={"chatbot_name": "x" * 200},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_position_over_max_length(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/config",
            json={"position": "x" * 50},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

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


class TestCsatReasons:
    """CRUD de motivos CSAT configurables (GlobalSetting 'csat_reasons')."""

    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/widget/csat-reasons")
        assert r.status_code == 401

    async def test_list_returns_defaults_when_unset(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/widget/csat-reasons", headers=auth_headers(admin_user))
        assert r.status_code == 200
        ids = {item["id"] for item in r.json()}
        assert "helpful_answer" in ids
        assert "no_solution" in ids

    async def test_create_reason(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/widget/csat-reasons",
            json={"label": "Trato del asistente"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["label"] == "Trato del asistente"
        assert body["enabled"] is True
        assert body["id"]

        listed = await client.get("/api/v1/widget/csat-reasons", headers=auth_headers(admin_user))
        assert any(item["id"] == body["id"] for item in listed.json())

    async def test_create_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/widget/csat-reasons",
            json={"label": "x"},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_update_reason_label_and_enabled(self, client, admin_user, auth_headers):
        created = await client.post(
            "/api/v1/widget/csat-reasons",
            json={"label": "Original"},
            headers=auth_headers(admin_user),
        )
        reason_id = created.json()["id"]

        r = await client.patch(
            f"/api/v1/widget/csat-reasons/{reason_id}",
            json={"label": "Editado", "enabled": False},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "Editado"
        assert r.json()["enabled"] is False

    async def test_update_nonexistent_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/widget/csat-reasons/no-existe",
            json={"label": "x"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_delete_reason(self, client, admin_user, auth_headers):
        created = await client.post(
            "/api/v1/widget/csat-reasons",
            json={"label": "Temporal"},
            headers=auth_headers(admin_user),
        )
        reason_id = created.json()["id"]

        r = await client.delete(
            f"/api/v1/widget/csat-reasons/{reason_id}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 204

        listed = await client.get("/api/v1/widget/csat-reasons", headers=auth_headers(admin_user))
        assert not any(item["id"] == reason_id for item in listed.json())

    async def test_delete_nonexistent_returns_404(self, client, admin_user, auth_headers):
        r = await client.delete(
            "/api/v1/widget/csat-reasons/no-existe",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_reorder_reasons(self, client, admin_user, auth_headers):
        listed = await client.get("/api/v1/widget/csat-reasons", headers=auth_headers(admin_user))
        ids = [item["id"] for item in listed.json()]
        reversed_ids = list(reversed(ids))

        r = await client.put(
            "/api/v1/widget/csat-reasons/reorder",
            json={"ordered_ids": reversed_ids},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        assert [item["id"] for item in r.json()] == reversed_ids

    async def test_reorder_rejects_mismatched_ids(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/widget/csat-reasons/reorder",
            json={"ordered_ids": ["a", "b", "c"]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_disabled_reason_not_offered_publicly_but_still_labeled_in_history(
        self, client, admin_user, auth_headers, widget_config, make_conversation, db_session,
    ):
        """Un motivo deshabilitado desaparece de /public/config (no se ofrece a
        nuevos usuarios) pero conversaciones ya calificadas con ese id deben
        poder seguir resolviendo su etiqueta vía GET /csat-reasons (incluye
        deshabilitados)."""
        created = await client.post(
            "/api/v1/widget/csat-reasons",
            json={"label": "Motivo a desactivar"},
            headers=auth_headers(admin_user),
        )
        reason_id = created.json()["id"]

        conv = await make_conversation()
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(conv.id), "score": 5, "reasons": [reason_id]},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204

        await client.patch(
            f"/api/v1/widget/csat-reasons/{reason_id}",
            json={"enabled": False},
            headers=auth_headers(admin_user),
        )

        public_cfg = await client.get(
            "/api/v1/widget/public/config",
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert reason_id not in public_cfg.json()["csat_reasons"]

        full_list = await client.get("/api/v1/widget/csat-reasons", headers=auth_headers(admin_user))
        assert any(item["id"] == reason_id for item in full_list.json())
