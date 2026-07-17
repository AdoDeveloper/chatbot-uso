from __future__ import annotations

import uuid
from collections import Counter

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings as get_env_settings
from app.core.exceptions import NotFoundError
from app.models.chunk_edit import ChunkEdit
from app.models.source import Source
from app.models.user import User
from app.schemas.chunk import ChunkEditOut, ChunkListOut, ChunkOut
from app.services.ai import semantic_cache as cache_svc
from app.services.ai.embedding import embed_texts_async
from app.services.ingestion import vector_store
from app.services.ingestion.chunk_warnings import compute_warnings

log = structlog.get_logger()


async def _edited_point_ids(db: AsyncSession, source_id: str) -> set[str]:
    """Return the set of chunk point-ids that have at least one edit row."""
    res = await db.execute(
        select(ChunkEdit.chunk_point_id).where(ChunkEdit.source_id == uuid.UUID(source_id)).distinct()
    )
    return {row[0] for row in res.all()}


def _chunk_to_out(c: dict, *, was_edited: bool) -> ChunkOut:
    return ChunkOut(
        id=c["id"],
        text=c.get("text", ""),
        source_id=c.get("source_id", ""),
        source_name=c.get("source_name", ""),
        chunk_index=c.get("chunk_index", 0),
        section=c.get("section"),
        parent_id=c.get("parent_id"),
        parent_text=c.get("parent_text"),
        environment=c.get("environment"),
        warnings=c.get("warnings") or [],
        is_discarded=bool(c.get("is_discarded", False)),
        was_edited=was_edited,
    )


async def list_source_chunks(
    db: AsyncSession, *, source_id: str, page: int, page_size: int, warning: str | None,
) -> ChunkListOut:
    """List chunks for a specific source, paginated with the app-standard
    page/page_size/total contract (same shape as /conversations, /audit/logs).

    Also returns an aggregated count of warnings across the whole source so the
    review UI can show "12 chunks necesitan atención" at the top.
    """
    all_chunks = await vector_store.list_all_chunks(source_id)

    counter: Counter[str] = Counter()
    for c in all_chunks:
        for w in (c.get("warnings") or []):
            counter[w] += 1

    # Optional filter by a specific warning flag — applied before pagination
    # so `total` reflects the filtered count, matching every other list
    # endpoint's contract (total = count of the filtered set, not the whole source).
    if warning:
        all_chunks = [c for c in all_chunks if warning in (c.get("warnings") or [])]

    total = len(all_chunks)
    start = (page - 1) * page_size
    chunks = all_chunks[start : start + page_size]

    edited_ids = await _edited_point_ids(db, source_id)

    return ChunkListOut(
        chunks=[_chunk_to_out(c, was_edited=c["id"] in edited_ids) for c in chunks],
        total=total,
        page=page,
        page_size=page_size,
        warning_counts=dict(counter),
    )


async def get_chunk(db: AsyncSession, *, point_id: str) -> ChunkOut:
    """Get a single chunk by Qdrant point ID."""
    chunk = await vector_store.get_chunk(point_id)
    if not chunk:
        raise NotFoundError("Chunk no encontrado")

    # Has this chunk ever been edited?
    res = await db.execute(
        select(ChunkEdit.id).where(ChunkEdit.chunk_point_id == point_id).limit(1)
    )
    was_edited = res.first() is not None

    return _chunk_to_out(chunk, was_edited=was_edited)


