"""Tests del Adaptive RAG Router.

Valida que `classify_query` decide la ruta correcta para cada tipo de consulta:
  - greeting → respuesta directa sin retrieval
  - factual  → retrieval + rerank
  - complex  → CRAG (expand + grade + rewrite)

Estos tests son puros (no tocan BD/Redis/Qdrant) — corren en milisegundos.
"""
from __future__ import annotations

import pytest

from app.services.rag.router import QueryRoute, classify_query, get_greeting_response


class TestGreetingDetection:
    @pytest.mark.parametrize("query", [
        "hola",
        "Hola",
        "HOLA",
        "  hola  ",
        "hola.",
        "hola!",
        "hola?",
        "hola.!?",
        "buenos días",
        "Buenas tardes",
        "Buenas noches",
        "buenas",
        "hey",
        "Hi",
        "Hello",
        "gracias",
        "Gracias!",
        "ok",
        "Vale",
        "perfecto",
        "entendido",
        "¿cómo estás?",
        "cómo estás",
        "qué tal",
        "¿qué tal?",
        # Saludos encadenados — antes del fix, solo una alternativa cubría
        # todo el mensaje y "hola buenos días" caía a la ruta factual.
        "hola buenos días",
        "hola, buenos días",
        "hola buenas tardes",
        "hola, ¿qué tal?",
        "gracias, hola",
        "ok gracias perfecto",
    ])
    def test_classifies_greetings(self, query: str):
        assert classify_query(query) == QueryRoute.GREETING

    def test_greeting_response_is_non_empty(self):
        response = get_greeting_response()
        assert isinstance(response, str)
        assert len(response) > 0
        assert "asistente" in response.lower() or "ayudarte" in response.lower()


class TestFactualRoute:
    @pytest.mark.parametrize("query", [
        "¿Cuándo abren las inscripciones?",
        "Requisitos de admisión",
        "horario de la biblioteca",
        "¿Cuál es el costo de la matrícula?",
        "fecha límite para pagar",
        "documentos para inscribirse",
    ])
    def test_short_factual_queries_get_factual_route(self, query: str):
        """Consultas cortas, sin keywords de comparación, sin múltiples
        preguntas: usan la ruta factual (más barata)."""
        assert classify_query(query) == QueryRoute.FACTUAL


class TestComplexRoute:
    def test_query_with_comparison_keyword_is_complex(self):
        assert classify_query("¿Cuál es la diferencia entre carrera técnica y licenciatura?") == QueryRoute.COMPLEX

    def test_versus_keyword_triggers_complex(self):
        assert classify_query("Ingeniería en sistemas vs Ingeniería industrial") == QueryRoute.COMPLEX

    def test_compara_keyword_triggers_complex(self):
        assert classify_query("Compara los planes de estudio de las dos carreras") == QueryRoute.COMPLEX

    def test_mejor_keyword_triggers_complex(self):
        assert classify_query("¿Cuál es la mejor opción de financiamiento?") == QueryRoute.COMPLEX

    def test_multiple_questions_trigger_complex(self):
        """2+ signos de pregunta (apertura o cierre) = consulta multi-parte."""
        assert classify_query("¿Cuándo es la matrícula? ¿y qué documentos llevo?") == QueryRoute.COMPLEX

    def test_long_query_triggers_complex(self):
        """Más de 25 palabras → ruta compleja con CRAG."""
        long_q = " ".join(["palabra"] * 30) + " sobre la universidad"
        assert classify_query(long_q) == QueryRoute.COMPLEX


class TestEdgeCases:
    def test_empty_query_does_not_match_greeting(self):
        """String vacío no debería matchear greeting; cae a factual."""
        assert classify_query("") == QueryRoute.FACTUAL

    def test_whitespace_only_falls_to_factual(self):
        assert classify_query("   ") == QueryRoute.FACTUAL

    def test_greeting_inside_longer_query_is_not_greeting(self):
        """`hola, ¿cuándo es la matrícula?` debe ser factual, no greeting."""
        result = classify_query("hola, ¿cuándo es la matrícula?")
        assert result != QueryRoute.GREETING

    def test_mixed_case_comparison_keyword(self):
        assert classify_query("VENTAJA de hacer el TFG aquí") == QueryRoute.COMPLEX

    def test_25_words_exactly_is_factual(self):
        """Justo 25 palabras = factual; 26+ = complex."""
        q25 = " ".join(["palabra"] * 25)
        assert classify_query(q25) == QueryRoute.FACTUAL

    def test_26_words_is_complex(self):
        q26 = " ".join(["palabra"] * 26)
        assert classify_query(q26) == QueryRoute.COMPLEX
