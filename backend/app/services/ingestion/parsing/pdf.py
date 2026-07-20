"""
PDF parser — extracts text prioritizing clean extraction over OCR.

Strategy: plain pymupdf FIRST, pymupdf4llm SECOND.
"""
from __future__ import annotations

import asyncio
import structlog

log = structlog.get_logger()

_MIN_CHARS_PER_PAGE = 100


def _extract_pymupdf(file_path: str) -> str | None:
    """Sync helper — ejecutado en thread pool para no bloquear el event loop."""
    import pymupdf

    doc = pymupdf.open(file_path)
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
    doc.close()

    text = "\n\n".join(pages)
    total_pages = len(pages) or 1
    avg_chars = len(text) / total_pages

    if avg_chars >= _MIN_CHARS_PER_PAGE:
        return text
    return None  # fallback needed


async def parse_pdf(file_path: str) -> str:
    """
    Extrae texto de un PDF.
    1. Intenta pymupdf plain text (limpio para PDFs basados en texto).
    2. Si el resultado es muy escaso, cae a pymupdf4llm (OCR para scans).
    """
    loop = asyncio.get_running_loop()

    # Estrategia 1: pymupdf texto plano — sin OCR, tablas limpias
    try:
        text = await loop.run_in_executor(None, _extract_pymupdf, file_path)
        if text is not None:
            log.info("pdf.parsed", method="pymupdf", path=file_path, chars=len(text))
            return text

        log.info("pdf.plain_insufficient", path=file_path, fallback="pymupdf4llm")

    except Exception as exc:
        log.warning("pdf.pymupdf_failed", error=str(exc), path=file_path)

    # Estrategia 2: pymupdf4llm — con OCR, para PDFs escaneados
    try:
        text = await loop.run_in_executor(None, _extract_ocr, file_path)
        log.info("pdf.parsed", method="pymupdf4llm", path=file_path, chars=len(text))
        return text

    except Exception as exc:
        log.error("pdf.parse_failed", error=str(exc), path=file_path)
        raise RuntimeError(f"No se pudo parsear el PDF: {exc}") from exc


def _extract_ocr(file_path: str) -> str:
    """Sync helper — pymupdf4llm con OCR, ejecutado en thread pool."""
    import pymupdf4llm
    return pymupdf4llm.to_markdown(file_path)
