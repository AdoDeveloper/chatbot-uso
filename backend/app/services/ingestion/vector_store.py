from __future__ import annotations

import uuid
from functools import lru_cache

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Rrf,
    RrfQuery,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import get_settings

log = structlog.get_logger()

COLLECTION = "chatbot_sources"
DENSE_DIM = 1024       # intfloat/multilingual-e5-large dense dimension
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
            # 409 = colección ya creada por otra instancia del backend (carrera al arrancar)
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
        # El índice puede ya existir, o la versión del servidor puede no soportar MULTILINGUAL
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
            # Flags de revisión por defecto: el admin puede alternar is_discarded desde el UI de revisión
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
    """Trae todos los chunks de una fuente en una sola llamada, ordenados por chunk_index.

    Se usa para calcular la paginación numérica page/page_size/total en el
    servidor sin depender del cursor de scroll opaco y solo-adelante de Qdrant.
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


async def set_source_active(source_id: str, value: bool) -> None:
    """Marca is_active=value en todos los puntos de una fuente (FAQ).

    Usado por faq.update_faq() para propagar el toggle "Activo/Inactivo" del
    panel a Qdrant sin necesidad de re-embeber: sin esto, hybrid_search()
    sigue devolviendo (y el bot sigue citando) una FAQ marcada inactiva.
    """
    client = _get_client()
    source_filter = Filter(
        must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
    )
    await client.set_payload(
        collection_name=COLLECTION,
        payload={"is_active": value},
        points=source_filter,
    )


async def count_chunks(source_id: str) -> int:
    """Cuenta el total de chunks de una fuente en Qdrant."""
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
    try:
        points = await client.retrieve(
            collection_name=COLLECTION,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
    except UnexpectedResponse as exc:
        # Qdrant exige que el id sea UUID o entero; con cualquier otro
        # formato responde 400 y el cliente lo propaga como excepción en
        # vez de una lista vacía - sin este catch, un point_id mal formado
        # (ej. "1" a secas, o cualquier string no-UUID) tumbaba el endpoint
        # con un 500 genérico en vez de un 404 limpio.
        log.warning("qdrant.get_chunk_invalid_id", point_id=point_id, error=str(exc))
        return None
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


async def get_source_info() -> tuple[set[str], dict[str, int]]:
    """Retorna (source_ids, source_id->chunk_count) de todos los puntos en Qdrant."""
    client = _get_client()
    ids: set[str] = set()
    counts: dict[str, int] = {}
    offset: str | None = None
    while True:
        result = await client.scroll(
            collection_name=COLLECTION,
            limit=200,
            offset=offset,
            with_payload=["source_id"],
            with_vectors=False,
        )
        points, next_offset = result
        for p in points:
            if p.payload and "source_id" in p.payload:
                sid = p.payload["source_id"]
                ids.add(sid)
                counts[sid] = counts.get(sid, 0) + 1
        if next_offset is None:
            break
        offset = next_offset
    return ids, counts


async def hybrid_search(
    query_dense: list[float],
    query_sparse: dict,
    source_ids: list[str] | None = None,
    exclude_source_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float = 0.0,
    balance_sources: bool = False,
) -> list[dict]:
    """
    Búsqueda híbrida (RRF sobre dense + sparse).

    Si balance_sources=True y no hay filtro explícito de fuentes, crea prefetches
    independientes por fuente con su propio filtro y Weighted RRF, asignando
    mayor peso a fuentes minoritarias según su cantidad de chunks.
    (requiere Qdrant v1.17+ para RrfQuery).
    """
    from qdrant_client.models import Fusion, FusionQuery, Prefetch

    client = _get_client()

    if source_ids is not None and len(source_ids) == 0:
        return []

    discard_filter = FieldCondition(key="is_discarded", match=MatchValue(value=True))
    # Solo los puntos de FAQ tienen is_active; must_not descarta solo las FAQ inactivas.
    inactive_filter = FieldCondition(key="is_active", match=MatchValue(value=False))

    # ── Per-source prefetches con Weighted RRF ─────────────────────────────
    fetched = False
    if balance_sources and exclude_source_ids is None:
        all_sids, chunk_counts = await get_source_info()
        if len(all_sids) > 1:
            # Determina qué fuentes balancear (todas o un subconjunto filtrado)
            target_sids = all_sids if source_ids is None else [s for s in all_sids if s in source_ids]
            if len(target_sids) > 1:
                sorted_sids = sorted(target_sids)
                total = sum(chunk_counts.values())
                num = len(target_sids)
                avg = total / num
                prefetches = []
                raw_weights: list[float] = []
                limits: list[int] = []
                for sid in sorted_sids:
                    count = chunk_counts[sid]
                    effective = max(count, 1)
                    raw = (avg / effective) ** 0.3
                    raw_weights.append(raw)
                    scale = avg / effective
                    limit = min(max(int(top_k * 1.5), int(top_k * scale)), max(top_k * 3, 200))
                    limit = min(limit, effective)
                    limits.append(limit)

                # Normaliza los pesos para que la fuente más grande tenga peso = 1.0
                min_raw = min(raw_weights)
                norm = [min(w / min_raw, 5.0) for w in raw_weights]

                rrf_weights: list[float] = []
                for i, sid in enumerate(sorted_sids):
                    count = chunk_counts[sid]
                    source_limit = limits[i]
                    weight = norm[i]
                    log.info("hybrid.balance_source", source_id=sid[:8], count=count, limit=source_limit, weight=round(weight, 2))
                    sid_filter = Filter(
                        must=[FieldCondition(key="source_id", match=MatchValue(value=sid))],
                        must_not=[discard_filter, inactive_filter],
                    )
                    prefetches.append(
                        Prefetch(query=query_dense, using=DENSE_VECTOR, limit=source_limit, filter=sid_filter)
                    )
                    prefetches.append(
                        Prefetch(
                            query=SparseVector(indices=query_sparse["indices"], values=query_sparse["values"]),
                            using=SPARSE_VECTOR,
                            limit=source_limit,
                            filter=sid_filter,
                        )
                    )
                    rrf_weights.extend([weight, weight])
                fetch_limit = max(top_k, 50)
                results = await client.query_points(
                    collection_name=COLLECTION,
                    prefetch=prefetches,
                    query=RrfQuery(rrf=Rrf(k=60, weights=rrf_weights)),
                    limit=fetch_limit,
                    with_payload=True,
                )
                fetched = True

    if not fetched:
        # ── Búsqueda unificada ──────────────────────────────────────────────
        must_conditions: list = []
        must_not: list = [discard_filter, inactive_filter]
        if source_ids:
            must_conditions.append(FieldCondition(key="source_id", match=MatchAny(any=list(source_ids))))
        if exclude_source_ids:
            must_not.append(FieldCondition(key="source_id", match=MatchAny(any=list(exclude_source_ids))))
        source_filter = Filter(must=must_conditions, must_not=must_not) if (must_conditions or must_not) else None

        prefetch_limit_dense = max(top_k * 10, 100)
        prefetch_limit_sparse = max(top_k * 20, 200)
        fetch_limit = max(top_k * 10, 100) if not source_ids else top_k

        results = await client.query_points(
            collection_name=COLLECTION,
            prefetch=[
                Prefetch(query=query_dense, using=DENSE_VECTOR, limit=prefetch_limit_dense),
                Prefetch(
                    query=SparseVector(indices=query_sparse["indices"], values=query_sparse["values"]),
                    using=SPARSE_VECTOR,
                    limit=prefetch_limit_sparse,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=fetch_limit,
            query_filter=source_filter,
            with_payload=True,
        )

    # ── Post-procesamiento común ───────────────────────────────────────────
    raw_docs = [{"score": p.score, **p.payload} for p in results.points]
    if score_threshold > 0.0:
        before = len(raw_docs)
        raw_docs = [d for d in raw_docs if d["score"] >= score_threshold]
        if len(raw_docs) != before:
            log.info("hybrid.score_filtered", before=before, after=len(raw_docs), threshold=score_threshold)

    seen_parents: set[str] = set()
    deduped: list[dict] = []
    for d in raw_docs:
        pid = d.get("parent_id")
        if pid:
            if pid in seen_parents:
                continue
            seen_parents.add(pid)
        deduped.append(d)

    # Cap solo necesario en el path unificado; balance_sources ya reparte por pesos de RrfQuery.
    if not fetched and not source_ids and len(deduped) > top_k:
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
        remaining = top_k - len(diverse)
        if remaining > 0:
            diverse.extend(overflow[:remaining])
        docs = diverse[:top_k]
    else:
        docs = deduped[:top_k]

    src_dist = {}
    for d in docs:
        sid = d.get("source_id", "?")
        src_dist[sid] = src_dist.get(sid, 0) + 1
    log.info("hybrid.result", requested=top_k, after_dedup=len(deduped), returned=len(docs), sources=src_dist)
    return docs
