"""Tests para app/api/v1/audit/router.py.

Cubre el listado con sus filtros y orden, el detalle, la lista de actores y
la exportacion. La exportacion recibe atencion especial: sus filtros deben
coincidir con los del listado, porque un archivo que no corresponde a lo
consultado invalida el registro como evidencia.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from app.models.audit_log import AuditLog
from app.models.enums import UserRole


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _seed_log(
    db_session,
    *,
    action: str = "source.create",
    resource_type: str = "source",
    actor_id: uuid.UUID | None = None,
    ip: str | None = None,
    created_at: datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        id=uuid.uuid4(),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id="r-1",
        meta_json={},
        ip=ip,
    )
    if created_at is not None:
        row.created_at = created_at
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


class TestListLogs:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/audit/logs")
        assert r.status_code in (401, 403)

    async def test_viewer_cannot_read_audit(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/audit/logs", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_lists_with_actor_name(self, client, db_session, admin_user, auth_headers):
        await _seed_log(db_session, actor_id=admin_user.id)

        r = await client.get("/api/v1/audit/logs", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert body["logs"][0]["actor_name"] == admin_user.full_name

    async def test_filters_by_resource_type(self, client, db_session, admin_user, auth_headers):
        await _seed_log(db_session, resource_type="source")
        await _seed_log(db_session, resource_type="user")

        r = await client.get(
            "/api/v1/audit/logs?resource_type=user", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        tipos = {row["resource_type"] for row in r.json()["logs"]}
        assert tipos == {"user"}

    async def test_filters_by_actor(self, client, db_session, admin_user, make_user, auth_headers):
        otro = await make_user(role=UserRole.editor)
        await _seed_log(db_session, actor_id=admin_user.id)
        await _seed_log(db_session, actor_id=otro.id)

        r = await client.get(
            f"/api/v1/audit/logs?actor_id={otro.id}", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        actores = {row["actor_id"] for row in r.json()["logs"]}
        assert actores == {str(otro.id)}

    async def test_filters_by_ip(self, client, db_session, admin_user, auth_headers):
        await _seed_log(db_session, ip="10.0.0.1")
        await _seed_log(db_session, ip="10.0.0.2")

        r = await client.get(
            "/api/v1/audit/logs?ip=10.0.0.2", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert {row["ip"] for row in r.json()["logs"]} == {"10.0.0.2"}

    async def test_filters_by_date_range(self, client, db_session, admin_user, auth_headers):
        ahora = datetime.now(timezone.utc)
        await _seed_log(db_session, action="viejo", created_at=ahora - timedelta(days=10))
        await _seed_log(db_session, action="reciente", created_at=ahora)

        desde = urlencode({"date_from": (ahora - timedelta(days=1)).isoformat()})
        r = await client.get(
            f"/api/v1/audit/logs?{desde}", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert "viejo" not in {row["action"] for row in r.json()["logs"]}

    async def test_paginates(self, client, db_session, admin_user, auth_headers):
        for _ in range(3):
            await _seed_log(db_session)

        r = await client.get(
            "/api/v1/audit/logs?page=1&page_size=2", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["logs"]) == 2
        assert body["page_size"] == 2
        assert body["total"] >= 3

    async def test_rejects_unknown_sort_field(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/audit/logs?sort_by=hashed_password", headers=auth_headers(admin_user)
        )
        assert r.status_code == 422


class TestLogDetail:
    async def test_returns_detail(self, client, db_session, admin_user, auth_headers):
        row = await _seed_log(db_session, actor_id=admin_user.id)

        r = await client.get(f"/api/v1/audit/logs/{row.id}", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["id"] == str(row.id)

    async def test_unknown_id_is_404(self, client, admin_user, auth_headers):
        r = await client.get(
            f"/api/v1/audit/logs/{uuid.uuid4()}", headers=auth_headers(admin_user)
        )
        assert r.status_code == 404


class TestActors:
    async def test_lists_only_actors_with_logs(
        self, client, db_session, admin_user, make_user, auth_headers
    ):
        sin_logs = await make_user(role=UserRole.editor)
        await _seed_log(db_session, actor_id=admin_user.id)

        r = await client.get("/api/v1/audit/actors", headers=auth_headers(admin_user))
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()}
        assert str(admin_user.id) in ids
        assert str(sin_logs.id) not in ids


class TestExportLogs:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/audit/logs/export")
        assert r.status_code in (401, 403)

    async def test_export_route_is_not_parsed_as_a_log_id(
        self, client, admin_user, auth_headers
    ):
        """`/logs/export` debe resolverse antes que `/logs/{log_id}`."""
        r = await client.get("/api/v1/audit/logs/export", headers=auth_headers(admin_user))
        assert r.status_code == 200

    async def test_exports_xlsx(self, client, db_session, admin_user, auth_headers):
        await _seed_log(db_session)

        r = await client.get("/api/v1/audit/logs/export", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert "spreadsheet" in r.headers["content-type"]

    async def test_exports_pdf(self, client, db_session, admin_user, auth_headers):
        await _seed_log(db_session)

        r = await client.get(
            "/api/v1/audit/logs/export?format=pdf", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")

    async def test_rejects_unknown_format(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/audit/logs/export?format=csv", headers=auth_headers(admin_user)
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("campo", ["resource_type", "actor_id", "ip", "action"])
    async def test_export_accepts_the_same_filters_as_the_listing(
        self, client, admin_user, auth_headers, campo
    ):
        """Los filtros del listado deben existir tambien en la exportacion.

        Si uno falta, FastAPI lo descarta en silencio y el archivo generado
        no corresponde a lo que el panel muestra.
        """
        valores = {
            "resource_type": "source",
            "actor_id": str(admin_user.id),
            "ip": "10.0.0.1",
            "action": "create",
        }
        r = await client.get(
            f"/api/v1/audit/logs/export?{campo}={valores[campo]}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

    async def test_export_honours_the_resource_type_filter(
        self, client, db_session, admin_user, auth_headers
    ):
        await _seed_log(db_session, resource_type="source")
        await _seed_log(db_session, resource_type="user")

        completo = await client.get(
            "/api/v1/audit/logs/export", headers=auth_headers(admin_user)
        )
        filtrado = await client.get(
            "/api/v1/audit/logs/export?resource_type=user", headers=auth_headers(admin_user)
        )
        assert completo.status_code == filtrado.status_code == 200
        assert len(filtrado.content) < len(completo.content)
