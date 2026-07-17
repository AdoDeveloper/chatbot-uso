from __future__ import annotations

import structlog
from qdrant_client.models import FieldCondition, Filter, MatchAny
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.services.ai import semantic_cache as cache_svc
from app.services.ingestion.vector_store import COLLECTION, _get_client

log = structlog.get_logger()


async def sync_qdrant(db: AsyncSession) -> dict:
    """Limpia chunks huérfanos en Qdrant (source_id sin fuente activa en MySQL)."""
    # 1. Source IDs válidos (en MySQL y NO soft-deleted)
    result = await db.execute(
        select(Source.id).where(Source.deleted_at.is_(None))
    )
    valid_source_ids = {str(row[0]) for row in result.all()}

    # 2. Source IDs presentes en Qdrant (scroll a través de toda la colección)
    client = _get_client()
    qdrant_source_ids: set[str] = set()
    total_chunks = 0
    offset = None
    while True:
        scroll_result = await client.scroll(
            collection_name=COLLECTION,
            limit=200,
            offset=offset,
            with_payload=["source_id"],
            with_vectors=False,
        )
        points, next_offset = scroll_result
        for p in points:
            sid = p.payload.get("source_id") if p.payload else None
            if sid:
                qdrant_source_ids.add(sid)
                total_chunks += 1
        if next_offset is None:
            break
        offset = next_offset

    # 3. Source IDs huérfanos = en Qdrant pero NO en MySQL
    orphan_ids = qdrant_source_ids - valid_source_ids

    # 4. Borrar todos los puntos con esos source_ids
    deleted = 0
    if orphan_ids:
        orphan_filter = Filter(
            must=[FieldCondition(
                key="source_id",
                match=MatchAny(any=list(orphan_ids)),
            )]
        )
        # Contar ANTES de borrar para un delta exacto e independiente de
        # escrituras concurrentes sobre otros source_ids.
        pre_count = await client.count(
            collection_name=COLLECTION,
            count_filter=orphan_filter,
            exact=True,
        )
        deleted = pre_count.count
        await client.delete(
            collection_name=COLLECTION,
            points_selector=orphan_filter,
        )

    # 5. Invalidar caché — respuestas viejas pueden citar chunks huérfanos
    cache_count = await cache_svc.invalidate_by_source("maintenance.sync-qdrant")

    log.info(
        "maintenance.sync_qdrant",
        total_chunks=total_chunks,
        valid_sources=len(valid_source_ids),
        orphan_sources=len(orphan_ids),
        orphan_chunks_deleted=deleted,
        cache_invalidated=cache_count,
    )

    return {
        "qdrant_chunks_total": total_chunks,
        "valid_source_ids": len(valid_source_ids),
        "orphan_chunks_deleted": deleted,
        "cache_invalidated_count": cache_count,
    }
