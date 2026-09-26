from __future__ import annotations

import uuid

import pytest

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.faq_entry import FAQEntry
from app.models.source import Source
from app.services.knowledge import faq as faq_svc


@pytest.fixture
async def faq_entry(db_session):
    source = Source(
        name="FAQ: pregunta original",
        type=SourceType.faq,
        status=SourceStatus.ready,
        review_status=ReviewStatus.aprobada,
        chunk_count=1,
    )
    db_session.add(source)
    await db_session.flush()

    entry = FAQEntry(
        question="pregunta original",
        answer="respuesta original",
        tags=[],
        is_active=True,
        source_id=source.id,
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    return entry


class TestUpdateFaqReEmbedFailure:
    async def test_failed_reembed_marks_source_error_not_silent(
        self, db_session, faq_entry, monkeypatch,
    ):
        async def _fake_delete_source(source_id):
            return None

        async def _fake_embed_texts_async(texts, prefix=""):
            raise RuntimeError("embedding provider unavailable")

        monkeypatch.setattr(faq_svc.vector_store, "delete_source", _fake_delete_source)
        monkeypatch.setattr(faq_svc, "embed_texts_async", _fake_embed_texts_async)

        updated = await faq_svc.update_faq(
            db_session, faq_entry, question="pregunta editada",
        )
        await db_session.commit()

        assert updated.question == "pregunta editada"

        src = await db_session.get(Source, faq_entry.source_id)
        assert src.status == SourceStatus.error
        assert src.error_message

    async def test_successful_reembed_leaves_source_untouched(
        self, db_session, faq_entry, monkeypatch,
    ):
        async def _fake_delete_source(source_id):
            return None

        async def _fake_embed_texts_async(texts, prefix=""):
            return [[0.1] * 8 for _ in texts]

        async def _fake_upsert_chunks(chunks, embeddings):
            return len(chunks)

        async def _fake_delete_except(source_id, keep_ids):
            return None

        async def _fake_set_active(source_id, value):
            return None

        monkeypatch.setattr(faq_svc.vector_store, "delete_source", _fake_delete_source)
        monkeypatch.setattr(faq_svc.vector_store, "delete_source_except", _fake_delete_except)
        monkeypatch.setattr(faq_svc.vector_store, "set_source_active", _fake_set_active)
        monkeypatch.setattr(faq_svc, "embed_texts_async", _fake_embed_texts_async)
        monkeypatch.setattr(faq_svc.vector_store, "upsert_chunks", _fake_upsert_chunks)

        await faq_svc.update_faq(db_session, faq_entry, question="pregunta editada 2")
        await db_session.commit()

        src = await db_session.get(Source, faq_entry.source_id)
        assert src.status == SourceStatus.ready
        assert not src.error_message


async def test_editing_an_inactive_faq_keeps_it_out_of_the_chat(db_session, faq_entry, monkeypatch):
    calls: list[tuple] = []

    async def _embed(texts, prefix=""):
        return [[0.1] * 8 for _ in texts]

    async def _upsert(chunks, embeddings):
        calls.append(("upsert", len(chunks)))
        return len(chunks)

    async def _delete_except(source_id, keep_ids):
        calls.append(("delete_except", len(keep_ids)))

    async def _set_active(source_id, value):
        calls.append(("active", value))

    monkeypatch.setattr(faq_svc, "embed_texts_async", _embed)
    monkeypatch.setattr(faq_svc.vector_store, "upsert_chunks", _upsert)
    monkeypatch.setattr(faq_svc.vector_store, "delete_source_except", _delete_except)
    monkeypatch.setattr(faq_svc.vector_store, "set_source_active", _set_active)
    faq_entry.is_active = False

    await faq_svc.update_faq(db_session, faq_entry, answer="respuesta nueva")

    assert calls[0][0] == "upsert" and calls[1][0] == "delete_except"
    assert ("active", False) in calls


async def test_failed_reembed_keeps_the_previous_version(db_session, faq_entry, monkeypatch):
    deleted: list[str] = []

    async def _embed(texts, prefix=""):
        raise RuntimeError("sin servicio de embeddings")

    async def _delete_except(source_id, keep_ids):
        deleted.append(source_id)

    async def _delete_source(source_id):
        deleted.append(source_id)

    async def _set_active(source_id, value):
        return None

    monkeypatch.setattr(faq_svc, "embed_texts_async", _embed)
    monkeypatch.setattr(faq_svc.vector_store, "delete_source_except", _delete_except)
    monkeypatch.setattr(faq_svc.vector_store, "delete_source", _delete_source)
    monkeypatch.setattr(faq_svc.vector_store, "set_source_active", _set_active)

    await faq_svc.update_faq(db_session, faq_entry, answer="otra respuesta")

    assert deleted == []
