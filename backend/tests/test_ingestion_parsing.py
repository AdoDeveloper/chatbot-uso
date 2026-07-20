"""Tests unitarios puros para app/services/ingestion/parsing/.

Ningún test previo ejercitaba estos parsers directamente (docx.py tenía
~8% de cobertura) — todos los tests de ingestion pasan por el endpoint HTTP
completo, que mockea el parsing. Estos tests llaman las funciones de parsing
directamente con archivos reales (generados con python-docx / pandas) y no
requieren client/db_session ni MySQL.
"""
from __future__ import annotations

import pytest

from app.services.ingestion.parsing.docx import parse_docx
from app.services.ingestion.parsing.txt import parse_txt
from app.services.ingestion.parsing.spreadsheet import parse_csv, parse_xlsx
from app.services.ingestion.parsing.pdf import parse_pdf
from app.services.ingestion.parsing.dispatcher import parse_source
from app.models.enums import SourceType


# ── docx.py ──────────────────────────────────────────────────────────────

def _add_numbered_paragraph(doc, text: str, ilvl: int = 0) -> None:
    """python-docx no agrega w:numPr real solo con style='List Bullet'
    (el estilo por sí solo no basta — Word decide "es lista" por la
    presencia de w:numPr en w:pPr). Lo inyectamos a mano para simular
    una lista auto-numerada real de Word, que es lo que _detect_sections
    / parse_docx buscan."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    para = doc.add_paragraph(text)
    pPr = para._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl_el = OxmlElement("w:ilvl")
    ilvl_el.set(qn("w:val"), str(ilvl))
    numId_el = OxmlElement("w:numId")
    numId_el.set(qn("w:val"), "1")
    numPr.append(ilvl_el)
    numPr.append(numId_el)
    pPr.append(numPr)


def _make_docx(path: str) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("Título Principal", level=0)  # style "Title"
    doc.add_heading("Sección Uno", level=1)  # "Heading 1"
    doc.add_paragraph("Este es un párrafo normal.")

    bold_para = doc.add_paragraph()
    bold_run = bold_para.add_run("Texto en negrita completo")
    bold_run.bold = True

    _add_numbered_paragraph(doc, "Ítem de lista 1")
    _add_numbered_paragraph(doc, "Ítem de lista 2", ilvl=1)

    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "2"

    doc.add_paragraph("")  # párrafo vacío: debe ser omitido

    doc.save(path)


class TestParseDocx:
    async def test_extracts_heading_as_markdown(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        assert "# Título Principal" in text
        assert "## Sección Uno" in text

    async def test_extracts_plain_paragraph(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        assert "Este es un párrafo normal." in text

    async def test_bold_paragraph_becomes_markdown_bold(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        assert "**Texto en negrita completo**" in text

    async def test_list_items_become_markdown_list(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        assert "- Ítem de lista 1" in text
        assert "  - Ítem de lista 2" in text  # ilvl=1 → sangría de 2 espacios

    async def test_bold_list_item_becomes_bold_markdown_list(self, tmp_path):
        from docx import Document

        path = str(tmp_path / "bold_list.docx")
        doc = Document()
        para = doc.add_paragraph()
        run = para.add_run("Ítem en negrita")
        run.bold = True
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        pPr = para._p.get_or_add_pPr()
        numPr = OxmlElement("w:numPr")
        ilvl_el = OxmlElement("w:ilvl")
        ilvl_el.set(qn("w:val"), "0")
        numId_el = OxmlElement("w:numId")
        numId_el.set(qn("w:val"), "1")
        numPr.append(ilvl_el)
        numPr.append(numId_el)
        pPr.append(numPr)
        doc.save(path)

        text = await parse_docx(path)

        assert "**Ítem en negrita**" in text
        assert "- **Ítem en negrita**" not in text

    async def test_table_becomes_markdown_table(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        assert "| A | B |" in text
        assert "|---|---|" in text
        assert "| 1 | 2 |" in text

    async def test_empty_paragraphs_are_skipped(self, tmp_path):
        path = str(tmp_path / "doc.docx")
        _make_docx(path)

        text = await parse_docx(path)

        # No debe haber tres o más saltos de línea seguidos por un párrafo vacío colado
        assert "\n\n\n" not in text

    async def test_heading_es_variant_is_recognized(self, tmp_path):
        from docx import Document

        path = str(tmp_path / "doc_es.docx")
        doc = Document()
        para = doc.add_paragraph("Encabezado en español")
        para.style = doc.styles["Heading 1"]
        # Renombrar el estilo asignado para simular variante localizada
        # (python-docx no permite crear estilos "Título 1" fácilmente sin
        # una plantilla localizada, así que verificamos vía el diccionario
        # _HEADING_STYLES directamente en un test aparte)
        doc.save(path)

        text = await parse_docx(path)
        assert "## Encabezado en español" in text

    def test_heading_styles_dict_covers_es_variants(self):
        from app.services.ingestion.parsing.docx import _HEADING_STYLES

        assert _HEADING_STYLES["título"] == "#"
        assert _HEADING_STYLES["encabezado 1"] == "##"
        assert _HEADING_STYLES["título 2"] == "###"
        assert _HEADING_STYLES["encabezado 4"] == "#####"

    async def test_nonexistent_file_raises_runtime_error(self, tmp_path):
        path = str(tmp_path / "does_not_exist.docx")

        with pytest.raises(RuntimeError, match="No se pudo parsear el DOCX"):
            await parse_docx(path)

    async def test_corrupt_file_raises_runtime_error(self, tmp_path):
        path = str(tmp_path / "corrupt.docx")
        with open(path, "wb") as f:
            f.write(b"not a real docx file")

        with pytest.raises(RuntimeError, match="No se pudo parsear el DOCX"):
            await parse_docx(path)


# ── txt.py ───────────────────────────────────────────────────────────────

class TestParseTxt:
    async def test_reads_utf8_file(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("Hola  mundo con acentos: ñ, á, é", encoding="utf-8")

        text = await parse_txt(str(path))

        assert text == "Hola  mundo con acentos: ñ, á, é"

    async def test_strips_leading_trailing_whitespace(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("\n\n  contenido  \n\n", encoding="utf-8")

        text = await parse_txt(str(path))

        assert text == "contenido"

    async def test_falls_back_to_latin1_when_not_utf8(self, tmp_path):
        path = tmp_path / "file.txt"
        # 'ñ' en latin-1 no es UTF-8 válido en ese byte
        path.write_bytes("año de la señorita".encode("latin-1"))

        text = await parse_txt(str(path))

        assert "año de la señorita" == text

    async def test_missing_file_raises(self, tmp_path):
        path = tmp_path / "missing.txt"

        with pytest.raises(FileNotFoundError):
            await parse_txt(str(path))


# ── spreadsheet.py ───────────────────────────────────────────────────────

class TestParseCsv:
    async def test_converts_csv_to_markdown(self, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("nombre,edad\nAna,30\nLuis,25\n", encoding="utf-8")

        text = await parse_csv(str(path))

        assert "nombre" in text
        assert "Ana" in text
        assert "30" in text

    async def test_missing_file_raises_runtime_error(self, tmp_path):
        path = tmp_path / "missing.csv"

        with pytest.raises(RuntimeError, match="No se pudo parsear el CSV"):
            await parse_csv(str(path))


class TestParseXlsx:
    async def test_converts_all_sheets_to_markdown(self, tmp_path):
        import pandas as pd

        path = tmp_path / "data.xlsx"
        with pd.ExcelWriter(str(path)) as writer:
            pd.DataFrame({"col1": ["a", "b"], "col2": [1, 2]}).to_excel(
                writer, sheet_name="Hoja1", index=False
            )
            pd.DataFrame({"x": ["z"]}).to_excel(writer, sheet_name="Hoja2", index=False)

        text = await parse_xlsx(str(path))

        assert "## Hoja1" in text
        assert "## Hoja2" in text
        assert "col1" in text
        assert "z" in text

    async def test_missing_file_raises_runtime_error(self, tmp_path):
        path = tmp_path / "missing.xlsx"

        with pytest.raises(RuntimeError, match="No se pudo parsear el XLSX"):
            await parse_xlsx(str(path))


# ── pdf.py ───────────────────────────────────────────────────────────────

class TestParsePdf:
    async def test_uses_plain_pymupdf_when_text_sufficient(self, monkeypatch):
        from app.services.ingestion.parsing import pdf as pdf_mod

        monkeypatch.setattr(pdf_mod, "_extract_pymupdf", lambda path: "x" * 500)

        text = await pdf_mod.parse_pdf("fake.pdf")

        assert text == "x" * 500

    async def test_falls_back_to_ocr_when_plain_text_insufficient(self, monkeypatch):
        from app.services.ingestion.parsing import pdf as pdf_mod

        monkeypatch.setattr(pdf_mod, "_extract_pymupdf", lambda path: None)
        monkeypatch.setattr(pdf_mod, "_extract_ocr", lambda path: "contenido ocr")

        text = await pdf_mod.parse_pdf("fake.pdf")

        assert text == "contenido ocr"

    async def test_falls_back_to_ocr_when_plain_extraction_raises(self, monkeypatch):
        from app.services.ingestion.parsing import pdf as pdf_mod

        def boom(path):
            raise ValueError("corrupt pdf")

        monkeypatch.setattr(pdf_mod, "_extract_pymupdf", boom)
        monkeypatch.setattr(pdf_mod, "_extract_ocr", lambda path: "contenido ocr")

        text = await pdf_mod.parse_pdf("fake.pdf")

        assert text == "contenido ocr"

    async def test_raises_runtime_error_when_both_strategies_fail(self, monkeypatch):
        from app.services.ingestion.parsing import pdf as pdf_mod

        def boom(path):
            raise ValueError("corrupt pdf")

        monkeypatch.setattr(pdf_mod, "_extract_pymupdf", boom)
        monkeypatch.setattr(pdf_mod, "_extract_ocr", boom)

        with pytest.raises(RuntimeError, match="No se pudo parsear el PDF"):
            await pdf_mod.parse_pdf("fake.pdf")

    def test_extract_pymupdf_returns_none_below_min_chars_threshold(self, monkeypatch, tmp_path):
        """Ejercita _extract_pymupdf real (sin mock) contra un PDF real casi vacío."""
        import pymupdf
        from app.services.ingestion.parsing.pdf import _extract_pymupdf

        path = str(tmp_path / "empty.pdf")
        doc = pymupdf.open()
        doc.new_page()
        doc.save(path)
        doc.close()

        result = _extract_pymupdf(path)

        assert result is None

    def test_extract_pymupdf_returns_text_above_threshold(self, tmp_path):
        """Ejercita _extract_pymupdf real contra un PDF con suficiente texto."""
        import pymupdf
        from app.services.ingestion.parsing.pdf import _extract_pymupdf

        path = str(tmp_path / "full.pdf")
        doc = pymupdf.open()
        page = doc.new_page()
        long_text = "Lorem ipsum dolor sit amet. " * 20
        page.insert_text((72, 72), long_text)
        doc.save(path)
        doc.close()

        result = _extract_pymupdf(path)

        assert result is not None
        assert "Lorem ipsum" in result


# ── dispatcher.py ────────────────────────────────────────────────────────

class TestDispatcher:
    async def test_dispatches_txt(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("contenido de prueba", encoding="utf-8")

        text = await parse_source(SourceType.txt, str(path))

        assert text == "contenido de prueba"

    async def test_dispatches_csv(self, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")

        text = await parse_source(SourceType.csv, str(path))

        assert "a" in text and "b" in text

    async def test_unsupported_source_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Tipo de fuente no soportado"):
            await parse_source(SourceType.faq, "whatever.faq")

    async def test_missing_file_path_raises_value_error(self):
        with pytest.raises(ValueError, match="requiere file_path"):
            await parse_source(SourceType.txt, None)

        with pytest.raises(ValueError, match="requiere file_path"):
            await parse_source(SourceType.txt, "")
