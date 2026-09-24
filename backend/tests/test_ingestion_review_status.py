from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source
from app.services.ingestion import service as ingestion


@pytest.fixture
def _stub_pipeline(monkeypatch):
    monkeypatch.setattr(ingestion, "parse_source", AsyncMock(return_value="Art. 1.- Texto del reglamento."))
    monkeypatch.setattr(ingestion, "embed_texts_async", AsyncMock(side_effect=lambda texts, prefix: [{}] * len(texts)))
    monkeypatch.setattr(ingestion, "invalidate_by_source", AsyncMock())
    monkeypatch.setattr(ingestion.vector_store, "ensure_collection", AsyncMock())
    monkeypatch.setattr(ingestion.vector_store, "delete_source", AsyncMock())
    monkeypatch.setattr(ingestion.vector_store, "list_all_chunks", AsyncMock(return_value=[]))
    monkeypatch.setattr(ingestion.vector_store, "upsert_chunks", AsyncMock(side_effect=lambda batch, emb: len(batch)))


async def _ingest_with(db_session, review_status: ReviewStatus) -> Source:
    source = Source(
        id=uuid.uuid4(), name="Reglamento", type=SourceType.txt, file_path="/tmp/reglamento.txt",
        status=SourceStatus.pending, review_status=review_status,
    )
    db_session.add(source)
    await db_session.commit()
    await ingestion.ingest(db_session, source)
    await db_session.refresh(source)
    return source


@pytest.mark.usefixtures("_stub_pipeline")
class TestReviewStatusAfterIngest:
    async def test_reprocessing_approved_source_keeps_approval(self, db_session):
        source = await _ingest_with(db_session, ReviewStatus.aprobada)
        assert source.status == SourceStatus.ready
        assert source.review_status == ReviewStatus.aprobada

    async def test_new_source_waits_for_review(self, db_session):
        source = await _ingest_with(db_session, ReviewStatus.pendiente_revision)
        assert source.review_status == ReviewStatus.pendiente_revision

    async def test_rejected_source_goes_back_to_review(self, db_session):
        source = await _ingest_with(db_session, ReviewStatus.rechazada)
        assert source.review_status == ReviewStatus.pendiente_revision


class TestCarryReviewMarks:
    async def test_edits_and_discards_survive_reprocessing(self, db_session, monkeypatch):
        from app.models.chunk_edit import ChunkEdit

        source = Source(id=uuid.uuid4(), name="Doc", type=SourceType.txt, status=SourceStatus.ready,
                        review_status=ReviewStatus.aprobada)
        db_session.add(source)
        await db_session.commit()
        db_session.add(ChunkEdit(chunk_point_id="old-1", source_id=source.id,
                                 previous_content="[Sección: A]\nTexto original", new_content="Texto corregido"))
        await db_session.commit()
        monkeypatch.setattr(ingestion.vector_store, "list_all_chunks", AsyncMock(return_value=[
            {"id": "old-1", "text": "Texto corregido"},
            {"id": "old-2", "text": "[Sección: B]\nFragmento irrelevante", "is_discarded": True},
        ]))
        chunks = [
            {"text": "[Sección: A > A1]\nTexto original", "parent_text": "[Sección: A > A1]\nTexto original"},
            {"text": "[Sección: B]\nFragmento irrelevante"},
            {"text": "[Sección: C]\nNuevo"},
        ]

        repointed = await ingestion._carry_review_marks(db_session, str(source.id), chunks)

        assert chunks[0]["text"] == "Texto corregido"
        assert "Texto corregido" in chunks[0]["parent_text"]
        assert repointed == {"old-1": chunks[0]["point_id"]}
        assert chunks[1].get("is_discarded") is True
        assert not chunks[2].get("is_discarded")
