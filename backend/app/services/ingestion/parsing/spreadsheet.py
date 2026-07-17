from __future__ import annotations

import structlog

log = structlog.get_logger()


async def parse_xlsx(file_path: str) -> str:
    """Convierte todas las hojas de un XLSX a Markdown."""
    try:
        import pandas as pd
        xls = pd.ExcelFile(file_path)
        parts: list[str] = []
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
            parts.append(f"## {sheet}\n\n{df.to_markdown(index=False)}")
        text = "\n\n".join(parts)
        log.info("xlsx.parsed", path=file_path, sheets=len(xls.sheet_names), chars=len(text))
        return text
    except Exception as exc:
        log.error("xlsx.parse_failed", error=str(exc))
        raise RuntimeError(f"No se pudo parsear el XLSX: {exc}") from exc


async def parse_csv(file_path: str) -> str:
    """Convierte un CSV a Markdown."""
    try:
        import pandas as pd
        df = pd.read_csv(file_path, dtype=str).fillna("")
        text = df.to_markdown(index=False)
        log.info("csv.parsed", path=file_path, rows=len(df), chars=len(text))
        return text
    except Exception as exc:
        log.error("csv.parse_failed", error=str(exc))
        raise RuntimeError(f"No se pudo parsear el CSV: {exc}") from exc
