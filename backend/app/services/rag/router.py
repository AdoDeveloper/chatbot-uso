from __future__ import annotations

"""
Adaptive RAG Router — classifies query complexity: greeting/factual/complex.
Saves 40-60% latency on simple queries by skipping grading/rewriting.
"""

import re

import structlog


log = structlog.get_logger()

_GREETING_WORD = (
    # `buen[oa]s?` cubre: buen, buena, buenos, buenas (saludos en ambos géneros)
    r"hola|buen[oa]s?\s*(tardes?|noches?|días?)?|hey|hi|hello|"
    r"gracias|ok|vale|perfecto|entendido|"
    r"¿?cómo\s+estás\??|¿?qué\s+tal\??"
)

# Encadena una o más frases de saludo (p. ej. "hola buenos días", "hola,
# ¿qué tal?") en vez de exigir que TODO el mensaje sea una sola alternativa
# — sin esto, "hola buenos días" no coincidía con ninguna alternativa
# completa y caía a la ruta "factual", ejecutando el pipeline de RAG
# completo para un simple saludo.
_GREETING_PATTERNS = re.compile(
    rf"^\s*(?:(?:{_GREETING_WORD})\s*[,.!?]*\s*)+$",
    re.IGNORECASE,
)

_GREETING_RESPONSE = (
    "¡Hola! Soy el asistente virtual de la universidad. "
    "¿En qué puedo ayudarte? Puedo resolver dudas sobre trámites, "
    "requisitos, fechas, normativas y más."
)


class QueryRoute:
    GREETING = "greeting"
    FACTUAL = "factual"
    COMPLEX = "complex"


def classify_query(question: str) -> str:
    q = question.strip()

    if _GREETING_PATTERNS.match(q):
        return QueryRoute.GREETING

    words = q.split()

    has_comparison = any(
        kw in q.lower()
        for kw in ["compara", "diferencia", "versus", "vs", "mejor", "peor", "ventaja"]
    )
    has_multi_question = q.count("?") > 1 or q.count("¿") > 1
    is_long = len(words) > 25

    if has_comparison or has_multi_question or is_long:
        return QueryRoute.COMPLEX

    return QueryRoute.FACTUAL


def get_greeting_response(custom: str | None = None) -> str:
    """Return the greeting response. Falls back to the built-in default if the
    admin hasn't set a custom one in ChatbotSettings.
    """
    custom = (custom or "").strip()
    return custom if custom else _GREETING_RESPONSE
