"""
PDF parser - extracts text prioritizing layout-aware extraction over plain text.

Strategy: pymupdf4llm.markdown FIRST (layout-aware, multi-column, tables),
          pymupdf4llm.markdown + force_ocr SECOND (scanned PDFs).
"""
from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger()


async def parse_pdf(file_path: str) -> str:
    """
    Extrae texto de un PDF con pymupdf4llm (layout-aware).
    Estrategia 1: markdown sin forzar OCR (para PDFs digitales con texto limpio).
    Estrategia 2: markdown con OCR forzado (para PDFs escaneados).
    """
    loop = asyncio.get_running_loop()
    import pymupdf4llm

    try:
        text = await loop.run_in_executor(
            None,
            lambda: pymupdf4llm.to_markdown(file_path, force_text=True),
        )
        if text and text.strip():
            log.info("pdf.parsed", method="pymupdf4llm", path=file_path, chars=len(text))
            return text
        log.info("pdf.empty_output", path=file_path, fallback="ocr")
    except Exception as exc:
        log.warning("pdf.layout_extract_failed", error=str(exc), path=file_path)

    try:
        text = await loop.run_in_executor(
            None,
            lambda: pymupdf4llm.to_markdown(file_path, force_text=False),
        )
        log.info("pdf.parsed", method="pymupdf4llm+ocr", path=file_path, chars=len(text))
        return text
    except Exception as exc:
        log.error("pdf.parse_failed", error=str(exc), path=file_path)
        raise RuntimeError(f"No se pudo parsear el PDF: {exc}") from exc
