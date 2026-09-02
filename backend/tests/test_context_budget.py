"""Tests de app/services/ai/context_budget.py - recorte de contexto por presupuesto.

Sin cobertura previa pese a ser lógica que evita 413 Payload Too Large del
proveedor LLM: si el chunk de mayor score por sí solo excede el presupuesto
disponible, debía truncarse su propio texto en vez de enviarse íntegro.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.ai.context_budget import (
    CHARS_PER_TOKEN,
    DEFAULT_CONTEXT_WINDOW,
    estimate_tokens,
    get_context_window,
    truncate_context_chunks,
)


def _chunk(text: str, score: float, source_id: str = "s1") -> dict:
    return {"text": text, "score": score, "source_id": source_id}


def _provider(*, model_name: str = "", provider_type: str = "", context_limit=None):
    return SimpleNamespace(model_name=model_name, provider_type=provider_type, context_limit=context_limit)


class TestGetContextWindow:
    def test_explicit_context_limit_wins_over_everything(self):
        # context_limit no existe hoy como campo real en LLMProvider, pero get_context_window ya lo respeta si algún caller lo pasa - contrato forward-compatible.
        p = _provider(model_name="gpt-4o", provider_type="openai", context_limit=999_999)
        assert get_context_window(p) == 999_999

    def test_more_specific_model_override_wins_over_generic_prefix(self):
        """gpt-4.1-nano y gpt-4.1-mini deben matchear antes que gpt-4.1
        genérico; gpt-4o-mini antes que gpt-4o. El orden de inserción del
        dict importa porque get_context_window usa `needle in model_name`."""
        assert get_context_window(_provider(model_name="gpt-4.1-nano-2026")) == 1_000_000
        assert get_context_window(_provider(model_name="gpt-4.1-2026-05-01")) == 1_000_000
        assert get_context_window(_provider(model_name="gpt-4o-mini")) == 128_000
        assert get_context_window(_provider(model_name="gpt-4o")) == 128_000
        assert get_context_window(_provider(model_name="o3-mini")) == 200_000

    def test_unknown_model_falls_back_to_provider_type(self):
        p = _provider(model_name="some-brand-new-model-xyz", provider_type="anthropic")
        # Sin override por nombre de modelo, cae al tamaño de ventana típico del proveedor (200k Anthropic), no al default genérico.
        from app.services.ai.context_budget import PROVIDER_CONTEXT_WINDOWS
        assert get_context_window(p) == PROVIDER_CONTEXT_WINDOWS["anthropic"]

    def test_completely_unknown_provider_and_model_uses_default(self):
        p = _provider(model_name="mystery-model", provider_type="mystery-provider")
        assert get_context_window(p) == DEFAULT_CONTEXT_WINDOW


class TestTruncateContextChunks:
    def test_empty_chunks_returns_empty(self):
        kept, info = truncate_context_chunks([], context_window=32_768)
        assert kept == []
        assert info["truncated"] is False

    def test_all_chunks_fit_no_truncation(self):
        chunks = [_chunk("texto corto", 0.9), _chunk("otro texto corto", 0.8)]
        kept, info = truncate_context_chunks(chunks, context_window=32_768)
        assert len(kept) == 2
        assert info["truncated"] is False

    def test_drops_lowest_score_chunks_when_over_budget(self):
        # Ventana pequeña para forzar recorte: cada chunk de 1000 chars ~250 tokens.
        big_text = "palabra " * 500  # ~4000 chars -> ~1000 tokens
        chunks = [
            _chunk(big_text, score=0.9),
            _chunk(big_text, score=0.5),
            _chunk(big_text, score=0.1),
        ]
        # MAX_CONTEXT_FRACTION=0.6, ventana pequeña -> cabe ~1 chunk grande.
        kept, info = truncate_context_chunks(chunks, context_window=2_048)
        assert info["truncated"] is True
        assert len(kept) < 3
        assert any(c["score"] == 0.9 for c in kept)

    def test_first_chunk_alone_exceeding_budget_gets_truncated_not_sent_whole(self):
        huge_text = "x" * 100_000  # ~25000 tokens estimados
        chunks = [_chunk(huge_text, score=0.95)]

        kept, info = truncate_context_chunks(
            chunks, context_window=2_048, system_prompt="", history=[],
        )
        assert len(kept) == 1
        kept_tokens = estimate_tokens(kept[0]["text"])
        # budget = int(2048*0.6) - 0 - 1024 = 205
        assert kept_tokens <= 210, (
            f"el primer chunk no se truncó: {kept_tokens} tokens estimados "
            f"(texto original: {len(huge_text)} chars)"
        )
        assert len(kept[0]["text"]) < len(huge_text)
        assert info["truncated"] is True

    def test_first_chunk_truncation_preserves_other_chunk_fields(self):
        huge_text = "y" * 50_000
        chunks = [_chunk(huge_text, score=0.9, source_id="doc-42")]
        kept, _ = truncate_context_chunks(chunks, context_window=1_500)
        assert kept[0]["source_id"] == "doc-42"
        assert kept[0]["score"] == 0.9

    def test_budget_exhausted_still_keeps_one_chunk(self):
        chunks = [_chunk("contenido relevante " * 50, score=0.9)]
        huge_prompt = "instrucciones del sistema " * 2000
        kept, info = truncate_context_chunks(
            chunks, context_window=2_048, system_prompt=huge_prompt,
        )
        assert len(kept) == 1
        assert info["truncated"] is True

    def test_budget_negative_truncates_to_minimal_text_not_sent_whole(self):
        huge_prompt = "instrucciones " * 5000  # agota la ventana por sí solo
        chunks = [_chunk("x" * 50_000, score=0.9)]

        kept, info = truncate_context_chunks(
            chunks, context_window=2_048, system_prompt=huge_prompt,
        )
        assert len(kept) == 1
        assert len(kept[0]["text"]) < 50_000
        assert info["truncated"] is True
