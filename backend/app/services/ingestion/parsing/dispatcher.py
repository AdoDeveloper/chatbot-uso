from __future__ import annotations

from app.models.enums import SourceType
from app.services.ingestion.parsing.pdf import parse_pdf
from app.services.ingestion.parsing.docx import parse_docx
from app.services.ingestion.parsing.spreadsheet import parse_csv, parse_xlsx
from app.services.ingestion.parsing.txt import parse_txt

_PARSERS = {
    SourceType.pdf: parse_pdf,
    SourceType.docx: parse_docx,
    SourceType.xlsx: parse_xlsx,
    SourceType.csv: parse_csv,
    SourceType.txt: parse_txt,
}


async def parse_source(source_type: SourceType, file_path: str | None) -> str:
    """Despacha al parser correcto según el tipo de fuente."""
    parser = _PARSERS.get(source_type)
    if parser is None:
        raise ValueError(f"Tipo de fuente no soportado: {source_type}")
    if not file_path:
        raise ValueError(f"{source_type.value.upper()} requiere file_path")
    return await parser(file_path)
