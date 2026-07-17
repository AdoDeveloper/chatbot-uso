"""
Automatic warnings for chunks at ingestion time.

These flags surface in the review UI to guide the admin: which chunks need
attention before approving the source. They are stored on the Qdrant payload
(no SQL table for chunks).

Flags implemented:
  - short:  length < MIN_LEN_CHARS (probably a stray header / page number / OCR garbage)
  - long:   length > MAX_LEN_FACTOR × parent_size (parsing likely fused two chunks)
  - pii:    regex detected email / phone number / national ID (DUI)
"""
from __future__ import annotations

import re

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
    """Return a list of warning flags for a chunk's text.

    Flags are short string identifiers so they are cheap to store in
    Qdrant payload and index/filter on.
    """
    warnings: list[str] = []

    length = len(text)
    if length < MIN_LEN_CHARS:
        warnings.append("short")
    if length > int(parent_size * MAX_LEN_FACTOR):
        warnings.append("long")

    if _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _DNI_RE.search(text):
        warnings.append("pii")

    return warnings
