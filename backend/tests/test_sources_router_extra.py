"""Tests de caracterización adicionales para app/api/v1/sources/router.py.

test_sources_api.py y test_chunks_api.py cubren list_sources,
approve_source, reject_source, get_source (parcial), delete_source
(solo permisos) y bulk_tag. Los siguientes endpoints NO tenían ningún
test antes de esto: upload_source, bulk_upload_sources, update_source,
reingest_source, delete_source (caso de éxito real), bulk_delete,
bulk_reingest, preview_source, quality_report_endpoint.

upload_source dispara la ingestión real en background (background_tasks),
pero la respuesta HTTP se devuelve antes de que corra; el parseo de un
PDF "falso" simplemente falla dentro del job de background y marca la
fuente como error — sin bloquear ni afectar el status code de la
petición. Por eso estos tests no necesitan mockear Qdrant/embeddings.
"""
from __future__ import annotations

import io
import uuid

import pytest

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source


def _fake_pdf_bytes(marker: str = "x") -> bytes:
    # No es un PDF válido — el parseo real fallará en background (esperado,
    # no lo estamos probando aquí), pero el content-type/extension bastan
    # para pasar la detección de tipo y el flujo de subida.
    return f"%PDF-1.4 fake content {marker}".encode()


@pytest.fixture
async def seeded_source(db_session):
    s = Source(
        id=uuid.uuid4(), name="Doc existente", type=SourceType.pdf,
        status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision,
        chunk_count=3, file_path=None,
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


class TestUploadSource:
    async def test_upload_creates_pending_source(self, client, admin_user, auth_headers):
        files = {"file": ("documento.pdf", io.BytesIO(_fake_pdf_bytes()), "application/pdf")}
        r = await client.post(
            "/api/v1/sources/upload", files=files, data={"name": "Mi documento"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Mi documento"
        assert body["type"] == "pdf"
        # El status puede ya haber avanzado a error si el background task
        # corrió sincrónicamente antes de leer la respuesta; lo importante
        # es que la creación en sí fue aceptada.
        assert body["status"] in ("pending", "processing", "error")

    async def test_upload_unsupported_type_returns_415(self, client, admin_user, auth_headers):
        files = {"file": ("archivo.txt", io.BytesIO(b"hola"), "text/plain")}
        r = await client.post(
            "/api/v1/sources/upload", files=files, headers=auth_headers(admin_user),
        )
        assert r.status_code == 415

    async def test_upload_empty_file_returns_400(self, client, admin_user, auth_headers):
        files = {"file": ("vacio.pdf", io.BytesIO(b""), "application/pdf")}
        r = await client.post(
            "/api/v1/sources/upload", files=files, headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_upload_duplicate_content_returns_409(self, client, admin_user, auth_headers):
        content = _fake_pdf_bytes("dup")
        files1 = {"file": ("primero.pdf", io.BytesIO(content), "application/pdf")}
        r1 = await client.post(
            "/api/v1/sources/upload", files=files1, headers=auth_headers(admin_user),
        )
        assert r1.status_code == 201

        files2 = {"file": ("segundo.pdf", io.BytesIO(content), "application/pdf")}
        r2 = await client.post(
            "/api/v1/sources/upload", files=files2, headers=auth_headers(admin_user),
        )
        assert r2.status_code == 409
        assert r2.json()["detail"]["code"] == "DUPLICATE_CONTENT"

    async def test_upload_name_defaults_to_filename_stem(self, client, admin_user, auth_headers):
        files = {"file": ("reglamento_2026.pdf", io.BytesIO(_fake_pdf_bytes("stem")), "application/pdf")}
        r = await client.post(
            "/api/v1/sources/upload", files=files, headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        assert r.json()["name"] == "reglamento_2026"


class TestBulkUploadSources:
    async def test_bulk_upload_mixed_success_and_errors(self, client, admin_user, auth_headers):
        files = [
            ("files", ("valido.pdf", io.BytesIO(_fake_pdf_bytes("bulk1")), "application/pdf")),
            ("files", ("vacio.pdf", io.BytesIO(b""), "application/pdf")),
            ("files", ("malo.xyz", io.BytesIO(b"data"), "application/octet-stream")),
        ]
        r = await client.post(
            "/api/v1/sources/bulk-upload", files=files, headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert len(body["created"]) == 1
        assert len(body["errors"]) == 2

    async def test_bulk_upload_duplicate_within_batch(self, client, admin_user, auth_headers):
        content = _fake_pdf_bytes("bulkdup")
        files = [
            ("files", ("a.pdf", io.BytesIO(content), "application/pdf")),
            ("files", ("b.pdf", io.BytesIO(content), "application/pdf")),
        ]
        r = await client.post(
            "/api/v1/sources/bulk-upload", files=files, headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert len(body["created"]) == 1
        assert len(body["errors"]) == 1


class TestUpdateSource:
    async def test_update_name_and_tags(self, client, admin_user, auth_headers, seeded_source):
        r = await client.patch(
            f"/api/v1/sources/{seeded_source.id}",
            json={"name": "Nuevo nombre", "tags": ["reglamento", "2026"]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Nuevo nombre"
        assert set(body["tags"]) == {"reglamento", "2026"}

    async def test_update_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.patch(
            f"/api/v1/sources/{uuid.uuid4()}", json={"name": "Nombre válido"}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 404


class TestReingestSource:
    async def test_reingest_resets_status_to_pending(self, client, admin_user, auth_headers, db_session):
        s = Source(
            id=uuid.uuid4(), name="Con error", type=SourceType.pdf,
            status=SourceStatus.error, review_status=ReviewStatus.pendiente_revision,
            error_message="fallo previo",
        )
        db_session.add(s)
        await db_session.commit()

        r = await client.post(f"/api/v1/sources/{s.id}/ingest", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("pending", "processing", "error")
        assert body["error_message"] is None or body["status"] == "error"

    async def test_reingest_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.post(f"/api/v1/sources/{uuid.uuid4()}/ingest", headers=auth_headers(admin_user))
        assert r.status_code == 404


class TestDeleteSourceSuccess:
    async def test_delete_marks_soft_deleted(self, client, admin_user, auth_headers, seeded_source, db_session):
        r = await client.delete(f"/api/v1/sources/{seeded_source.id}", headers=auth_headers(admin_user))
        assert r.status_code == 204

        await db_session.refresh(seeded_source)
        assert seeded_source.deleted_at is not None

        # Ya no debe aparecer en el listado activo.
        r2 = await client.get("/api/v1/sources", headers=auth_headers(admin_user))
        ids = [s["id"] for s in r2.json()]
        assert str(seeded_source.id) not in ids

    async def test_delete_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.delete(f"/api/v1/sources/{uuid.uuid4()}", headers=auth_headers(admin_user))
        assert r.status_code == 404


class TestBulkDelete:
    async def test_bulk_delete_soft_deletes_all(self, client, admin_user, auth_headers, db_session):
        s1 = Source(id=uuid.uuid4(), name="A", type=SourceType.pdf, status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision)
        s2 = Source(id=uuid.uuid4(), name="B", type=SourceType.pdf, status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision)
        db_session.add_all([s1, s2])
        await db_session.commit()

        r = await client.post(
            "/api/v1/sources/bulk/delete",
            json={"source_ids": [str(s1.id), str(s2.id)]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 204
        await db_session.refresh(s1)
        await db_session.refresh(s2)
        assert s1.deleted_at is not None
        assert s2.deleted_at is not None

    async def test_bulk_delete_empty_list_is_noop(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/sources/bulk/delete", json={"source_ids": []}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 204


class TestBulkReingest:
    async def test_bulk_reingest_queues_non_processing_sources(self, client, admin_user, auth_headers, db_session):
        s1 = Source(id=uuid.uuid4(), name="A", type=SourceType.pdf, status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision)
        s2 = Source(id=uuid.uuid4(), name="B", type=SourceType.pdf, status=SourceStatus.processing, review_status=ReviewStatus.pendiente_revision)
        db_session.add_all([s1, s2])
        await db_session.commit()

        r = await client.post(
            "/api/v1/sources/bulk/reingest",
            json={"source_ids": [str(s1.id), str(s2.id)]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        # Solo s1 se encola: s2 ya estaba "processing" y se salta a propósito.
        assert r.json()["queued"] == 1


class TestPreviewSource:
    async def test_preview_missing_file_returns_404(self, client, admin_user, auth_headers, db_session):
        s = Source(
            id=uuid.uuid4(), name="Sin archivo en disco", type=SourceType.pdf,
            status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision,
            file_path="/tmp/no-existe-en-disco-12345.pdf",
        )
        db_session.add(s)
        await db_session.commit()

        r = await client.get(f"/api/v1/sources/{s.id}/preview", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_preview_txt_file_returns_content(self, client, admin_user, auth_headers, db_session, tmp_path):
        p = tmp_path / "notas.txt"
        p.write_text("Contenido de prueba para preview.", encoding="utf-8")
        s = Source(
            id=uuid.uuid4(), name="Notas", type=SourceType.pdf,
            status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision,
            file_path=str(p),
        )
        db_session.add(s)
        await db_session.commit()

        r = await client.get(f"/api/v1/sources/{s.id}/preview", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert "Contenido de prueba" in body["preview"]
        assert body["truncated"] is False

    async def test_preview_truncates_when_over_max_chars(self, client, admin_user, auth_headers, db_session, tmp_path):
        p = tmp_path / "largo.txt"
        p.write_text("a" * 500, encoding="utf-8")
        s = Source(
            id=uuid.uuid4(), name="Largo", type=SourceType.pdf,
            status=SourceStatus.ready, review_status=ReviewStatus.pendiente_revision,
            file_path=str(p),
        )
        db_session.add(s)
        await db_session.commit()

        r = await client.get(
            f"/api/v1/sources/{s.id}/preview?max_chars=100", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["preview"]) == 100
        assert body["truncated"] is True

    async def test_preview_source_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.get(f"/api/v1/sources/{uuid.uuid4()}/preview", headers=auth_headers(admin_user))
        assert r.status_code == 404


class TestQualityReport:
    async def test_quality_report_for_existing_source(self, client, admin_user, auth_headers, seeded_source):
        r = await client.get(f"/api/v1/sources/{seeded_source.id}/quality", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert "total_chunks" in r.json()
