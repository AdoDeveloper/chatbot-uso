from __future__ import annotations

"""
Semantic cache for chat responses using Redis + embedding similarity.

University chatbots have highly repetitive queries ("¿cuándo es la matrícula?",
"requisitos de admisión", etc.). A semantic cache with cosine similarity
threshold 0.93 can hit 30-60% of queries post-warmup, saving LLM costs.

Architecture:
  - Embeddings are computed with the same model used for RAG (e5-large)
  - Cached as Redis hashes with an embedding vector for ANN lookup
  - TTL 12h by default, invalidated on document re-index via doc_version bump

Falls back gracefully if Redis is unavailable — cache miss, not error.
"""

import hashlib
import json
from typing import Any

import numpy as np
import structlog

from app.core.redis import get_redis
from app.services.ai.embedding import embed_texts_async

log = structlog.get_logger()

CACHE_PREFIX = "semcache:v2:"
DEFAULT_TTL = 43200  # 12 hours
SIMILARITY_THRESHOLD = 0.93
MAX_CACHED_EMBEDDINGS = 10000
# Límite duro de claves a escanear por request: evita latencia O(n) cuando el
# caché crece. Con 1000 entradas el escaneo toma ~200ms; con 10k+ puede tomar
# segundos. Si se alcanza este límite, se devuelve miss en vez de seguir.
SCAN_BATCH_HARD_LIMIT = 2000


def _threshold() -> float:
    """Umbral por defecto cuando el caller no pasa el valor efectivo del panel."""
    return SIMILARITY_THRESHOLD


def _sids_token(source_ids: list[str] | None) -> str:
    """Token determinista de los source_ids para comparar scope de fuentes."""
    return json.dumps(sorted(source_ids or []))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _cache_key(question: str, source_ids: list[str] | None, use_draft: bool = False) -> str:
    q = question.lower().strip()
    sids = json.dumps(sorted(source_ids or []))
    scope = "draft" if use_draft else "prod"
    h = hashlib.sha256(f"{q}|{sids}|{scope}".encode()).hexdigest()[:16]
    return f"{CACHE_PREFIX}{scope}:{h}"


async def get_cached_response(
    question: str,
    source_ids: list[str] | None = None,
    use_draft: bool = False,
    threshold: float | None = None,
) -> dict[str, Any] | None:
    """
    Check semantic cache for a similar question.
    Returns {"sources": [...], "content": "..."} or None on miss.
    """
    try:
        redis = get_redis()
        query_emb = (await embed_texts_async([question], prefix="query: "))[0]["dense"]

        scope = "draft" if use_draft else "prod"
        want_sids = _sids_token(source_ids)
        if threshold is None:
            threshold = _threshold()
        # Procesa lote a lote (200 claves por SCAN): la memoria queda acotada al
        # tamaño del lote en vez de cargar las ~10k entradas completas en RAM.
        best_score = 0.0
        best_entry = None
        scanned = 0
        cursor = 0
        while True:
            cursor, batch = await redis.scan(cursor, match=f"{CACHE_PREFIX}{scope}:*", count=200)
            if batch:
                pipe = redis.pipeline()
                for k in batch:
                    pipe.hgetall(k)
                entries = await pipe.execute()
                for entry in entries:
                    if not entry or "embedding" not in entry:
                        continue
                    if entry.get("source_ids", "__missing__") != want_sids:
                        continue
                    cached_emb = json.loads(entry["embedding"])
                    sim = _cosine_similarity(query_emb, cached_emb)
                    if sim > best_score:
                        best_score = sim
                        best_entry = entry
                scanned += len(batch)
            if cursor == 0:
                break
            # Hard limit: si el caché es muy grande, salir temprano para
            # evitar latencia excesiva. Mejor un miss ocasional que un
            # slowdown de segundos en cada request de chat.
            if scanned >= SCAN_BATCH_HARD_LIMIT:
                log.debug("semantic_cache.scan_hard_limit", scanned=scanned)
                break

        if best_score >= threshold and best_entry:
            log.info("semantic_cache.hit", similarity=round(best_score, 4))
            return {
                "sources": json.loads(best_entry.get("sources", "[]")),
                "content": best_entry.get("content", ""),
            }

        log.debug("semantic_cache.miss", best_similarity=round(best_score, 4))
        return None

    except Exception as exc:
        log.debug("semantic_cache.error", error=str(exc))
        return None


async def store_cached_response(
    question: str,
    source_ids: list[str] | None,
    sources: list[dict],
    content: str,
    ttl: int = DEFAULT_TTL,
    use_draft: bool = False,
) -> None:
    """Store a response in the semantic cache."""
    try:
        redis = get_redis()
        emb = (await embed_texts_async([question], prefix="query: "))[0]["dense"]
        key = _cache_key(question, source_ids, use_draft)

        await redis.hset(key, mapping={
            "question": question,
            "embedding": json.dumps(emb),
            "sources": json.dumps(sources, ensure_ascii=False),
            "content": content,
            "source_ids": _sids_token(source_ids),
        })
        await redis.expire(key, ttl)
        log.info("semantic_cache.stored", key=key[:24])
    except Exception as exc:
        log.debug("semantic_cache.store_error", error=str(exc))


async def invalidate_by_source(source_id: str) -> int:
    """Invalida el caché completo (tanto semántico como exacto).

    Importante: el caché es content-keyed (hash de pregunta + source_ids), no
    source-keyed. Por eso al borrar un Source no podemos saber qué entradas
    cacheadas lo referenciaban — borramos todo el caché para evitar respuestas
    "fantasma" que sigan citando el documento eliminado. Se reconstruye en
    minutos con el tráfico normal del chatbot.

    Borra:
      - `semcache:v2:*` (cache semántico con embeddings — ver CACHE_PREFIX)
      - `chat:v1:*` (cache exacto de chat.py, hash de pregunta+sources)
    """
    try:
        redis = get_redis()
        keys: list[str] = []
        for pattern in (f"{CACHE_PREFIX}*", "chat:v1:*"):
            cursor = 0
            while True:
                cursor, batch = await redis.scan(cursor, match=pattern, count=500)
                keys.extend(batch)
                if cursor == 0:
                    break
        if keys:
            await redis.delete(*keys)
            log.info("cache.invalidated", count=len(keys), source_id=source_id)
        return len(keys)
    except Exception:
        return 0


async def count_entries() -> int:
    """Count cached entries."""
    try:
        redis = get_redis()
        pattern = f"{CACHE_PREFIX}*"
        count = 0
        cursor = 0
        while True:
            cursor, batch = await redis.scan(cursor, match=pattern, count=500)
            count += len(batch)
            if cursor == 0:
                break
        return count
    except Exception:
        return 0


async def list_entries(limit: int = 20) -> list[dict]:
    """List cached question entries."""
    try:
        redis = get_redis()
        pattern = f"{CACHE_PREFIX}*"
        entries = []
        cursor = 0
        while len(entries) < limit:
            cursor, batch = await redis.scan(cursor, match=pattern, count=100)
            for key in batch:
                if len(entries) >= limit:
                    break
                question = await redis.hget(key, "question")
                if question:
                    entries.append({"key": key, "question": question})
            if cursor == 0:
                break
        return entries
    except Exception:
        return []


async def delete_entry(key: str) -> None:
    """Delete a specific cache entry by Redis key."""
    try:
        redis = get_redis()
        await redis.delete(key)
    except Exception:
        pass


async def clear_all() -> int:
    """Clear all semantic cache entries."""
    return await invalidate_by_source("")
