from __future__ import annotations

import zipfile

import structlog

log = structlog.get_logger()

# Mitigación zip bomb: valida el tamaño descomprimido antes de invocar Document().
_MAX_DECOMPRESSED_RATIO = 100
_MAX_DECOMPRESSED_BYTES = 500 * 1024 * 1024  # 500MB, techo absoluto


def _check_zip_bomb(file_path: str) -> None:
    with zipfile.ZipFile(file_path) as zf:
        total_compressed = sum(info.compress_size for info in zf.infolist())
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed > _MAX_DECOMPRESSED_BYTES:
            raise ValueError(
                f"El documento se expande a {total_uncompressed / 1024 / 1024:.0f}MB "
                f"descomprimido, por encima del límite permitido."
            )
        if total_compressed > 0 and total_uncompressed / total_compressed > _MAX_DECOMPRESSED_RATIO:
            raise ValueError(
                "El documento tiene una tasa de compresión anormalmente alta "
                "(posible archivo corrupto o malicioso)."
            )

# Nombres de estilos de Word (variantes EN + ES) mapeados a nivel de encabezado markdown
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

# Párrafos de cuerpo con estilo de título por error de formato: tratados como
# encabezado, el fragmentador los descartaría por no tener contenido debajo.
_MAX_HEADING_CHARS = 150


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTAINERS = {"sdt", "sdtContent", "customXml", "smartTag"}
_DELETED = {"del", "moveFrom"}


def _local(el) -> str:
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def _blocks(container):
    """Párrafos y tablas en orden de lectura, incluidos los que están dentro de controles de contenido."""
    for child in container:
        name = _local(child)
        if name in ("p", "tbl"):
            yield name, child
        elif name in _CONTAINERS:
            yield from _blocks(child)


def _paragraph_text(p_el) -> tuple[str, list[str]]:
    """Texto visible del párrafo (incluye cambios insertados) y el de sus cuadros de texto aparte."""
    out: list[str] = []
    boxes: list[str] = []

    def walk(el):
        for child in el:
            name = _local(child)
            if name in _DELETED:
                continue
            if name == "txbxContent":
                box = "\n".join(t for t in (_paragraph_text(bp)[0].strip() for _, bp in _blocks(child)) if t)
                if box and box not in boxes:
                    boxes.append(box)
                continue
            if name == "t":
                out.append(child.text or "")
            elif name == "tab":
                out.append(" ")
            elif name in ("br", "cr"):
                out.append("\n")
            walk(child)

    walk(p_el)
    return "".join(out), boxes


def _cell_text(tc) -> str:
    parts: list[str] = []
    for kind, el in _blocks(tc):
        if kind == "p":
            text, boxes = _paragraph_text(el)
            parts += [t for t in (text.strip(), *boxes) if t]
        else:
            parts += ["; ".join(filter(None, (_cell_text(c) for c in row.findall(_W + "tc"))))
                      for row in el.findall(_W + "tr")]
    return " ".join(p.replace("\n", " ") for p in parts if p)


def _table_markdown(tbl) -> str:
    rows: list[str] = []
    for i, tr in enumerate(tbl.findall(_W + "tr")):
        cells = [_cell_text(tc).replace("|", "/") for tc in tr.findall(_W + "tc")]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("|" + "|".join(["---"] * len(cells)) + "|")
    return "\n".join(rows)


def _plain_blocks(container) -> list[str]:
    out: list[str] = []
    for kind, el in _blocks(container):
        if kind == "p":
            text, boxes = _paragraph_text(el)
            out += [t for t in (text.strip(), *boxes) if t]
        else:
            out.append(_table_markdown(el))
    return out


def _page_margins(doc, attr: str) -> list[str]:
    seen: list[str] = []
    for section in doc.sections:
        for part in (getattr(section, attr), getattr(section, f"first_page_{attr}"), getattr(section, f"even_page_{attr}")):
            if part.is_linked_to_previous and section is not doc.sections[0]:
                continue
            for text in _plain_blocks(part._element):
                if text not in seen:
                    seen.append(text)
    return seen


async def parse_docx(file_path: str) -> str:
    """Extrae texto de un archivo DOCX preservando estructura."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph

        _check_zip_bomb(file_path)
        doc = Document(file_path)
        parts: list[str] = []

        for tag, block in _blocks(doc.element.body):
            if tag == "tbl":
                table = _table_markdown(block)
                if table:
                    parts.append(table)
                continue

            para = Paragraph(block, doc)
            text, boxes = _paragraph_text(block)
            text = text.strip()
            parts.extend(boxes)
            if not text:
                continue

            style_name = (para.style.name or "").strip().lower() if para.style is not None else ""

            if style_name in _HEADING_STYLES and len(text) <= _MAX_HEADING_CHARS:
                parts.append(f"{_HEADING_STYLES[style_name]} {text}")
                continue

            pPr = block.find(qn("w:pPr"))
            is_list = False
            list_level = 0
            if pPr is not None:
                numPr = pPr.find(qn("w:numPr"))
                if numPr is not None:
                    ilvl = numPr.find(qn("w:ilvl"))
                    list_level = int(ilvl.get(qn("w:val"), "0")) if ilvl is not None else 0
                    is_list = True

            non_empty = [r for r in para.runs if r.text.strip()]
            all_bold = bool(non_empty) and all(r.bold for r in non_empty)
            if is_list:
                indent = "  " * list_level
                parts.append(f"{indent}**{text}**" if all_bold else f"{indent}- {text}")
            elif all_bold and "\n" not in text:
                parts.append(f"**{text}**")
            else:
                parts.append(text)

        body = "\n\n".join(parts)
        header = [t for t in _page_margins(doc, "header") if t not in body]
        footer = [t for t in _page_margins(doc, "footer") if t not in body]
        text = "\n\n".join([*header, body, *footer]).strip()
        log.info("docx.parsed", path=file_path, chars=len(text))
        return text

    except Exception as exc:
        log.error("docx.parse_failed", error=str(exc), path=file_path)
        raise RuntimeError(f"No se pudo parsear el DOCX: {exc}") from exc
