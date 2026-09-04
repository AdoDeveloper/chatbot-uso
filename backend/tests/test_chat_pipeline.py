"""Tests para funciones puras de app/services/chat/pipeline.py."""
from __future__ import annotations

from app.services.chat.pipeline import _truncate_at_word_boundary, format_sources


class TestTruncateAtWordBoundary:
    def test_no_truncation_needed(self):
        assert _truncate_at_word_boundary("corto", 300) == "corto"

    def test_cuts_at_last_space_before_limit(self):
        text = "Teléfono: 7851-7588 y 7841-4724 disponible en horario de oficina"
        result = _truncate_at_word_boundary(text, 25)
        assert result == "Teléfono: 7851-7588 y…"

    def test_never_splits_a_long_word_mid_way(self):
        """Con max_len=15, el corte literal caería a mitad de
        '78517588extra'; debe retroceder al espacio anterior en vez de
        partir la palabra."""
        text = "Teléfono: 78517588extra continúa aquí"
        result = _truncate_at_word_boundary(text, 15)
        assert result == "Teléfono:…"
        assert "7851" not in result

    def test_no_space_within_limit_cuts_at_exact_length(self):
        text = "x" * 500
        result = _truncate_at_word_boundary(text, 300)
        assert result == "x" * 300 + "…"


class TestFormatSources:
    def test_deduplicates_by_parent_id_not_source_id(self):
        """Dos secciones distintas de un mismo documento FAQ (mismo source_id,
        parent_id distinto) deben aparecer como fuentes separadas: deduplicar
        por source_id oculta de qué sección salió cada dato citado."""
        chunk_a = {
            "text": "[Sección: Equivalencias] R/ El costo es de $50...",
            "source_id": "doc-1", "source_name": "FAQ", "parent_id": "parent-A", "score": 0.83,
        }
        chunk_b = {
            "text": "[Sección: Carreras] R/ El costo del curso es de $30...",
            "source_id": "doc-1", "source_name": "FAQ", "parent_id": "parent-B", "score": 0.75,
        }

        result = format_sources([chunk_a, chunk_b])

        assert len(result) == 2
        assert {r["text"][:20] for r in result} == {chunk_a["text"][:20], chunk_b["text"][:20]}

    def test_still_deduplicates_repeated_parent_id(self):
        """Dos child chunks de la MISMA sección (mismo parent_id) sí deben
        colapsar a una sola fuente - son fragmentos del mismo dato, no
        secciones independientes."""
        chunk_a = {
            "text": "Fragmento 1 de la misma sección",
            "source_id": "doc-1", "parent_id": "parent-A", "score": 0.9,
        }
        chunk_b = {
            "text": "Fragmento 2 de la misma sección",
            "source_id": "doc-1", "parent_id": "parent-A", "score": 0.8,
        }

        result = format_sources([chunk_a, chunk_b])

        assert len(result) == 1
        assert result[0]["text"].startswith("Fragmento 1")

    def test_falls_back_to_source_id_without_parent_id(self):
        """Fuentes sin chunking Parent-Child (sin parent_id) siguen
        deduplicando por source_id, como antes."""
        chunk_a = {"text": "Texto 1", "source_id": "doc-1", "score": 0.9}
        chunk_b = {"text": "Texto 2", "source_id": "doc-1", "score": 0.8}

        result = format_sources([chunk_a, chunk_b])

        assert len(result) == 1

    def test_truncates_long_text_without_spaces(self):
        """Sin ningún espacio dentro del límite, corta en el carácter 300 y
        marca el corte con elipsis."""
        chunk = {"text": "x" * 500, "source_id": "doc-1", "parent_id": "p-1", "score": 0.5}

        result = format_sources([chunk])

        assert result[0]["text"] == "x" * 300 + "…"

    def test_short_text_is_not_truncated(self):
        chunk = {"text": "Texto corto.", "source_id": "doc-1", "parent_id": "p-1", "score": 0.5}

        result = format_sources([chunk])

        assert result[0]["text"] == "Texto corto."

    def test_empty_input_returns_empty_list(self):
        assert format_sources([]) == []
