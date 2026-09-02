"""Estimación de tokens y recorte silencioso de contexto (Token Guardrails)."""

from __future__ import annotations

import structlog

log = structlog.get_logger()

PROVIDER_CONTEXT_WINDOWS: dict[str, int] = {
    "openai": 128_000,
    "azure": 128_000,
    "anthropic": 200_000,
    "gemini": 1_000_000,
    "groq": 32_768,
    "mistral": 32_768,
    "cohere": 128_000,
    "ollama": 32_768,
    "together": 32_768,
    "perplexity": 32_768,
}

MODEL_CONTEXT_OVERRIDES: dict[str, int] = {
    "gpt-3.5": 16_385,
    "gpt-4-32k": 32_768,
    "gpt-4.1-nano": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4.1": 1_000_000,
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-5-nano": 400_000,
    "gpt-5-mini": 400_000,
    "gpt-5": 400_000,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5": 200_000,
    "claude-3.7": 200_000,
    "claude-4": 200_000,
    "claude-5": 200_000,
    "gemini-2.0": 1_000_000,
    "gemini-2.5": 1_000_000,
    "gemini-3": 1_000_000,
    "llama-3.1": 128_000,
    "llama-3.3": 128_000,
    "llama-4": 1_000_000,
    "llama3-70b-8192": 8_192,
    "llama3-8b-8192": 8_192,
    "gemma2-9b-it": 8_192,
    "gemma-3": 128_000,
    "mixtral-8x7b": 32_768,
    "deepseek-v3": 128_000,
    "deepseek-r1": 128_000,
    "qwen3": 128_000,
    "grok-3": 128_000,
    "grok-4": 256_000,
}

DEFAULT_CONTEXT_WINDOW = 32_768
SAFETY_MARGIN_TOKENS = 1_024
MAX_CONTEXT_FRACTION = 0.6  # tope de la ventana dedicado al contexto recuperado



# Caracteres por token (medido: ratio 3.95-4.52, media 4.36); 4.0 deja margen conservador.
CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str | None) -> int:
    """Estimación de tokens por longitud de texto (heurística, sin tokenizador externo)."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def get_context_window(provider) -> int:
    # Si el proveedor expone un límite explícito, se respeta (forward-compatible).
    explicit = getattr(provider, "context_limit", None)
    if explicit:
        return int(explicit)

    model_name = (getattr(provider, "model_name", "") or "").lower()
    for needle, window in MODEL_CONTEXT_OVERRIDES.items():
        if needle in model_name:
            return window

    provider_type = (getattr(provider, "provider_type", "") or "").lower()
    return PROVIDER_CONTEXT_WINDOWS.get(provider_type, DEFAULT_CONTEXT_WINDOW)


def truncate_context_chunks(
    chunks: list[dict],
    *,
    context_window: int,
    system_prompt: str = "",
    history: list[dict] | None = None,
    reserve_output_tokens: int = 0,
) -> tuple[list[dict], dict]:
    """Recorta chunks por score hasta que quepan en la ventana de contexto.

    Nunca lanza ni devuelve vacío si había chunks: al menos se conserva el de
    mayor score. Devuelve (chunks_keep, info).
    """
    info: dict = {"truncated": False, "kept": len(chunks), "dropped": 0}
    if not chunks:
        return chunks, info

    history = history or []
    base_tokens = (
        estimate_tokens(system_prompt)
        + sum(estimate_tokens(m.get("content")) for m in history)
        + max(0, int(reserve_output_tokens))
    )
    budget = int(context_window * MAX_CONTEXT_FRACTION) - base_tokens - SAFETY_MARGIN_TOKENS

    ordered_by_score = sorted(
        range(len(chunks)),
        key=lambda i: float(chunks[i].get("score") or 0),
        reverse=True,
    )

    if budget <= 0:
        keep_idx = ordered_by_score[:1]
        keep_idx.sort()
        min_chars = max(1, int(SAFETY_MARGIN_TOKENS * CHARS_PER_TOKEN * 0.1))
        kept = [
            {**chunks[i], "text": chunks[i].get("text", "")[:min_chars]}
            for i in keep_idx
        ]
        info.update(truncated=True, kept=len(kept), dropped=len(chunks) - len(kept))
        log.warning("context.budget_exhausted", context_window=context_window, base_tokens=base_tokens)
        return kept, info

    keep_idx: list[int] = []
    used = 0
    truncated_first_chunk = False
    for i in ordered_by_score:
        t = estimate_tokens(chunks[i].get("text"))
        if not keep_idx and t > budget:
            max_chars = max(1, int(budget * CHARS_PER_TOKEN))
            chunks[i] = {**chunks[i], "text": chunks[i].get("text", "")[:max_chars]}
            t = budget
            truncated_first_chunk = True
        if keep_idx and used + t > budget:
            continue
        keep_idx.append(i)
        used += t

    keep_idx.sort()
    kept = [chunks[i] for i in keep_idx]
    dropped = len(chunks) - len(kept)
    if truncated_first_chunk:
        info["truncated"] = True
        log.warning("context.first_chunk_truncated", budget=budget)

    src_after = {}
    for c in kept:
        sid = c.get("source_id", "?")
        src_after[sid] = src_after.get(sid, 0) + 1
    if dropped:
        info.update(truncated=True, kept=len(kept), dropped=dropped)
        log.warning("context.truncated", kept=len(kept), dropped=dropped, budget=budget, used=used, sources=src_after)
    else:
        log.debug("context.no_truncation", kept=len(kept), sources=src_after)
    return kept, info
