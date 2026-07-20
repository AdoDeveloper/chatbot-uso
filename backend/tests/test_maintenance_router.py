"""Tests de caracterización para app/api/v1/maintenance/router.py.

Ningún archivo de test cubría sync_qdrant ni purge_health_outliers antes
de esto. Se fijan aquí antes de mover sync_qdrant a servicio. Qdrant se
sustituye por un stub — no hay Qdrant real en el entorno de test.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import ReviewStatus, SourceStatus, SourceType, UserRole
from app.models.health_snapshot import HealthSnapshot
from app.models.source import Source


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


@pytest.fixture
def patch_qdrant_scroll_and_delete(monkeypatch):
    """Stub del cliente Qdrant usado por sync_qdrant: scroll devuelve puntos
    fijos (uno válido, uno huérfano), count/delete registran llamadas."""
    import app.services.ingestion.qdrant_sync as qdrant_sync_svc

    calls = {"deleted_filter": None, "count_called": False}

    class _FakePoint:
        def __init__(self, source_id):
            self.payload = {"source_id": source_id}

    class _FakeClient:
        async def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
            if offset is not None:
                return [], None
            points = [_FakePoint(str(calls["valid_source_id"])), _FakePoint("orphan-source-id")]
            return points, None

        async def count(self, *, collection_name, count_filter, exact):
            calls["count_called"] = True
            class _R:
                count = 1
            return _R()

        async def delete(self, *, collection_name, points_selector):
            calls["deleted_filter"] = points_selector

    fake_client = _FakeClient()
    monkeypatch.setattr(qdrant_sync_svc, "_get_client", lambda: fake_client)

    async def _invalidate_by_source(source_id):
        return 3
    monkeypatch.setattr(qdrant_sync_svc.cache_svc, "invalidate_by_source", _invalidate_by_source)

    return calls


class TestSyncQdrant:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/maintenance/sync-qdrant")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/maintenance/sync-qdrant", headers=auth_headers(viewer_user)
        )
        assert r.status_code == 403

    async def test_sync_qdrant_deletes_orphans(
        self, client, admin_user, auth_headers, patch_qdrant_scroll_and_delete, db_session
    ):
        source = Source(
            id=uuid.uuid4(), name="Doc válido", type=SourceType.pdf,
            status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision, chunk_count=1,
        )
        db_session.add(source)
        await db_session.commit()
        patch_qdrant_scroll_and_delete["valid_source_id"] = source.id

        r = await client.post("/api/v1/maintenance/sync-qdrant", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["qdrant_chunks_total"] == 2
        assert body["valid_source_ids"] == 1
        assert body["orphan_chunks_deleted"] == 1
        assert body["cache_invalidated_count"] == 3
        assert patch_qdrant_scroll_and_delete["deleted_filter"] is not None

    async def test_sync_qdrant_no_orphans_skips_delete(
        self, client, admin_user, auth_headers, monkeypatch, db_session
    ):
        # Único source_id del scroll y también el único válido -> sin huérfanos.
        s1 = Source(id=uuid.uuid4(), name="A", type=SourceType.pdf, status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision)
        db_session.add(s1)
        await db_session.commit()

        import app.services.ingestion.qdrant_sync as qdrant_sync_svc

        class _FakePoint:
            def __init__(self, source_id):
                self.payload = {"source_id": source_id}

        class _FakeClientNoOrphans:
            async def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
                if offset is not None:
                    return [], None
                return [_FakePoint(str(s1.id))], None

            async def count(self, *, collection_name, count_filter, exact):
                raise AssertionError("count no debe llamarse si no hay huérfanos")

            async def delete(self, *, collection_name, points_selector):
                raise AssertionError("delete no debe llamarse si no hay huérfanos")

        monkeypatch.setattr(qdrant_sync_svc, "_get_client", lambda: _FakeClientNoOrphans())

        async def _invalidate_by_source(source_id):
            return 0
        monkeypatch.setattr(qdrant_sync_svc.cache_svc, "invalidate_by_source", _invalidate_by_source)

        r = await client.post("/api/v1/maintenance/sync-qdrant", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["orphan_chunks_deleted"] == 0


class TestPurgeHealthOutliers:
    async def test_requires_auth(self, client):
        r = await client.delete("/api/v1/maintenance/health-snapshots/outliers")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.delete(
            "/api/v1/maintenance/health-snapshots/outliers",
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_purge_deletes_only_above_threshold(self, client, admin_user, auth_headers, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            HealthSnapshot(id=uuid.uuid4(), service_name="qdrant", is_ok=True, latency_ms=100, recorded_at=now),
            HealthSnapshot(id=uuid.uuid4(), service_name="mysql", is_ok=True, latency_ms=2500, recorded_at=now),
            HealthSnapshot(id=uuid.uuid4(), service_name="redis", is_ok=True, latency_ms=1999, recorded_at=now),
        ])
        await db_session.commit()

        r = await client.delete("/api/v1/maintenance/health-snapshots/outliers", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 1
        assert body["threshold_ms"] == 2000

    async def test_purge_no_outliers(self, client, admin_user, auth_headers, db_session):
        db_session.add(HealthSnapshot(
            id=uuid.uuid4(), service_name="qdrant", is_ok=True, latency_ms=50,
            recorded_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        r = await client.delete("/api/v1/maintenance/health-snapshots/outliers", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["deleted"] == 0
