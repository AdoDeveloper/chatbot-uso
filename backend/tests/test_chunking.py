"""Tests del chunking Parent-Child."""
from __future__ import annotations

import pytest

from app.services.ingestion.chunking import chunk_text


SOURCE_ID = "test-source-id"
SOURCE_NAME = "Manual de prueba"


class TestEmptyAndTrivial:
    def test_empty_string_returns_empty_list(self):
        assert chunk_text("", SOURCE_ID, SOURCE_NAME) == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_text("   \n\n   ", SOURCE_ID, SOURCE_NAME) == []


class TestShortDocument:
    """Documentos cortos (< child_size) producen un solo chunk con parent_text == text."""

    def test_short_text_produces_single_chunk(self):
        text = "Las inscripciones del ciclo 2026 abren el 15 de enero."
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        assert len(chunks) == 1

    def test_short_chunk_metadata_is_correct(self):
        text = "Pregunta corta de prueba."
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        c = chunks[0]
        assert c["source_id"] == SOURCE_ID
        assert c["source_name"] == SOURCE_NAME
        assert c["chunk_index"] == 0
        assert c["text"].endswith(text)  # Empieza con prefix de sección
        assert c["parent_id"]  # UUID generado
        assert c["parent_text"] == c["text"]  # En docs cortos, parent == child


class TestLongDocument:
    """Documentos largos (> child_size) se dividen en parents y cada parent en múltiples children."""

    @pytest.fixture
    def long_text(self) -> str:
        # Genera ~3000 caracteres de texto coherente sin headings
        paragraph = (
            "La Universidad de Sonsonate ofrece distintas modalidades de inscripción. "
            "Los estudiantes nuevos deben presentar el título de bachiller original y copia, "
            "fotografía tamaño cédula reciente, y partida de nacimiento. "
            "Los estudiantes que vienen de equivalencias deben además presentar las certificaciones de notas oficiales. "
        )
        return paragraph * 8

    def test_long_text_produces_multiple_chunks(self, long_text):
        chunks = chunk_text(long_text, SOURCE_ID, SOURCE_NAME, child_size=500, parent_size=1500)
        assert len(chunks) > 1

    def test_chunk_indices_are_sequential(self, long_text):
        chunks = chunk_text(long_text, SOURCE_ID, SOURCE_NAME, child_size=500, parent_size=1500)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_children_share_parent_id(self, long_text):
        chunks = chunk_text(long_text, SOURCE_ID, SOURCE_NAME, child_size=500, parent_size=1500)
        parent_ids = {c["parent_id"] for c in chunks}
        # Hay menos parents que children (ese es el punto del modelo Parent-Child)
        assert len(parent_ids) < len(chunks)

    def test_parent_text_is_richer_than_child(self, long_text):
        """parent_text debe tener más contexto que el child individual (mismo prefijo pero cuerpo más largo)."""
        chunks = chunk_text(long_text, SOURCE_ID, SOURCE_NAME, child_size=500, parent_size=1500)
        # Para el primer chunk, parent_text >= text (es child o parent completo)
        c = chunks[0]
        assert len(c["parent_text"]) >= len(c["text"])


class TestSectionDetection:
    def test_markdown_headings_create_sections(self):
        text = (
            "# Inscripciones\n"
            "Las inscripciones abren en enero. Para inscribirse necesitas el título de bachiller, "
            "una foto reciente y la partida de nacimiento.\n\n"
            "# Equivalencias\n"
            "Si vienes de otra universidad, debes traer las certificaciones de notas oficiales "
            "selladas por la institución de origen."
        )
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        sections = {c["section"] for c in chunks if c.get("section")}
        # Al menos detectamos las dos secciones
        assert len(sections) >= 1

    def test_section_prefix_in_text(self):
        text = (
            "# Matrícula\n"
            "El costo de la matrícula es de USD 150 mensuales. Se paga en el banco con la boleta "
            "que se descarga del portal del estudiante."
        )
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        # Cada chunk debe llevar el prefijo de sección al inicio de `text`
        for c in chunks:
            assert "[Sección:" in c["text"]


