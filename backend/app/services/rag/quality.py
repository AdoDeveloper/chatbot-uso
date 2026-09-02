"""Métricas de calidad de respuesta RAG (answer relevance), evaluadas
async/fire-and-forget tras persistir el turno - ver también llm_gateway.grade_faithfulness.
"""
from __future__ import annotations

import structlog

from app.services.ai.embedding import embed_texts_async
from app.services.ai.semantic_cache import cosine_similarity

log = structlog.get_logger()


async def compute_answer_relevance(question: str, answer: str) -> float | None:
    try:
        embeddings = await embed_texts_async([question, answer], prefix="query: ")
        return float(cosine_similarity(embeddings[0]["dense"], embeddings[1]["dense"]))
    except Exception as exc:
        log.warning("rag.answer_relevance_failed", error=str(exc))
        return None
