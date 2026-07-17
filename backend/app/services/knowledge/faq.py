from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.faq_entry import FAQEntry
from app.models.source import Source
from app.services.ingestion import vector_store
from app.services.ingestion.chunking import chunk_text
from app.services.ai.embedding import embed_texts_async

log = structlog.get_logger()


async def list_faqs(db: AsyncSession) -> list[FAQEntry]:
    result = await db.execute(select(FAQEntry).order_by(FAQEntry.created_at.desc()))
    return list(result.scalars().all())


async def get_faq(db: AsyncSession, faq_id: uuid.UUID) -> FAQEntry | None:
    result = await db.execute(select(FAQEntry).where(FAQEntry.id == faq_id))
    return result.scalar_one_or_none()


async def create_faq(
    db: AsyncSession,
    *,
    question: str,
    answer: str,
    tags: list[str] | None = None,
    is_active: bool = True,
    created_by_id: uuid.UUID | None = None,
) -> FAQEntry:
    full_text = f"P: {question}\nR: {answer}"
    source = Source(
        name=f"FAQ: {question[:80]}",
        type=SourceType.faq,
        status=SourceStatus.processing,
        review_status=ReviewStatus.aprobada,
        reviewed_by_id=created_by_id,
        created_by_id=created_by_id,
    )
    db.add(source)
    await db.flush()

    entry = FAQEntry(
        question=question,
        answer=answer,
        tags=tags or [],
        is_active=is_active,
        source_id=source.id,
        created_by_id=created_by_id,
    )
    db.add(entry)

    try:
        await vector_store.ensure_collection()
        source_id = str(source.id)
        chunks = chunk_text(full_text, source_id=source_id, source_name=source.name)
        embeddings = await embed_texts_async([c["text"] for c in chunks], prefix="passage: ")
        count = await vector_store.upsert_chunks(chunks, embeddings)
        source.status = SourceStatus.ready
        source.chunk_count = count
    except Exception as exc:
        log.error("faq.embed_failed", error=str(exc))
        source.status = SourceStatus.error
        source.error_message = str(exc)[:500]

    await db.flush()
    return entry


async def update_faq(
    db: AsyncSession,
    entry: FAQEntry,
    *,
    question: str | None = None,
    answer: str | None = None,
    tags: list[str] | None = None,
    is_active: bool | None = None,
) -> FAQEntry:
    changed = False
    if question is not None and question != entry.question:
        entry.question = question
        changed = True
    if answer is not None and answer != entry.answer:
        entry.answer = answer
        changed = True
    if tags is not None:
        entry.tags = tags
    if is_active is not None:
        entry.is_active = is_active
    entry.updated_at = datetime.now(timezone.utc)

    if changed and entry.source_id:
        await _re_embed_faq(entry)

    await db.flush()
    return entry


async def _re_embed_faq(entry: FAQEntry) -> None:
    full_text = f"P: {entry.question}\nR: {entry.answer}"
    source_id = str(entry.source_id)
    try:
        await vector_store.delete_source(source_id)
        chunks = chunk_text(full_text, source_id=source_id, source_name=f"FAQ: {entry.question[:80]}")
        embeddings = await embed_texts_async([c["text"] for c in chunks], prefix="passage: ")
        await vector_store.upsert_chunks(chunks, embeddings)
    except Exception as exc:
        log.error("faq.re_embed_failed", faq_id=str(entry.id), error=str(exc))


async def delete_faq(db: AsyncSession, entry: FAQEntry) -> None:
    if entry.source_id:
        try:
            await vector_store.delete_source(str(entry.source_id))
            src = await db.get(Source, entry.source_id)
            if src:
                await db.delete(src)
        except Exception as exc:
            log.error("faq.delete_vector_failed", error=str(exc))
    await db.delete(entry)
    await db.flush()
