from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings as get_env_settings
from app.models.chunk_edit import ChunkEdit
from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source
from app.services.ai.embedding import embed_texts_async
from app.services.ai.semantic_cache import invalidate_by_source
from app.services.ingestion import vector_store
from app.services.ingestion.chunk_warnings import compute_warnings
from app.services.ingestion.chunking import chunk_text
from app.services.ingestion.parsing import parse_source

log = structlog.get_logger()

# Batch size para no saturar RAM con documentos grandes
_EMBED_BATCH = 16


class _SourceDeletedDuringIngestion(Exception):
    """Señal interna: el source fue borrado (soft-delete) mientras se ingería en background."""


async def _set_stage(db: AsyncSession, source: Source, stage: str) -> None:
    """Persiste la etapa de progreso actual para que el frontend la muestre."""
    source.progress_stage = stage
    source.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def _abort_if_deleted(db: AsyncSession, source_pk) -> None:
    """Releída best-effort de `deleted_at` para detectar si delete_source() corrió en paralelo."""
    result = await db.execute(select(Source.deleted_at).where(Source.id == source_pk))
    deleted_at = result.scalar_one_or_none()
    if deleted_at is not None:
        raise _SourceDeletedDuringIngestion()


_SECTION_PREFIX = re.compile(r"^\[Sección:.*?\]\n")


def _body(text: str) -> str:
    return _SECTION_PREFIX.sub("", text, count=1).strip()


async def _carry_review_marks(db: AsyncSession, source_id: str, chunks: list[dict]) -> dict[str, str]:
    """Reaplica ediciones y descartes del panel a los fragmentos nuevos con el mismo texto."""
    existing = await vector_store.list_all_chunks(source_id)
    if not existing:
        return {}
    rows = (await db.execute(
        select(ChunkEdit).where(ChunkEdit.source_id == uuid.UUID(source_id)).order_by(ChunkEdit.edited_at)
    )).scalars().all()
    original_by_point: dict[str, str] = {}
    for row in rows:
        original_by_point.setdefault(row.chunk_point_id, row.previous_content)

    edited: dict[str, tuple[str, str]] = {}
    discarded: set[str] = set()
    for point in existing:
        pid, text = point["id"], point.get("text", "")
        if pid in original_by_point:
            edited.setdefault(_body(original_by_point[pid]), (pid, text))
        if point.get("is_discarded"):
            discarded.add(_body(text))

    repointed: dict[str, str] = {}
    for chunk in chunks:
        match = edited.pop(_body(chunk["text"]), None)
        if match:
            old_pid, edited_text = match
            if chunk.get("parent_text"):
                chunk["parent_text"] = chunk["parent_text"].replace(_body(chunk["text"]), _body(edited_text), 1)
            chunk["text"] = edited_text
            chunk["point_id"] = str(uuid.uuid4())
            repointed[old_pid] = chunk["point_id"]
        if _body(chunk["text"]) in discarded:
            chunk["is_discarded"] = True
    return repointed


async def ingest(db: AsyncSession, source: Source) -> None:
    """Pipeline completo:  parse → chunk → embed → upsert Qdrant → update DB Actualiza source.status y source.chunk_count en la DB."""
    source_id = str(source.id)
    log.info("ingestion.start", source_id=source_id, type=source.type, name=source.name)

    was_approved = source.review_status == ReviewStatus.aprobada
    source.status = SourceStatus.processing
    source.review_status = ReviewStatus.procesando
    source.error_message = None
    source.progress_stage = "starting"
    await db.commit()

    try:
        if source.type == SourceType.faq:
            # Fuentes FAQ: los datos ya viven en faq_entries - un chunk por entrada.
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
        repointed = await _carry_review_marks(db, source_id, chunks)

        await _abort_if_deleted(db, source.id)
        await _set_stage(db, source, "cleaning")
        await vector_store.delete_source(source_id)

        total_upserted = 0
        total_batches = (len(chunks) + _EMBED_BATCH - 1) // _EMBED_BATCH
        for batch_num, i in enumerate(range(0, len(chunks), _EMBED_BATCH), 1):
            await _abort_if_deleted(db, source.id)
            await _set_stage(db, source, f"embedding:{batch_num}:{total_batches}")
            batch = chunks[i: i + _EMBED_BATCH]
            texts = [c["text"] for c in batch]
            embeddings = await embed_texts_async(texts, prefix="passage: ")
            total_upserted += await vector_store.upsert_chunks(batch, embeddings)

        await _abort_if_deleted(db, source.id)
        for old_pid, new_pid in repointed.items():
            await db.execute(
                update(ChunkEdit).where(ChunkEdit.chunk_point_id == old_pid).values(chunk_point_id=new_pid)
            )
        source.status = SourceStatus.ready
        source.chunk_count = total_upserted
        source.progress_stage = None
        source.updated_at = datetime.now(timezone.utc)
        source.review_status = ReviewStatus.aprobada if was_approved else ReviewStatus.pendiente_revision
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

    except _SourceDeletedDuringIngestion:
        # Source soft-deleted durante el background task: no es error, se limpia y termina.
        log.info("ingestion.aborted_source_deleted", source_id=source_id)
        try:
            await vector_store.delete_source(source_id)
        except Exception as exc:
            log.warning("ingestion.vector_cleanup_failed", source_id=source_id, error=str(exc))

    except Exception as exc:
        from app.services.ingestion.source_quality import classify_error
        raw = str(exc)[:1000]
        code, friendly, hint = classify_error(raw)
        log.error("ingestion.failed", source_id=source_id, error=raw, code=code)
        source.status = SourceStatus.error
        # El chunk_count parcial no representa el documento completo; se limpia lo indexado.
        source.chunk_count = 0
        try:
            await vector_store.delete_source(source_id)
        except Exception as vec_exc:
            log.warning("ingestion.vector_cleanup_failed", source_id=source_id, error=str(vec_exc))
        source.error_message = friendly or raw
        source.error_code = code
        source.error_hint = hint
        source.progress_stage = None
        source.updated_at = datetime.now(timezone.utc)
        await db.commit()

        # Notifica a los admins del fallo de ingesta (best-effort)
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
