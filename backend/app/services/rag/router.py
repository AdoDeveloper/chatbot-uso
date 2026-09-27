"""
Adaptive RAG Router - classifies query complexity: greeting/factual/complex.
"""
from __future__ import annotations

import re

import structlog

log = structlog.get_logger()

# Tuplas de 1-2 palabras normalizadas para matching greedy de saludos encadenados.
_GREETING_TOKENS: set[tuple[str, ...]] = {
    ("hola",), ("hey",), ("hi",), ("hello",),
    ("buen",), ("buena",), ("buenos",), ("buenas",),
    ("buenos", "dias"), ("buenas", "tardes"), ("buenas", "noches"),
    ("gracias",), ("muchas", "gracias"), ("mil", "gracias"),
    ("ok",), ("vale",), ("perfecto",), ("entendido",),
    ("como", "estas"), ("que", "tal"),
}
_MAX_PHRASE_WORDS = max(len(t) for t in _GREETING_TOKENS)
# Quita acentos para no duplicar cada entrada de _GREETING_TOKENS en sus dos variantes.
_ACCENTS = str.maketrans("áéíóúü", "aeiouu")
_WORD_STRIP = ",.!?¡¿"
_GREETING_MAX_LEN = 80  # cota dura de longitud antes de tokenizar


def _is_greeting_only(q: str) -> bool:
    """True si la pregunta completa es, en esencia, solo saludo/cortesía."""
    if len(q) > _GREETING_MAX_LEN:
        return False
    words = [
        w.strip(_WORD_STRIP).translate(_ACCENTS)
        for w in q.strip().lower().replace(",", " ").split()
    ]
    words = [w for w in words if w]
    if not words:
        return False

    i = 0
    n = len(words)
    while i < n:
        matched = False
        for length in range(min(_MAX_PHRASE_WORDS, n - i), 0, -1):
            if tuple(words[i:i + length]) in _GREETING_TOKENS:
                i += length
                matched = True
                break
        if not matched:
            return False
    return True

_ACK_TOKENS: set[tuple[str, ...]] = {
    ("gracias",), ("muchas", "gracias"), ("mil", "gracias"),
    ("ok",), ("vale",), ("perfecto",), ("entendido",),
}

_ACK_RESPONSE = "Con gusto. ¿Hay algo más en lo que pueda ayudarle?"


def _is_acknowledgement(q: str) -> bool:
    """Agradecimiento o conformidad ("gracias", "ok"), sin saludo."""
    words = [
        w.strip(_WORD_STRIP).translate(_ACCENTS)
        for w in q.strip().lower().replace(",", " ").split()
    ]
    words = [w for w in words if w]
    i = 0
    while i < len(words):
        for length in (2, 1):
            if tuple(words[i:i + length]) in _ACK_TOKENS:
                i += length
                break
        else:
            return False
    return bool(words)


_COMPARISON_RE = re.compile(r"\b(compara\w*|diferencias?|versus|vs\.?|mejor|peor|ventajas?)\b", re.IGNORECASE)

_GREETING_RESPONSE = (
    "¡Hola! Soy el asistente virtual de la universidad. "
    "¿En qué puedo ayudarle? Puedo resolver dudas sobre trámites, "
    "requisitos, fechas, normativas y más."
)


class QueryRoute:
    GREETING = "greeting"
    FACTUAL = "factual"
    COMPLEX = "complex"


def classify_query(question: str) -> str:
    q = question.strip()

    if _is_greeting_only(q):
        return QueryRoute.GREETING

    words = q.split()

    has_comparison = bool(_COMPARISON_RE.search(q))
    has_multi_question = q.count("?") > 1 or q.count("¿") > 1
    is_long = len(words) > 25

    if has_comparison or has_multi_question or is_long:
        return QueryRoute.COMPLEX

    return QueryRoute.FACTUAL


def get_greeting_response(custom: str | None = None, question: str | None = None) -> str:
    """Devuelve el saludo de respuesta, o un cierre cortés si solo se agradeció."""
    if question and _is_acknowledgement(question):
        return _ACK_RESPONSE
    custom = (custom or "").strip()
    return custom if custom else _GREETING_RESPONSE
