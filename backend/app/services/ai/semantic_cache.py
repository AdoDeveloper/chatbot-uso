"""
Semantic cache for chat responses using Redis + embedding similarity.
Falls back gracefully if Redis is unavailable - cache miss, not error.
"""
from __future__ import annotations

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
SCAN_BATCH_HARD_LIMIT = 2000
_GENERATION_KEY = "semcache:generation"


async def get_cache_generation() -> int:
    """Contador global, incrementado en cada invalidate_by_source().

    Usado para cerrar una race TOCTOU: retrieve_context() lee los chunks al
    inicio del turno, pero store_cache() escribe la respuesta recién al
    terminar el streaming del LLM (varios segundos después). Si un admin
    edita/descarta el chunk usado en ese intervalo, invalidate_by_source()
    limpia el caché - pero store_cache() lo volvía a poblar de todas formas
    con la respuesta ya generada (basada en el texto viejo), revirtiendo la
    invalidación y sirviendo información obsoleta hasta el próximo edit o
    el TTL de 12h. Comparando la generación capturada al leer el contexto
    contra la generación actual al escribir, una escritura "vencida" por una
    invalidación intermedia se descarta en vez de re-cachearse.
    """
    try:
        redis = get_redis()
        val = await redis.get(_GENERATION_KEY)
        return int(val) if val else 0
    except Exception:
        return 0


def _threshold() -> float:
    """Umbral por defecto cuando el caller no pasa el valor efectivo del panel."""
    return SIMILARITY_THRESHOLD


def _sids_token(source_ids: list[str] | None) -> str:
    """Token determinista de los source_ids para comparar scope de fuentes."""
    return json.dumps(sorted(source_ids or []))


def cosine_similarity(a: list[float], b: list[float]) -> float:
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
                    sim = cosine_similarity(query_emb, cached_emb)
                    if sim > best_score:
                        best_score = sim
                        best_entry = entry
                scanned += len(batch)
            if cursor == 0:
                break
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
    min_generation: int | None = None,
) -> None:
    """Guarda una respuesta en el caché semántico.

    `min_generation`: generación de caché capturada (get_cache_generation())
    al momento de leer el contexto, ANTES de generar la respuesta con el
    LLM. Si al momento de escribir la generación actual ya avanzó (una
    edición/descarte de fuente invalidó el caché mientras el LLM generaba),
    la escritura se descarta - ver docstring de get_cache_generation().
    """
    try:
        if min_generation is not None:
            current_gen = await get_cache_generation()
            if current_gen != min_generation:
                log.info(
                    "semantic_cache.store_skipped_stale_generation",
                    min_generation=min_generation, current_generation=current_gen,
                )
                return

        redis = get_redis()
        emb = (await embed_texts_async([question], prefix="query: "))[0]["dense"]
        key = _cache_key(question, source_ids, use_draft)

        pipe = redis.pipeline()
        pipe.hset(key, mapping={
            "question": question,
            "embedding": json.dumps(emb),
            "sources": json.dumps(sources, ensure_ascii=False),
            "content": content,
            "source_ids": _sids_token(source_ids),
        })
        pipe.expire(key, ttl)
        await pipe.execute()
        log.info("semantic_cache.stored", key=key[:24])
    except Exception as exc:
        log.debug("semantic_cache.store_error", error=str(exc))


async def invalidate_by_source(source_id: str) -> int:
    """Invalida el caché completo (tanto semántico como exacto)."""
    try:
        redis = get_redis()
        await redis.incr(_GENERATION_KEY)
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


async def delete_entry(key: str) -> bool:
    """Borra una entrada del caché semántico.

    La clave llega desde el path del endpoint, así que se exige el prefijo del
    caché: el mismo Redis aloja los locks de ingesta, los contadores de rate
    limit y los cooldowns de alertas, y borrar cualquiera de ellos tendría
    efectos muy distintos a "limpiar una respuesta guardada".
    """
    if not key.startswith(CACHE_PREFIX):
        return False
    try:
        redis = get_redis()
        await redis.delete(key)
    except Exception:
        pass
    return True


async def clear_all() -> int:
    """Clear all semantic cache entries."""
    return await invalidate_by_source("")
