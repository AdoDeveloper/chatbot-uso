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
    """Devuelve el conjunto de point-ids de chunks que tienen al menos una edición registrada."""
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
        warnings=c.get("warnings") or [],
        is_discarded=bool(c.get("is_discarded", False)),
        was_edited=was_edited,
    )


async def list_source_chunks(
    db: AsyncSession, *, source_id: str, page: int, page_size: int, warning: str | None,
) -> ChunkListOut:
    """Lista los chunks de una fuente específica, paginados con el contrato
    estándar de la app page/page_size/total (misma forma que /conversations, /audit/logs).

    También devuelve un conteo agregado de warnings de toda la fuente para que
    el UI de revisión pueda mostrar "12 chunks necesitan atención" arriba.
    """
    all_chunks = await vector_store.list_all_chunks(source_id)

    counter: Counter[str] = Counter()
    for c in all_chunks:
        for w in (c.get("warnings") or []):
            counter[w] += 1

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
    """Obtiene un solo chunk por su point ID de Qdrant."""
    chunk = await vector_store.get_chunk(point_id)
    if not chunk:
        raise NotFoundError("Chunk no encontrado")

    # ¿Este chunk fue editado alguna vez?
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
    and an audit row is written. The edit applies immediately - chunks are
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

    # 1. Regenerar embedding
    try:
        [emb] = await embed_texts_async([new_text], prefix="passage: ")
    except Exception as exc:
        # Detalle a logs; la excepción cruda puede exponer rutas o hosts internos
        log.error("chunk.edit_embed_failed", point_id=point_id, error=str(exc))
        raise HTTPException(status_code=500, detail="No se pudo regenerar el embedding. Inténtelo de nuevo más tarde.")

    # 2. Recalcular warnings (usa el tamaño de chunk del .env para mantener consistencia con la ingesta)
    new_warnings = compute_warnings(new_text, get_env_settings().CHATBOT_CHUNK_PARENT_SIZE)

    # 3. Upsert de vuelta en Qdrant (mismo point_id = actualización)
    from qdrant_client.models import PointStruct, SparseVector
    client = vector_store._get_client()
    new_payload = dict(existing)
    # Descarta campos que Qdrant inserta por su cuenta (id) y los que sobrescribimos explícitamente
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

    # 4. Fila de auditoría
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

    # 5. Invalidar caché semántico (respuestas viejas pueden referenciar texto anterior)
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


async def set_discarded(db: AsyncSession, *, point_id: str, value: bool, user: User) -> ChunkOut:
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

    # Invalidar caché (los chunks descartados no deben aparecer)
    sid = existing.get("source_id")
    if sid:
        try:
            await cache_svc.invalidate_by_source(sid)
        except Exception as exc:
            log.warning("chunk.cache_invalidate_discard_failed", source_id=sid, error=str(exc))

    existing["is_discarded"] = value
    res = await db.execute(
        select(ChunkEdit.id).where(ChunkEdit.chunk_point_id == point_id).limit(1)
    )
    was_edited = res.first() is not None
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
        was_edited=was_edited,
    )


async def chunk_history(db: AsyncSession, *, point_id: str) -> list[ChunkEditOut]:
    """Lista las ediciones aplicadas a un chunk, más recientes primero."""
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
