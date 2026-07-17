"""
Embedding service — multilingual-e5-large via fastembed.

Model: intfloat/multilingual-e5-large
  - Dense:  1024 dims (vs 384 of MiniLM)
  - Sparse: Qdrant/bm25 (statistical BM25 for hybrid search)
  - Max tokens: 512 (vs 128 of MiniLM — 4× more context per chunk)
  - Languages: 100+ including Spanish, SOTA on MIRACL multilingual benchmark
  - Inference: ONNX Runtime — auto-detect GPU (CUDA), fallback CPU

Important — e5 prefix convention:
  embed_texts(texts, prefix="passage: ")  →  at ingestion time (documents)
  embed_texts(texts, prefix="query: ")    →  at search time (user questions)
  Omitting the prefix works but reduces retrieval accuracy.

Why multilingual-e5-large over MiniLM:
  MiniLM's 128-token limit silently truncated chunks >500 chars, discarding
  roughly half the content before embedding. e5-large handles 512 tokens and
  produces richer 1024-dim semantic representations.
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache

import structlog

log = structlog.get_logger()

# Serializa la inferencia ONNX entre todos los workers/threads.
# ONNX en CPU no mejora con paralelismo — solo genera contención.
# Con este semáforo las requests se encolan y cada una tarda ~0.4s
# en vez de competir por CPU y tardar 10–24s.
#
# The semaphore must be created inside a running event loop, so we
# initialize it lazily via a module-level lock-free pattern: the first
# call to embed_texts_async (always within a running loop) creates it.
# We store it in a list so we can swap it atomically without a global lock.
_ONNX_SEM: list[asyncio.Semaphore] = []

def _get_onnx_sem() -> asyncio.Semaphore:
    if not _ONNX_SEM:
        # Two coroutines reaching here simultaneously in the same event loop
        # will both append, but asyncio is single-threaded — only one runs at
        # a time, so at most one Semaphore is ever created.
        _ONNX_SEM.append(asyncio.Semaphore(1))
    return _ONNX_SEM[0]


def _onnx_providers() -> list[str]:
    """Auto-detect GPU: si CUDA está disponible, usarla; si no, CPU."""
    try:
        import onnxruntime
        available = onnxruntime.get_available_providers()
        if "CUDAExecutionProvider" in available:
            log.info("embedding.gpu_detected", provider="CUDAExecutionProvider")
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:
        pass
    return ["CPUExecutionProvider"]

_DENSE_MODEL_NAME = "intfloat/multilingual-e5-large"
_SPARSE_MODEL_NAME = "Qdrant/bm25"

# Mapped to model_cache volume in docker-compose
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "fastembed")


@lru_cache(maxsize=1)
def _get_dense_model():
    from fastembed import TextEmbedding
    providers = _onnx_providers()
    log.info("embedding.loading_dense", model=_DENSE_MODEL_NAME, providers=providers)
    model = TextEmbedding(_DENSE_MODEL_NAME, cache_dir=_CACHE_DIR, providers=providers)
    log.info("embedding.ready_dense", model=_DENSE_MODEL_NAME, providers=providers)
    return model


@lru_cache(maxsize=1)
def _get_sparse_model():
    from fastembed import SparseTextEmbedding
    log.info("embedding.loading_sparse", model=_SPARSE_MODEL_NAME)
    return SparseTextEmbedding(_SPARSE_MODEL_NAME, cache_dir=_CACHE_DIR)


def embed_texts(texts: list[str], prefix: str = "") -> list[dict]:
    """
    Genera embeddings densos y sparse para una lista de textos.
    Retorna lista de dicts con keys: dense, sparse_indices, sparse_values.

    prefix: e5 models require "query: " for search queries and "passage: "
            for documents at ingestion time. Omitting degrades performance.
    NOTA: función síncrona — usar embed_texts_async desde contextos async.
    """
    dense_model = _get_dense_model()
    sparse_model = _get_sparse_model()

    prefixed = [prefix + t for t in texts] if prefix else texts
    dense_vecs = list(dense_model.embed(prefixed))
    sparse_vecs = list(sparse_model.embed(prefixed))

    results = []
    for dense, sparse in zip(dense_vecs, sparse_vecs):
        results.append({
            "dense": dense.tolist(),
            "sparse_indices": sparse.indices.tolist(),
            "sparse_values": sparse.values.tolist(),
        })

    log.info("embedding.done", count=len(texts), dense_dim=len(results[0]["dense"]) if results else 0)
    return results


async def embed_texts_async(texts: list[str], prefix: str = "") -> list[dict]:
    """
    Async wrapper — ejecuta la inferencia ONNX en un thread pool para no
    bloquear el event loop.

    El semáforo _ONNX_SEM(1) garantiza que solo un worker corre inferencia
    ONNX a la vez. Los demás esperan en la cola async (sin bloquear el event
    loop ni consumir CPU). Esto elimina la contención entre workers que
    causaba spikes de 10–24s en CPU.
    """
    loop = asyncio.get_running_loop()
    async with _get_onnx_sem():
        return await loop.run_in_executor(None, embed_texts, texts, prefix)
