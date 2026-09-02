from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.faq_entry import FAQEntry
from app.models.source import Source
from app.services.ai import semantic_cache as cache_svc
from app.services.ai.embedding import embed_texts_async
from app.services.ingestion import vector_store
from app.services.ingestion.chunking import chunk_text

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
        # chunk_text() no admite metadata custom, el payload insertado no trae is_active.
        if not is_active:
            await vector_store.set_source_active(source_id, is_active)
        try:
            await cache_svc.invalidate_by_source(source_id)
        except Exception as exc:
            log.warning("faq.cache_invalidate_failed", source_id=source_id, error=str(exc))
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
    active_changed = is_active is not None and is_active != entry.is_active
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
        re_embed_ok = await _re_embed_faq(entry)
        if not re_embed_ok:
            # El vector en Qdrant quedó desactualizado; se refleja el error en la Source.
            src = await db.get(Source, entry.source_id)
            if src:
                src.status = SourceStatus.error
                src.error_message = "No se pudo reindexar la FAQ tras la edición. Guarde de nuevo para reintentar."
    if active_changed and entry.source_id:
        # `if` independiente, no `elif`: debe ejecutar aunque también haya cambiado el texto.
        try:
            await vector_store.set_source_active(str(entry.source_id), entry.is_active)
        except Exception as exc:
            log.error("faq.set_active_failed", faq_id=str(entry.id), error=str(exc))

    if (changed or active_changed) and entry.source_id:
        # Invalida caché: puede haber respuestas citando texto o estado viejo de la FAQ.
        try:
            await cache_svc.invalidate_by_source(str(entry.source_id))
        except Exception as exc:
            log.warning("faq.cache_invalidate_failed", source_id=str(entry.source_id), error=str(exc))

    await db.flush()
    return entry


async def _re_embed_faq(entry: FAQEntry) -> bool:
    """Reindexar una FAQ en Qdrant tras editar su texto.

    Devuelve False si falla, en vez de solo loguear: sin eso, la FAQ quedaría
    "editada" en MySQL pero sin vector en Qdrant, y el bot no podría
    responder esa pregunta sin ningún error visible en el panel."""
    full_text = f"P: {entry.question}\nR: {entry.answer}"
    source_id = str(entry.source_id)
    try:
        await vector_store.delete_source(source_id)
        chunks = chunk_text(full_text, source_id=source_id, source_name=f"FAQ: {entry.question[:80]}")
        embeddings = await embed_texts_async([c["text"] for c in chunks], prefix="passage: ")
        await vector_store.upsert_chunks(chunks, embeddings)
        return True
    except Exception as exc:
        log.error("faq.re_embed_failed", faq_id=str(entry.id), error=str(exc))
        return False


async def delete_faq(db: AsyncSession, entry: FAQEntry) -> None:
    if entry.source_id:
        source_id = str(entry.source_id)
        try:
            await vector_store.delete_source(source_id)
            src = await db.get(Source, entry.source_id)
            if src:
                await db.delete(src)
        except Exception as exc:
            log.error("faq.delete_vector_failed", error=str(exc))
        try:
            await cache_svc.invalidate_by_source(source_id)
        except Exception as exc:
            log.warning("faq.cache_invalidate_failed", source_id=source_id, error=str(exc))
    await db.delete(entry)
    await db.flush()
