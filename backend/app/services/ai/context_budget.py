"""Estimación de tokens y recorte silencioso de contexto (Token Guardrails).

Evita superar la ventana de contexto del modelo antes de llamar al LLM: en
lugar de dejar que el proveedor devuelva un error de ventana excedida (que
rompe el streaming SSE), recortamos los chunks menos relevantes por score y
seguimos con lo que cabe. Heurística conservadora: estima tokens como ~4
caracteres por token (sin tiktoken, para no acoplarnos al tokenizador de un
proveedor concreto).
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Ventanas por tipo de proveedor (topes conservadores conocidos). Se usa como
# límite superior para recortar; es preferible recortar de más a pasarse.
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

# Overrides por familia de modelo (subcadena en model_name, insensible a
# mayúsculas). Cubre modelos pequeños dentro de un mismo proveedor.
MODEL_CONTEXT_OVERRIDES: dict[str, int] = {
    "gpt-3.5": 16_385,
    "gpt-4-32k": 32_768,
    "gpt-4.1-nano": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4o-mini": 128_000,
    "claude-3-haiku": 200_000,
}

DEFAULT_CONTEXT_WINDOW = 32_768
SAFETY_MARGIN_TOKENS = 1_024
MAX_CONTEXT_FRACTION = 0.6  # tope de la ventana dedicado al contexto recuperado


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


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
        # Ventana saturada por system+history+output: conservar solo el de
        # mayor score para no enviar contexto vacío.
        keep_idx = ordered_by_score[:1]
        keep_idx.sort()
        kept = [chunks[i] for i in keep_idx]
        info.update(truncated=True, kept=len(kept), dropped=len(chunks) - len(kept))
        log.warning("context.budget_exhausted", context_window=context_window, base_tokens=base_tokens)
        return kept, info

    keep_idx: list[int] = []
    used = 0
    for i in ordered_by_score:
        t = estimate_tokens(chunks[i].get("text"))
        if keep_idx and used + t > budget:
            continue
        keep_idx.append(i)
        used += t

    keep_idx.sort()  # preservar orden original de los chunks
    kept = [chunks[i] for i in keep_idx]
    dropped = len(chunks) - len(kept)
    if dropped:
        info.update(truncated=True, kept=len(kept), dropped=dropped)
        log.warning("context.truncated", kept=len(kept), dropped=dropped, budget=budget, used=used)
    return kept, info
