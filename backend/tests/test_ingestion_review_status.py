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