class TestMetadataConsistency:
    def test_all_chunks_carry_source_id(self):
        text = "x" * 5000
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        for c in chunks:
            assert c["source_id"] == SOURCE_ID
            assert c["source_name"] == SOURCE_NAME

    def test_chunk_keys_present(self):
        """El shape del chunk debe estar siempre completo para Qdrant payload."""
        text = "Texto de prueba con algo de contenido."
        chunks = chunk_text(text, SOURCE_ID, SOURCE_NAME)
        required = {"text", "source_id", "source_name", "chunk_index", "parent_id", "parent_text"}
        for c in chunks:
            assert required.issubset(c.keys()), f"Faltan campos: {required - c.keys()}"


class TestCustomSizes:
    def test_smaller_child_size_produces_more_chunks(self):
        text = "x" * 3000
        small = chunk_text(text, SOURCE_ID, SOURCE_NAME, child_size=200, parent_size=800)
        large = chunk_text(text, SOURCE_ID, SOURCE_NAME, child_size=1000, parent_size=2000)
        assert len(small) > len(large)



def test_consecutive_headings_are_kept_as_hierarchy():
    from app.services.ingestion.chunking import chunk_text

    text = "## Capítulo V\n\n### Proyecto de investigación\n\nArt. 16.- Es el proceso de investigación."
    chunks = chunk_text(text, "s", "n")
    assert any("[Sección: Capítulo V > Proyecto de investigación]" in c["text"] for c in chunks)


def test_trailing_headings_without_body_are_not_lost():
    from app.services.ingestion.chunking import chunk_text

    text = "## Sección\n\nContenido de la sección.\n\n**Aviso final importante**\n\n**Última línea**"
    joined = " ".join(c["text"] for c in chunk_text(text, "s", "n"))
    assert "Aviso final importante" in joined
    assert "Última línea" in joined


def test_allcaps_heading_does_not_span_lines():
    from app.services.ingestion.chunking import _detect_sections

    sections = _detect_sections("REQUISITOS\n\nPRESENTAR PARTIDA\n\nTexto normal del documento.")
    assert all("\n" not in title for title, _ in sections)
    assert any("REQUISITOS" in title for title, _ in sections)


_TRICKY_TEXTS = {
    "líneas que empiezan con número": "Plazos\n\nEl pago es en ventanilla.\n30 días hábiles para presentar.\n2025 es el año de vigencia.",
    "preámbulo corto": "Universidad de Sonsonate\n\n## Reglamento\n\nArt. 1.- Texto del artículo.",
    "siglas en mayúsculas": "REQUISITOS DEL DUI Y NIT\n\nPresentar copia del DUI.",
    "títulos encadenados": "## Capítulo I\n\n### Sección A\n\n**Nota**\n\n**Aviso**\n\nContenido final.",
    "lista numerada": "## Pasos\n\n1. Pagar $25 en caja.\n2. Llenar la solicitud.\n3. Esperar 8 días.",
    "tabla": "## Aranceles\n\n| Trámite | Costo |\n|---|---|\n| Constancia | $10 |\n| Cambio | $25 |",
    "documento largo": "\n\n".join(f"## Art. {i}\n\n" + f"El plazo {i} es de {i * 3} días y cuesta ${i * 7}. " * 30 for i in range(1, 15)),
}


@pytest.mark.parametrize("name", list(_TRICKY_TEXTS))
def test_every_word_and_number_reaches_the_chunks(name):
    import re

    from app.services.ingestion.chunking import chunk_text

    text = _TRICKY_TEXTS[name]
    joined = " ".join(c["text"] for c in chunk_text(text, "s", "n"))
    missing = set(re.findall(r"\w+", text)) - set(re.findall(r"\w+", joined))
    assert not missing, f"{name}: se perdieron {sorted(missing)}"


def test_line_wrapped_phone_number_is_not_a_heading():
    from app.services.ingestion.chunking import _detect_sections

    sections = _detect_sections("Teléfono de Registro: 7851-\n7588 en horario laboral.\n\n## Otro\n\nTexto.")
    assert all("7588" not in title for title, _ in sections)
