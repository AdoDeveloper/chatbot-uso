"""
Cross-encoder reranker — post-processes hybrid search results.

Model: ms-marco-MultiBERT-L-12 (FlashRank).

Flow:
  hybrid_search returns top_k × 3 candidates
        ↓
  rerank() scores each (query, passage) pair
        ↓
  returns top_k re-ordered by cross-encoder score
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache

import structlog

log = structlog.get_logger()

_MODEL = "ms-marco-MultiBERT-L-12"
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "flashrank")


def _detect_device() -> str:
    """Auto-detect GPU: si CUDA está disponible, usarla; si no, CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            log.info("reranker.gpu_detected", device="cuda")
            return "cuda"
    except Exception:
        pass
    return "cpu"


@lru_cache(maxsize=1)
def _get_ranker():
    from flashrank import Ranker

    device = _detect_device()
    log.info("reranker.loading", model=_MODEL, device=device)
    ranker = Ranker(model_name=_MODEL, cache_dir=_CACHE_DIR, device=device)
    log.info("reranker.ready", model=_MODEL, device=device)
    return ranker


def _rerank_sync(query: str, docs: list[dict], top_k: int) -> list[dict]:
    if not docs:
        return docs

    from flashrank import RerankRequest

    try:
        ranker = _get_ranker()
        # Use parent_text for reranking when available (richer context)
        passages = [
            {"id": i, "text": d.get("parent_text", d["text"])}
            for i, d in enumerate(docs)
        ]
        request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(request)

        reranked: list[dict] = []
        for r in results[:top_k]:
            doc = docs[r["id"]].copy()
            doc["score"] = round(float(r["score"]), 4)
            reranked.append(doc)

        log.info("reranker.done", candidates=len(docs), kept=len(reranked))
        return reranked

    except Exception as exc:
        log.warning("reranker.failed", error=str(exc), fallback="original_order")
        return docs[:top_k]


async def rerank_async(query: str, docs: list[dict], top_k: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _rerank_sync, query, docs, top_k)
