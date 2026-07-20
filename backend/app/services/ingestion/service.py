from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source
from app.core.config import get_settings as get_env_settings
from app.services.ingestion.chunking import chunk_text
from app.services.ingestion.chunk_warnings import compute_warnings
from app.services.ai.embedding import embed_texts_async
from app.services.ingestion.parsing import parse_source
from app.services.ai.semantic_cache import invalidate_by_source
from app.services.ingestion import vector_store

log = structlog.get_logger()

# Batch size para no saturar RAM con documentos grandes
_EMBED_BATCH = 16


async def _set_stage(db: AsyncSession, source: Source, stage: str) -> None:
    """Persiste la etapa de progreso actual para que el frontend la muestre."""
    source.progress_stage = stage
    source.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def ingest(db: AsyncSession, source: Source) -> None:
    """
    Pipeline completo:  parse → chunk → embed → upsert Qdrant → update DB
    Actualiza source.status y source.chunk_count en la DB.
    """
    source_id = str(source.id)
    log.info("ingestion.start", source_id=source_id, type=source.type, name=source.name)

    source.status = SourceStatus.processing
    source.review_status = ReviewStatus.procesando
    source.error_message = None
    source.progress_stage = "starting"
    await db.commit()

    try:
        if source.type == SourceType.faq:
            # FAQ sources: data already lives in faq_entries — one chunk per entry.
            await _set_stage(db, source, "parsing")
            from app.models.faq_entry import FAQEntry
            result = await db.execute(
                select(FAQEntry).where(
                    FAQEntry.source_id == source.id,
                    FAQEntry.deleted_at.is_(None),
                    FAQEntry.is_active.is_(True),
                )
            )
            entries = result.scalars().all()
            if not entries:
                raise ValueError("Esta fuente FAQ no tiene entradas activas para indexar")
            chunks = [
                {
                    "text": f"Pregunta: {e.question}\nRespuesta: {e.answer}",
                    "source_id": source_id,
                    "source_name": source.name,
                    "chunk_index": i,
                    "warnings": [],
                }
                for i, e in enumerate(entries)
            ]
        else:
            await _set_stage(db, source, "parsing")
            raw_text = await parse_source(source.type, source.file_path)
            if not raw_text.strip():
                raise ValueError("El documento no contiene texto extraíble")

            await _set_stage(db, source, "chunking")
            env = get_env_settings()
            chunks = chunk_text(
                raw_text,
                source_id=source_id,
                source_name=source.name,
                parent_size=env.CHATBOT_CHUNK_PARENT_SIZE,
                parent_overlap=env.CHATBOT_CHUNK_PARENT_OVERLAP,
                child_size=env.CHATBOT_CHUNK_CHILD_SIZE,
                child_overlap=env.CHATBOT_CHUNK_CHILD_OVERLAP,
            )

            for c in chunks:
                c["warnings"] = compute_warnings(c["text"], env.CHATBOT_CHUNK_PARENT_SIZE)

        await vector_store.ensure_collection()

        await _set_stage(db, source, "cleaning")
        await vector_store.delete_source(source_id)

        total_upserted = 0
        total_batches = (len(chunks) + _EMBED_BATCH - 1) // _EMBED_BATCH
        for batch_num, i in enumerate(range(0, len(chunks), _EMBED_BATCH), 1):
            await _set_stage(db, source, f"embedding:{batch_num}:{total_batches}")
            batch = chunks[i: i + _EMBED_BATCH]
            texts = [c["text"] for c in batch]
            embeddings = await embed_texts_async(texts, prefix="passage: ")
            total_upserted += await vector_store.upsert_chunks(batch, embeddings)

        source.status = SourceStatus.ready
        source.chunk_count = total_upserted
        source.progress_stage = None
        source.updated_at = datetime.now(timezone.utc)
        source.review_status = ReviewStatus.pendiente_revision
        await db.commit()

        await invalidate_by_source(source_id)

        log.info("ingestion.done", source_id=source_id, chunks=total_upserted)

        try:
            from app.models.enums import NotificationEvent
            from app.services.notifications.service import send_notification
            await send_notification(db, event=NotificationEvent.doc_ready, payload={
                "source_id": source_id,
                "source_name": source.name,
                "chunks": total_upserted,
            })
        except Exception as exc:
            log.debug("ingestion.notify_doc_ready_failed", source_id=source_id, error=str(exc))

    except Exception as exc:
        from app.services.ingestion.source_quality import classify_error
        raw = str(exc)[:1000]
        code, friendly, hint = classify_error(raw)
        log.error("ingestion.failed", source_id=source_id, error=raw, code=code)
        source.status = SourceStatus.error
        source.error_message = friendly or raw
        source.error_code = code
        source.error_hint = hint
        source.progress_stage = None
        source.updated_at = datetime.now(timezone.utc)
        await db.commit()

        # Notify admins of ingestion failure (best-effort)
        try:
            from app.models.enums import NotificationEvent
            from app.services.notifications.service import send_notification
            await send_notification(db, event=NotificationEvent.doc_error, payload={
                "source_id": source_id,
                "source_name": source.name,
                "error": str(exc)[:300],
            })
        except Exception as notify_exc:
            log.debug("ingestion.notify_doc_error_failed", source_id=source_id, error=str(notify_exc))
        raise
