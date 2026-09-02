"""
Adaptive RAG Router - classifies query complexity: greeting/factual/complex.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()

# Tuplas de 1-2 palabras normalizadas para matching greedy de saludos encadenados.
_GREETING_TOKENS: set[tuple[str, ...]] = {
    ("hola",), ("hey",), ("hi",), ("hello",),
    ("buen",), ("buena",), ("buenos",), ("buenas",),
    ("buenos", "dias"), ("buenas", "tardes"), ("buenas", "noches"),
    ("gracias",), ("ok",), ("vale",), ("perfecto",), ("entendido",),
    ("como", "estas"), ("que", "tal"),
}
_MAX_PHRASE_WORDS = max(len(t) for t in _GREETING_TOKENS)
# Quita acentos para no duplicar cada entrada de _GREETING_TOKENS en sus dos variantes.
_ACCENTS = str.maketrans("áéíóúü", "aeiouu")
_WORD_STRIP = ",.!?¡¿"
_GREETING_MAX_LEN = 80  # cota dura de longitud antes de tokenizar


def _is_greeting_only(q: str) -> bool:
    """True si la pregunta completa es, en esencia, solo saludo/cortesía.

    Reemplaza al patrón regex `^(?:(?:ALT)\\s*[,.!?]*\\s*)+$` que sufría
    backtracking catastrófico (ReDoS) con entradas tipo "hola " * N: un
    grupo repetido `(...)+ ` cuyo contenido interno también acepta longitud
    cero es la combinación clásica que dispara ese comportamiento. Aquí no
    hay ningún cuantificador de repetición sobre un grupo con alternativas
    - solo tokenización por espacios/puntuación (str.split, O(n)) y
    comparación greedy de tuplas de palabras contra un set fijo.
    """
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

    if _is_greeting_only(q):
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
    """Devuelve el saludo de respuesta. Recurre al valor por defecto si el
    admin no configuró uno personalizado en ChatbotSettings.
    """
    custom = (custom or "").strip()
    return custom if custom else _GREETING_RESPONSE
