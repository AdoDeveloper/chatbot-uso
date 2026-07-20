"""Tests para app/api/v1/versions/router.py — no tenía ningún test.

Cubre listado paginado, creación de snapshot manual (incl. 409 sin cambios),
detalle, diff contra la versión padre, deploy (incl. 409 sin cambios desde el
último deploy), deploy/status, deploy/config, y rollback (incl. 404), con
verificación de RBAC (bot_settings.read / bot_settings.update) en cada
endpoint.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import UserRole
from app.models.global_setting import GlobalSetting


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _add_setting(db_session, key: str, value) -> None:
    """Crea o actualiza un GlobalSetting para que capture_snapshot() detecte un cambio real."""
    existing = await db_session.get(GlobalSetting, key)
    if existing:
        existing.value = value
    else:
        db_session.add(GlobalSetting(key=key, value=value))
    await db_session.commit()


class TestListVersions:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/versions")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        # viewer no tiene bot_settings.read en este módulo
        r = await client.get("/api/v1/versions", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_empty_list_when_no_versions(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/versions", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["versions"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["page_size"] == 20

    async def test_lists_created_versions_ordered_desc(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot A")
        r1 = await client.post("/api/v1/versions", json={"description": "v1"}, headers=auth_headers(admin_user))
        assert r1.status_code == 201

        await _add_setting(db_session, "chatbot_name", "Bot B")
        r2 = await client.post("/api/v1/versions", json={"description": "v2"}, headers=auth_headers(admin_user))
        assert r2.status_code == 201

        r = await client.get("/api/v1/versions", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        # Orden descendente por version_number
        assert body["versions"][0]["version_number"] > body["versions"][1]["version_number"]

    async def test_respects_pagination(self, client, admin_user, auth_headers, db_session):
        for i in range(3):
            await _add_setting(db_session, "chatbot_name", f"Bot {i}")
            r = await client.post(
                "/api/v1/versions", json={"description": f"v{i}"}, headers=auth_headers(admin_user),
            )
            assert r.status_code == 201

        r = await client.get("/api/v1/versions?page_size=2", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) == 2
        assert body["total"] == 3

        r2 = await client.get("/api/v1/versions?page=2&page_size=2", headers=auth_headers(admin_user))
        assert len(r2.json()["versions"]) == 1

    async def test_rejects_page_size_over_limit(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/versions?page_size=1000", headers=auth_headers(admin_user))
        assert r.status_code == 422

    async def test_rejects_page_below_minimum(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/versions?page=0", headers=auth_headers(admin_user))
        assert r.status_code == 422


class TestCreateVersion:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/versions", json={"description": "x"})
        assert r.status_code == 401

    async def test_requires_update_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/versions", json={"description": "x"}, headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_returns_409_when_no_changes(self, client, admin_user, auth_headers):
        # BD vacía: no hay diferencia respecto al estado (inexistente) anterior.
        r = await client.post("/api/v1/versions", json={"description": "sin cambios"}, headers=auth_headers(admin_user))
        assert r.status_code == 409

    async def test_creates_version_with_changes(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot Nuevo")

        r = await client.post(
            "/api/v1/versions", json={"description": "Cambio de nombre"}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["description"] == "Cambio de nombre"
        assert body["version_number"] == 1
        assert body["is_active"] is True
        assert body["created_by_name"] is not None

    async def test_uses_default_description_when_blank(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot X")
        r = await client.post("/api/v1/versions", json={}, headers=auth_headers(admin_user))
        assert r.status_code == 201
        assert r.json()["description"] == "Snapshot manual"


class TestGetVersion:
    async def test_requires_auth(self, client):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_404_for_unknown_id(self, client, admin_user, auth_headers):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_returns_detail_with_snapshot(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot Detalle")
        created = await client.post(
            "/api/v1/versions", json={"description": "detalle"}, headers=auth_headers(admin_user),
        )
        version_id = created.json()["id"]

        r = await client.get(f"/api/v1/versions/{version_id}", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == version_id
        assert "config_snapshot" in body
        assert "sections" in body["config_snapshot"]


class TestDiffVersion:
    async def test_requires_auth(self, client):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}/diff")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}/diff", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_404_for_unknown_id(self, client, admin_user, auth_headers):
        r = await client.get(f"/api/v1/versions/{uuid.uuid4()}/diff", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_diff_against_previous_version(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot Uno")
        v1 = await client.post("/api/v1/versions", json={"description": "v1"}, headers=auth_headers(admin_user))

        await _add_setting(db_session, "chatbot_name", "Bot Dos")
        v2 = await client.post("/api/v1/versions", json={"description": "v2"}, headers=auth_headers(admin_user))
        v2_id = v2.json()["id"]

        r = await client.get(f"/api/v1/versions/{v2_id}/diff", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["version_number"] == v2.json()["version_number"]
        assert "global_settings" in body["sections"]
        changes = body["sections"]["global_settings"]
        assert any(c["key"] == "chatbot_name" for c in changes)

    async def test_diff_for_first_version_has_no_parent(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot Solo")
        v1 = await client.post("/api/v1/versions", json={"description": "v1"}, headers=auth_headers(admin_user))
        v1_id = v1.json()["id"]

        r = await client.get(f"/api/v1/versions/{v1_id}/diff", headers=auth_headers(admin_user))
        assert r.status_code == 200
        # Sin padre, se compara contra estado vacío: chatbot_name aparece como "added".
        changes = r.json()["sections"]["global_settings"]
        assert any(c["key"] == "chatbot_name" and c["action"] == "added" for c in changes)


class TestDeployStatus:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/versions/deploy/status")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/versions/deploy/status", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_never_deployed_state(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/versions/deploy/status", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["never_deployed"] is True
        assert body["last_deployed_at"] is None
        assert body["last_deployed_version"] is None
        assert body["config_changed_since_deploy"] is True
        assert body["pending_sources"] == 0

    async def test_after_deploy_reflects_state(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot Deploy")
        deployed = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert deployed.status_code == 201

        r = await client.get("/api/v1/versions/deploy/status", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["never_deployed"] is False
        assert body["last_deployed_version"] == deployed.json()["version"]["version_number"]
        assert body["config_changed_since_deploy"] is False


class TestDeployConfig:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/versions/deploy/config")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/versions/deploy/config", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_empty_dict_when_never_deployed(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/versions/deploy/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == {}

    async def test_returns_widget_config_from_last_deploy(self, client, admin_user, auth_headers, db_session):
        from app.models.widget_config import WidgetConfig

        widget = WidgetConfig(chatbot_name="Bot Publicado")
        db_session.add(widget)
        await db_session.commit()

        deployed = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert deployed.status_code == 201

        r = await client.get("/api/v1/versions/deploy/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json().get("chatbot_name") == "Bot Publicado"


class TestDeploy:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/versions/deploy", json={})
        assert r.status_code == 401

    async def test_requires_update_perm(self, client, viewer_user, auth_headers):
        r = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_deploy_creates_version_tagged_deploy(self, client, admin_user, auth_headers, db_session):
        await _add_setting(db_session, "chatbot_name", "Bot A")
        r = await client.post(
            "/api/v1/versions/deploy", json={"description": "primer deploy"}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["version"]["description"] == "primer deploy"
        assert "pending_sources" in body

    async def test_deploy_returns_409_when_no_changes_since_last_deploy(
        self, client, admin_user, auth_headers, db_session,
    ):
        await _add_setting(db_session, "chatbot_name", "Bot A")
        first = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert first.status_code == 201

        second = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert second.status_code == 409

    async def test_deploy_succeeds_again_after_further_changes(
        self, client, admin_user, auth_headers, db_session,
    ):
        await _add_setting(db_session, "chatbot_name", "Bot A")
        first = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert first.status_code == 201

        await _add_setting(db_session, "chatbot_name", "Bot B")
        second = await client.post("/api/v1/versions/deploy", json={}, headers=auth_headers(admin_user))
        assert second.status_code == 201
        assert second.json()["version"]["version_number"] > first.json()["version"]["version_number"]


class TestRollback:
    async def test_requires_auth(self, client):
        r = await client.post(f"/api/v1/versions/{uuid.uuid4()}/rollback")
        assert r.status_code == 401

    async def test_requires_update_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            f"/api/v1/versions/{uuid.uuid4()}/rollback", headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_returns_404_for_unknown_version(self, client, admin_user, auth_headers):
        r = await client.post(f"/api/v1/versions/{uuid.uuid4()}/rollback", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_rollback_restores_previous_setting_and_creates_new_version(
        self, client, admin_user, auth_headers, db_session,
    ):
        await _add_setting(db_session, "chatbot_name", "Bot Original")
        v1 = await client.post("/api/v1/versions", json={"description": "v1"}, headers=auth_headers(admin_user))
        v1_id = v1.json()["id"]

        await _add_setting(db_session, "chatbot_name", "Bot Modificado")
        v2 = await client.post("/api/v1/versions", json={"description": "v2"}, headers=auth_headers(admin_user))
        assert v2.status_code == 201

        r = await client.post(f"/api/v1/versions/{v1_id}/rollback", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert "warnings" in body
        assert body["version"]["version_number"] > v2.json()["version_number"]

        settings = await client.get("/api/v1/settings", headers=auth_headers(admin_user))
        assert settings.json()["chatbot_name"] == "Bot Original"
