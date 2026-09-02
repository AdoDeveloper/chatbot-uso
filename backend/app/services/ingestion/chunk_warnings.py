"""
Automatic warnings for chunks at ingestion time.

These flags surface in the review UI to guide the admin: which chunks need
attention before approving the source. They are stored on the Qdrant payload
(no SQL table for chunks).

Flags implemented:
  - short:     length < MIN_LEN_CHARS (probably a stray header / page number / OCR garbage)
  - long:      length > MAX_LEN_FACTOR × parent_size (parsing likely fused two chunks)
  - pii:       regex detected email / phone number / national ID (DUI)
  - injection: matches the same prompt-injection patterns that validate_input()
               applies to user messages. Ingested documents never pass through
               validate_input - only `question` does - so a chunk containing
               "ignora todas las instrucciones..." or "[SYSTEM] ..." would
               otherwise reach the LLM's prompt as trusted context with zero
               screening. This doesn't block ingestion (a false positive would
               stall a legitimate document); it flags the chunk so the human
               reviewer sees it before approving the source for the public bot.
"""
from __future__ import annotations

import re

from app.services.ai.guardrails import get_active_compiled_patterns

MIN_LEN_CHARS = 50
MAX_LEN_FACTOR = 1.5  # "long" = more than 1.5× the parent chunk size

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Teléfono de El Salvador: 8 dígitos, opcionalmente con prefijo +503,
# admitiendo espacios o guiones (ej. +503 7123-4567, 71234567).
_PHONE_RE = re.compile(r"\b(?:\+?503[\s-]?)?[267]\d{3}[\s-]?\d{4}\b")
# DUI (Documento Único de Identidad, El Salvador): 8 dígitos, guion y 1 dígito
# verificador (ej. 01234567-8).
_DNI_RE = re.compile(r"\b\d{8}-\d\b")


def compute_warnings(text: str, parent_size: int) -> list[str]:
    """Devuelve una lista de flags de advertencia para el texto de un chunk.

    Los flags son identificadores de texto cortos, así son económicos de
    guardar en el payload de Qdrant y de indexar/filtrar.
    """
    warnings: list[str] = []

    length = len(text)
    if length < MIN_LEN_CHARS:
        warnings.append("short")
    if length > int(parent_size * MAX_LEN_FACTOR):
        warnings.append("long")

    if _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _DNI_RE.search(text):
        warnings.append("pii")

    if _has_injection_pattern(text):
        warnings.append("injection")

    return warnings


def _has_injection_pattern(text: str) -> bool:
    for pat, _label, _category, _example, _source, _pid in get_active_compiled_patterns():
        if pat.search(text):
            return True
    return False
