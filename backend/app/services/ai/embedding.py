"""Embedding service - multilingual-e5-large via fastembed."""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache

import structlog

log = structlog.get_logger()

_ONNX_SEM: list[asyncio.Semaphore] = []

def _get_onnx_sem() -> asyncio.Semaphore:
    if not _ONNX_SEM:
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

# Mapeado al volumen model_cache en docker-compose
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
    """Genera embeddings densos y sparse para una lista de textos."""
    if not texts:
        return []

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
    """Async wrapper - ejecuta la inferencia ONNX en un thread pool para no bloquear el event loop."""
    loop = asyncio.get_running_loop()
    async with _get_onnx_sem():
        return await loop.run_in_executor(None, embed_texts, texts, prefix)
