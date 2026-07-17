from __future__ import annotations

import structlog

log = structlog.get_logger()

# Word style names (EN + ES variants) mapped to markdown heading level
_HEADING_STYLES: dict[str, str] = {
    "title":       "#",
    "título":      "#",
    "heading 1":   "##",
    "encabezado 1": "##",
    "título 1":    "##",
    "heading 2":   "###",
    "encabezado 2": "###",
    "título 2":    "###",
    "heading 3":   "####",
    "encabezado 3": "####",
    "título 3":    "####",
    "heading 4":   "#####",
    "encabezado 4": "#####",
    "título 4":    "#####",
}


async def parse_docx(file_path: str) -> str:
    """
    Extrae texto de un archivo DOCX preservando estructura:
    - Headings  → ## / ### / ####  (para que _detect_sections los reconozca)
    - Párrafos completamente en negrita → **texto** (títulos de sección sin estilo)
    - Listas auto-numeradas de Word  → - ítem  (con sangría por nivel)
    - Tablas → representación Markdown
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(file_path)
        parts: list[str] = []

        for block in doc.element.body:
            tag = block.tag.split("}")[-1]

            if tag == "p":
                para = Paragraph(block, doc)
                text = para.text.strip()
                if not text:
                    continue

                style_name = (para.style.name or "").strip().lower()

                if style_name in _HEADING_STYLES:
                    parts.append(f"{_HEADING_STYLES[style_name]} {text}")
                    continue

                pPr = para._p.find(qn("w:pPr"))
                is_list = False
                list_level = 0
                if pPr is not None:
                    numPr = pPr.find(qn("w:numPr"))
                    if numPr is not None:
                        ilvl = numPr.find(qn("w:ilvl"))
                        list_level = int(ilvl.get(qn("w:val"), "0")) if ilvl is not None else 0
                        is_list = True

                if is_list:
                    indent = "  " * list_level
                    non_empty = [r for r in para.runs if r.text.strip()]
                    if non_empty and all(r.bold for r in non_empty):
                        parts.append(f"{indent}**{text}**")
                    else:
                        parts.append(f"{indent}- {text}")
                    continue

                # ── 3. Párrafo completamente en negrita → título de sección
                non_empty = [r for r in para.runs if r.text.strip()]
                if non_empty and all(r.bold for r in non_empty):
                    parts.append(f"**{text}**")
                    continue

                parts.append(text)

            elif tag == "tbl":
                tbl = Table(block, doc)
                rows: list[str] = []
                for i, row in enumerate(tbl.rows):
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    rows.append("| " + " | ".join(cells) + " |")
                    if i == 0:
                        rows.append("|" + "|".join(["---"] * len(cells)) + "|")
                if rows:
                    parts.append("\n".join(rows))

        text = "\n\n".join(parts)
        log.info("docx.parsed", path=file_path, chars=len(text))
        return text

    except Exception as exc:
        log.error("docx.parse_failed", error=str(exc), path=file_path)
        raise RuntimeError(f"No se pudo parsear el DOCX: {exc}") from exc
