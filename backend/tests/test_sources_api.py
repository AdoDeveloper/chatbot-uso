"""Tests para el flujo de revisión de fuentes (approve/reject).

Cubren los endpoints añadidos tras eliminar `/environments/`:
  - POST /api/v1/sources/{id}/approve
  - POST /api/v1/sources/{id}/reject
  - GET  /api/v1/sources (listado con filtro de soft-delete)
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import (
    ReviewStatus, SourceStatus, SourceType, UserRole,
)
from app.models.source import Source


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def editor_user(make_user):
    return await make_user(role=UserRole.editor)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _create_source(
    db_session,
    *,
    name: str = "Manual de Procedimientos",
    review_status: ReviewStatus = ReviewStatus.pendiente_revision,
    status: SourceStatus = SourceStatus.ready,
) -> Source:
    src = Source(
        id=uuid.uuid4(),
        name=name,
        type=SourceType.pdf,
        status=status,
        review_status=review_status,
        chunk_count=10,
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    return src


class TestSourcesList:
    async def test_unauthenticated_request_rejected(self, client):
        r = await client.get("/api/v1/sources")
        assert r.status_code in (401, 403)

    async def test_empty_list_returns_array(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/sources", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_includes_existing_source(
        self, client, db_session, admin_user, auth_headers
    ):
        src = await _create_source(db_session)
        r = await client.get("/api/v1/sources", headers=auth_headers(admin_user))
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()]
        assert str(src.id) in ids


class TestSourceApprove:
    async def test_admin_can_approve_pending_source(
        self, client, db_session, admin_user, auth_headers
    ):
        src = await _create_source(db_session, review_status=ReviewStatus.pendiente_revision)
        r = await client.post(
            f"/api/v1/sources/{src.id}/approve", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["review_status"] == "aprobada"
        assert body["reviewed_at"] is not None
        assert body["reviewed_by_name"] == admin_user.full_name
        assert body["rejection_reason"] is None

    async def test_approve_overrides_previous_rejection(
        self, client, db_session, admin_user, auth_headers
    ):
        """Si una fuente fue rechazada, aprobarla limpia el rejection_reason."""
        src = await _create_source(db_session, review_status=ReviewStatus.rechazada)

        # Rechazada con razón previa
        await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={"reason": "Contenido obsoleto"},
            headers=auth_headers(admin_user),
        )

        r = await client.post(
            f"/api/v1/sources/{src.id}/approve", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["review_status"] == "aprobada"
        assert body["rejection_reason"] is None

    async def test_editor_cannot_approve(
        self, client, db_session, editor_user, auth_headers
    ):
        """El rol editor puede subir fuentes pero no aprobarlas."""
        src = await _create_source(db_session)
        r = await client.post(
            f"/api/v1/sources/{src.id}/approve", headers=auth_headers(editor_user)
        )
        assert r.status_code == 403

    async def test_viewer_cannot_approve(
        self, client, db_session, viewer_user, auth_headers
    ):
        src = await _create_source(db_session)
        r = await client.post(
            f"/api/v1/sources/{src.id}/approve", headers=auth_headers(viewer_user)
        )
        assert r.status_code == 403

    async def test_unauthenticated_rejected(self, client, db_session):
        src = await _create_source(db_session)
        r = await client.post(f"/api/v1/sources/{src.id}/approve")
        assert r.status_code in (401, 403)

    async def test_approve_nonexistent_source_returns_404(
        self, client, admin_user, auth_headers
    ):
        fake_id = uuid.uuid4()
        r = await client.post(
            f"/api/v1/sources/{fake_id}/approve", headers=auth_headers(admin_user)
        )
        assert r.status_code == 404


class TestSourceReject:
    async def test_admin_can_reject_with_reason(
        self, client, db_session, admin_user, auth_headers
    ):
        src = await _create_source(db_session)
        r = await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={"reason": "El documento contiene información incorrecta sobre las fechas"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["review_status"] == "rechazada"
        assert "información incorrecta" in body["rejection_reason"]
        assert body["reviewed_at"] is not None

    async def test_reject_without_reason_returns_422(
        self, client, db_session, admin_user, auth_headers
    ):
        src = await _create_source(db_session)
        r = await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={},  # missing required `reason`
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_reject_truncates_long_reason(
        self, client, db_session, admin_user, auth_headers
    ):
        """El backend trunca razones a 500 chars (rejection_reason column limit)."""
        src = await _create_source(db_session)
        long_reason = "x" * 1000
        r = await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={"reason": long_reason},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["rejection_reason"]) <= 500

    async def test_editor_cannot_reject(
        self, client, db_session, editor_user, auth_headers
    ):
        src = await _create_source(db_session)
        r = await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={"reason": "test"},
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_reject_nonexistent_source_returns_404(
        self, client, admin_user, auth_headers
    ):
        fake_id = uuid.uuid4()
        r = await client.post(
            f"/api/v1/sources/{fake_id}/reject",
            json={"reason": "test"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404


class TestApproveRejectAuditTrail:
    """Cada acción de revisión debe quedar registrada en audit_log."""

    async def test_approve_emits_audit_log(
        self, client, db_session, admin_user, auth_headers
    ):
        from sqlalchemy import select
        from app.models.audit_log import AuditLog

        src = await _create_source(db_session)
        await client.post(
            f"/api/v1/sources/{src.id}/approve", headers=auth_headers(admin_user)
        )

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "source.approve")
        )
        logs = list(result.scalars().all())
        assert len(logs) == 1
        assert logs[0].resource_id == str(src.id)
        assert logs[0].actor_id == admin_user.id

    async def test_reject_emits_audit_log_with_reason_meta(
        self, client, db_session, admin_user, auth_headers
    ):
        from sqlalchemy import select
        from app.models.audit_log import AuditLog

        src = await _create_source(db_session)
        await client.post(
            f"/api/v1/sources/{src.id}/reject",
            json={"reason": "smoke test"},
            headers=auth_headers(admin_user),
        )

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "source.reject")
        )
        logs = list(result.scalars().all())
        assert len(logs) == 1
        assert logs[0].meta_json.get("reason") == "smoke test"
