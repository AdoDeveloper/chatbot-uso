"""Tests para funciones puras de app/services/chat/pipeline.py."""
from __future__ import annotations

from app.services.chat.pipeline import format_sources


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

    def test_truncates_text_to_300_chars(self):
        chunk = {"text": "x" * 500, "source_id": "doc-1", "parent_id": "p-1", "score": 0.5}

        result = format_sources([chunk])

        assert len(result[0]["text"]) == 300

    def test_empty_input_returns_empty_list(self):
        assert format_sources([]) == []