async def edit_chunk(
    db: AsyncSession, *, point_id: str, new_text: str, reason: str | None, current_user: User,
) -> ChunkOut:
    """
    Edit a chunk's text. The embedding is regenerated, warnings are recomputed,
    and an audit row is written. The edit applies immediately — chunks are
    editable at any time, in any review state.

    Invalidates the semantic cache of the chunk's environment so stale answers
    referencing the previous text won't be served.
    """
    existing = await vector_store.get_chunk(point_id)
    if not existing:
        raise NotFoundError("Chunk no encontrado")

    previous_text = existing.get("text", "")
    new_text = new_text.strip()
    if new_text == previous_text.strip():
        # no-op: return the chunk as-is without re-embedding
        return await get_chunk(db, point_id=point_id)

    source_id_str = existing.get("source_id")
    if not source_id_str:
        raise HTTPException(status_code=500, detail="Chunk sin source_id en payload")

    source = await db.get(Source, uuid.UUID(source_id_str))
    if not source:
        raise NotFoundError("La fuente del chunk ya no existe")

    # 1. Re-embed
    try:
        [emb] = await embed_texts_async([new_text], prefix="passage: ")
    except Exception as exc:
        # Detalle a logs; la excepción cruda puede exponer rutas o hosts internos
        log.error("chunk.edit_embed_failed", point_id=point_id, error=str(exc))
        raise HTTPException(status_code=500, detail="No se pudo regenerar el embedding. Inténtelo de nuevo más tarde.")

    # 2. Recompute warnings (use .env chunk size to stay consistent with ingestion)
    new_warnings = compute_warnings(new_text, get_env_settings().CHATBOT_CHUNK_PARENT_SIZE)

    # 3. Upsert back into Qdrant (same point_id = update)
    from qdrant_client.models import PointStruct, SparseVector
    client = vector_store._get_client()
    new_payload = dict(existing)
    # Drop fields that Qdrant inserts for us (id) and that we're explicitly overwriting
    new_payload.pop("id", None)
    new_payload["text"] = new_text
    new_payload["warnings"] = new_warnings
    await client.upsert(
        collection_name=vector_store.COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector={
                    vector_store.DENSE_VECTOR: emb["dense"],
                    vector_store.SPARSE_VECTOR: SparseVector(
                        indices=emb["sparse_indices"],
                        values=emb["sparse_values"],
                    ),
                },
                payload=new_payload,
            )
        ],
        wait=True,
    )

    # 4. Audit row
    edit = ChunkEdit(
        chunk_point_id=point_id,
        source_id=source.id,
        previous_content=previous_text,
        new_content=new_text,
        edited_by_id=current_user.id,
        reason=reason,
    )
    db.add(edit)
    await db.commit()

    # 5. Invalidate semantic cache (old answers may reference old text)
    try:
        await cache_svc.invalidate_by_source(source_id_str)
    except Exception as exc:
        log.warning("chunk.cache_invalidate_failed", source_id=source_id_str, error=str(exc))

    log.info(
        "chunk.edit",
        point_id=point_id,
        source_id=source_id_str,
        by=str(current_user.id),
        new_warnings=new_warnings,
    )

    return ChunkOut(
        id=point_id,
        text=new_text,
        source_id=source_id_str,
        source_name=existing.get("source_name", ""),
        chunk_index=existing.get("chunk_index", 0),
        section=existing.get("section"),
        parent_id=existing.get("parent_id"),
        parent_text=existing.get("parent_text"),
        warnings=new_warnings,
        is_discarded=bool(existing.get("is_discarded", False)),
        was_edited=True,
    )


async def set_discarded(*, point_id: str, value: bool, user: User) -> ChunkOut:
    existing = await vector_store.get_chunk(point_id)
    if not existing:
        raise NotFoundError("Chunk no encontrado")

    client = vector_store._get_client()
    await client.set_payload(
        collection_name=vector_store.COLLECTION,
        payload={"is_discarded": value},
        points=[point_id],
    )

    log.info(
        "chunk.set_discarded",
        point_id=point_id,
        source_id=existing.get("source_id"),
        value=value,
        by=str(user.id),
    )

    # Invalidate cache (discarded chunks must not appear)
    sid = existing.get("source_id")
    if sid:
        try:
            await cache_svc.invalidate_by_source(sid)
        except Exception as exc:
            log.warning("chunk.cache_invalidate_discard_failed", source_id=sid, error=str(exc))

    existing["is_discarded"] = value
    return ChunkOut(
        id=point_id,
        text=existing.get("text", ""),
        source_id=existing.get("source_id", ""),
        source_name=existing.get("source_name", ""),
        chunk_index=existing.get("chunk_index", 0),
        section=existing.get("section"),
        parent_id=existing.get("parent_id"),
        parent_text=existing.get("parent_text"),
        warnings=existing.get("warnings") or [],
        is_discarded=value,
        was_edited=False,  # no query here; safe default — call /chunks/:id for fresh data
    )


async def chunk_history(db: AsyncSession, *, point_id: str) -> list[ChunkEditOut]:
    """List edits applied to a chunk, newest first."""
    res = await db.execute(
        select(ChunkEdit)
        .where(ChunkEdit.chunk_point_id == point_id)
        .options(selectinload(ChunkEdit.edited_by))
        .order_by(ChunkEdit.edited_at.desc())
    )
    return [
        ChunkEditOut(
            id=str(e.id),
            chunk_point_id=e.chunk_point_id,
            previous_content=e.previous_content,
            new_content=e.new_content,
            edited_by_name=e.edited_by.full_name if e.edited_by else None,
            reason=e.reason,
            edited_at=e.edited_at,
        )
        for e in res.scalars().all()
    ]
