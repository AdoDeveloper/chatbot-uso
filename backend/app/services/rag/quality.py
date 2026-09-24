"""Métricas de calidad de respuesta RAG."""
from __future__ import annotations

import re

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


_NO_ANSWER_MARKERS = re.compile(
    r"\bno (dispongo|cuento) (de|con)\b|\bno tengo (esa |la )?informaci[oó]n\b|"
    r"\bno encontr[eé] informaci[oó]n\b|\bno (aparece|se menciona|se indica|se especifica)\b",
    re.IGNORECASE,
)
_NO_ANSWER_OPENING = re.compile(
    r"^\W*(lo siento,?\s*)?(no (tengo|dispongo|cuento|encontr[eé]|encuentro)|desconozco|no s[eé]\b)",
    re.IGNORECASE,
)


def is_no_answer_reply(text: str | None) -> bool:
    """True si el asistente admitió no tener la información (vacío de la base de conocimiento)."""
    from app.schemas.settings import NO_CONTEXT_MESSAGE

    if not text or not text.strip():
        return False
    if text.strip() == NO_CONTEXT_MESSAGE.strip():
        return True
    return bool(_NO_ANSWER_OPENING.search(text) or _NO_ANSWER_MARKERS.search(text[:300]))
