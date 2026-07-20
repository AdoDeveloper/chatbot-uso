from __future__ import annotations

import uuid
from functools import lru_cache

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
    Filter,
    FieldCondition,
    MatchAny,
    MatchValue,
    SparseVector,
)

from app.core.config import get_settings

log = structlog.get_logger()

COLLECTION = "chatbot_sources"
DENSE_DIM = 1024       # intfloat/multilingual-e5-large dense dimension (was 384 for MiniLM)
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"


@lru_cache(maxsize=1)
def _get_client() -> AsyncQdrantClient:
    settings = get_settings()
    return AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
    )


async def ensure_collection() -> None:
    """Crea la colección y sus payload indexes si no existen (idempotente)."""
    from qdrant_client.models import TextIndexParams, TokenizerType

    client = _get_client()
    existing = {c.name for c in (await client.get_collections()).collections}
    if COLLECTION not in existing:
        try:
            await client.create_collection(
                collection_name=COLLECTION,
                vectors_config={
                    DENSE_VECTOR: VectorParams(size=DENSE_DIM, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    SPARSE_VECTOR: SparseVectorParams(index=SparseIndexParams()),
                },
            )
            log.info("qdrant.collection_created", name=COLLECTION, dense_dim=DENSE_DIM)
        except Exception as exc:
            # 409 = race condition between workers, collection already created
            if "already exists" in str(exc):
                log.debug("qdrant.collection_already_exists", name=COLLECTION)
            else:
                raise

    try:
        await client.create_payload_index(
            collection_name=COLLECTION,
            field_name="text",
            field_schema=TextIndexParams(
                type="text",
                tokenizer=TokenizerType.MULTILINGUAL,
                lowercase=True,
                min_token_len=2,
                max_token_len=20,
            ),
        )
        log.info("qdrant.text_index_ensured", field="text", tokenizer="multilingual")
    except Exception as exc:
        # Index may already exist or server version may not support MULTILINGUAL
        log.debug("qdrant.text_index_skipped", reason=str(exc))

async def upsert_chunks(
    chunks: list[dict],
    embeddings: list[dict],
) -> int:
    """
    Inserta/actualiza puntos en Qdrant.
    chunks: salida de chunking.chunk_text
    embeddings: salida de embedding.embed_texts (misma longitud)
    """
    client = _get_client()
    points = []
    for chunk, emb in zip(chunks, embeddings):
        payload = {
            "text": chunk["text"],
            "source_id": chunk["source_id"],
            "source_name": chunk["source_name"],
            "chunk_index": chunk["chunk_index"],
            # Default review flags — admin can toggle is_discarded from the review UI
            "is_discarded": False,
        }
        if "section" in chunk:
            payload["section"] = chunk["section"]
        if "parent_id" in chunk:
            payload["parent_id"] = chunk["parent_id"]
        if "parent_text" in chunk:
            payload["parent_text"] = chunk["parent_text"]
        payload["warnings"] = chunk.get("warnings", [])

        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    DENSE_VECTOR: emb["dense"],
                    SPARSE_VECTOR: SparseVector(
                        indices=emb["sparse_indices"],
                        values=emb["sparse_values"],
                    ),
                },
                payload=payload,
            )
        )

    await client.upsert(collection_name=COLLECTION, points=points, wait=True)
    log.info("qdrant.upserted", count=len(points))
    return len(points)


ALL_CHUNKS_CAP = 2000


async def list_all_chunks(source_id: str) -> list[dict]:
    """Fetch every chunk for a source in one call, ordered by chunk_index.

    Used to compute numeric page/page_size/total pagination server-side
    without relying on Qdrant's opaque forward-only scroll cursor.
    """
    client = _get_client()
    source_filter = Filter(
        must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
    )
    result = await client.scroll(
        collection_name=COLLECTION,
        scroll_filter=source_filter,
        limit=ALL_CHUNKS_CAP,
        with_payload=True,
        with_vectors=False,
    )
    points, _ = result
    chunks = [{"id": str(p.id), **p.payload} for p in points]
    chunks.sort(key=lambda c: c.get("chunk_index", 0))
    return chunks


async def count_chunks(source_id: str) -> int:
    """Count total chunks for a source in Qdrant."""
    client = _get_client()
    source_filter = Filter(
        must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
    )
    result = await client.count(
        collection_name=COLLECTION,
        count_filter=source_filter,
        exact=True,
    )
    return result.count


async def get_chunk(point_id: str) -> dict | None:
    """Retrieve a single chunk by its Qdrant point ID."""
    client = _get_client()
    points = await client.retrieve(
        collection_name=COLLECTION,
        ids=[point_id],
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        return None
    p = points[0]
    return {"id": str(p.id), **p.payload}


async def delete_source(source_id: str) -> None:
    """Elimina todos los vectores asociados a un source_id."""
    client = _get_client()
    await client.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
        ),
    )
    log.info("qdrant.deleted_source", source_id=source_id)


async def hybrid_search(
    query_dense: list[float],
    query_sparse: dict,
    source_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float = 0.0,
) -> list[dict]:
    """
    Búsqueda híbrida (RRF sobre dense + sparse).
    Si se pasan source_ids, filtra solo esas fuentes.
    score_threshold: descarta chunks con score < threshold (0.0 = sin filtro).
    """
    from qdrant_client.models import Prefetch, FusionQuery, Fusion

    client = _get_client()

    if source_ids is not None and len(source_ids) == 0:
        return []

    must_conditions: list = []
    must_not: list = []
    if source_ids:
        must_conditions.append(
            FieldCondition(key="source_id", match=MatchAny(any=list(source_ids)))
        )
    # Never return chunks the admin manually discarded during review
    must_not.append(
        FieldCondition(key="is_discarded", match=MatchValue(value=True))
    )
    source_filter = Filter(must=must_conditions, must_not=must_not) if (must_conditions or must_not) else None

    prefetch_limit = max(top_k * 10, 100)

    fetch_limit = max(top_k * 5, 50) if not source_ids else top_k

    results = await client.query_points(
        collection_name=COLLECTION,
        prefetch=[
            Prefetch(query=query_dense, using=DENSE_VECTOR, limit=prefetch_limit),
            Prefetch(
                query=SparseVector(
                    indices=query_sparse["indices"],
                    values=query_sparse["values"],
                ),
                using=SPARSE_VECTOR,
                limit=prefetch_limit,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=fetch_limit,
        query_filter=source_filter,
        with_payload=True,
    )

    raw_docs = [{"score": p.score, **p.payload} for p in results.points]
    if score_threshold > 0.0:
        raw_docs = [d for d in raw_docs if d["score"] >= score_threshold]

    seen_parents: set[str] = set()
    deduped: list[dict] = []
    for d in raw_docs:
        pid = d.get("parent_id")
        if pid:
            if pid in seen_parents:
                continue
            seen_parents.add(pid)
        deduped.append(d)

    if not source_ids and len(deduped) > top_k:
        max_per_source = max(1, round(top_k * 0.6))
        diverse: list[dict] = []
        counts: dict[str, int] = {}
        overflow: list[dict] = []
        for d in deduped:
            sid = d.get("source_id", "")
            if counts.get(sid, 0) < max_per_source:
                diverse.append(d)
                counts[sid] = counts.get(sid, 0) + 1
            else:
                overflow.append(d)
        # Fill remaining slots with best leftover chunks (any source)
        remaining = top_k - len(diverse)
        if remaining > 0:
            diverse.extend(overflow[:remaining])
        docs = diverse[:top_k]
    else:
        docs = deduped[:top_k] if len(deduped) > top_k else deduped

    return docs
