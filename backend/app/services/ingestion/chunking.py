from __future__ import annotations

"""
Context-aware chunking with Parent-Child retrieval.

Strategy: section detection → child chunks (256 tokens ≈ 1024 chars) for
precise embedding retrieval → parent chunks (1000 tokens ≈ 4000 chars) for
rich LLM context.

Why Parent-Child:
  - Child chunks are small enough for embedding models (e5-large 512 token limit)
    to produce focused semantic representations.
  - Parent chunks give the LLM enough surrounding context to generate
    coherent, complete answers.
  - At retrieval time: embed & search children, but return the parent to the LLM.

Public API:
  chunk_text(text, source_id, source_name) -> list[dict]
"""

import re
import uuid

import structlog
from langchain_text_splitters import RecursiveCharacterTextSplitter

log = structlog.get_logger()

DEFAULT_PARENT_CHUNK_SIZE = 4000
DEFAULT_PARENT_CHUNK_OVERLAP = 200
DEFAULT_CHILD_CHUNK_SIZE = 1024
DEFAULT_CHILD_CHUNK_OVERLAP = 128

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _make_splitters(
    parent_size: int = DEFAULT_PARENT_CHUNK_SIZE,
    parent_overlap: int = DEFAULT_PARENT_CHUNK_OVERLAP,
    child_size: int = DEFAULT_CHILD_CHUNK_SIZE,
    child_overlap: int = DEFAULT_CHILD_CHUNK_OVERLAP,
) -> tuple[RecursiveCharacterTextSplitter, RecursiveCharacterTextSplitter]:
    parent = RecursiveCharacterTextSplitter(
        chunk_size=parent_size, chunk_overlap=parent_overlap,
        length_function=len, separators=_SEPARATORS,
    )
    child = RecursiveCharacterTextSplitter(
        chunk_size=child_size, chunk_overlap=child_overlap,
        length_function=len, separators=_SEPARATORS,
    )
    return parent, child

_SECTION_PATTERNS = [
    re.compile(r"^(#{2,4})\s+(.+)$", re.MULTILINE),
    re.compile(r"^(\d+(?:\.\d+)*\.?)\s+\**(.+?)\**\s*$", re.MULTILINE),
    re.compile(r"^\*\*(.+?)\*\*\s*$", re.MULTILINE),
]


_ALLCAPS_PATTERN = re.compile(r"^([A-ZÁÉÍÓÚÑÜ\s]{4,})$", re.MULTILINE)


def _detect_sections(text: str) -> list[tuple[str, str]]:
    headings: list[tuple[int, str]] = []

    for pattern in _SECTION_PATTERNS:
        for match in pattern.finditer(text):
            if match.lastindex is None:
                continue
            title = match.group(match.lastindex).strip().strip("*").strip()
            if len(title) > 2:
                headings.append((match.start(), title))

    for match in _ALLCAPS_PATTERN.finditer(text):
        title = match.group(1).strip().title()
        if len(title) > 3 and not title.isdigit():
            headings.append((match.start(), title))

    if not headings:
        return [("General", text)]

    headings.sort(key=lambda h: h[0])
    headings = _deduplicate_headings(headings)

    sections: list[tuple[str, str]] = []

    first_pos = headings[0][0]
    if first_pos > 0:
        preamble = text[:first_pos].strip()
        if len(preamble) > 50:
            sections.append(("General", preamble))

    for i, (pos, title) in enumerate(headings):
        body_end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        body = text[pos:body_end]
        body_lines = body.split("\n", 1)
        body = body_lines[1].strip() if len(body_lines) > 1 else ""
        if body:
            sections.append((title, body))

    return sections if sections else [("General", text)]


def _deduplicate_headings(
    headings: list[tuple[int, str]], min_distance: int = 20
) -> list[tuple[int, str]]:
    if not headings:
        return headings
    result = [headings[0]]
    for pos, title in headings[1:]:
        if pos - result[-1][0] < min_distance:
            if len(title) > len(result[-1][1]):
                result[-1] = (pos, title)
        else:
            result.append((pos, title))
    return result


def chunk_text(
    text: str,
    source_id: str,
    source_name: str,
    *,
    parent_size: int = DEFAULT_PARENT_CHUNK_SIZE,
    parent_overlap: int = DEFAULT_PARENT_CHUNK_OVERLAP,
    child_size: int = DEFAULT_CHILD_CHUNK_SIZE,
    child_overlap: int = DEFAULT_CHILD_CHUNK_OVERLAP,
) -> list[dict]:
    """
    Divide el texto en chunks Parent-Child listos para indexar.

    Los parámetros de tamaño son configurables desde GlobalSetting.
    """
    if not text or not text.strip():
        return []

    parent_splitter, child_splitter = _make_splitters(
        parent_size, parent_overlap, child_size, child_overlap,
    )

    sections = _detect_sections(text)
    all_chunks: list[dict] = []
    chunk_index = 0

    for section_title, section_body in sections:
        context_prefix = f"[Sección: {section_title}]\n"

        if len(section_body) <= child_size:
            parent_id = str(uuid.uuid4())
            parent_text = context_prefix + section_body
            all_chunks.append({
                "text": parent_text,
                "source_id": source_id,
                "source_name": source_name,
                "chunk_index": chunk_index,
                "section": section_title,
                "parent_id": parent_id,
                "parent_text": parent_text,
            })
            chunk_index += 1
        else:
            parents = parent_splitter.split_text(section_body)
            for pi, parent_body in enumerate(parents):
                parent_id = str(uuid.uuid4())
                parent_prefix = f"[Sección: {section_title}]\n"
                parent_text = parent_prefix + parent_body

                children = child_splitter.split_text(parent_body)
                for ci, child_body in enumerate(children):
                    child_prefix = (
                        f"[Sección: {section_title} | Parte {pi + 1}/{len(parents)}, "
                        f"Fragmento {ci + 1}/{len(children)}]\n"
                    )
                    all_chunks.append({
                        "text": child_prefix + child_body,
                        "source_id": source_id,
                        "source_name": source_name,
                        "chunk_index": chunk_index,
                        "section": section_title,
                        "parent_id": parent_id,
                        "parent_text": parent_text,
                    })
                    chunk_index += 1

    log.info(
        "chunking.done",
        source_id=source_id,
        total_chars=len(text),
        sections=len(sections),
        chunks=len(all_chunks),
    )
    return all_chunks
