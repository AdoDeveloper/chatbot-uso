"""Tests de la normalización del texto extraído.

Todo lo que sale de un parser pasa por aquí antes de trocearse y vectorizarse,
así que un artefacto que sobreviva degrada la búsqueda: un espacio duro en
"Artículo 1" impide que coincida con la consulta del usuario. Estos tests
cubren los artefactos reales de PDF y DOCX, y que la estructura que sí aporta
significado (tablas, encabezados, párrafos) no se pierda.
"""
from __future__ import annotations

from app.services.ingestion.parsing.normalize import normalizar_texto


class TestEspaciosInvisibles:
    def test_espacio_duro_pasa_a_espacio_normal(self):
        assert normalizar_texto("Artículo\xa01") == "Artículo 1"

    def test_espacios_unicode_exoticos_se_unifican(self):
        assert normalizar_texto("a b c") == "a b c"

    def test_marcas_invisibles_se_eliminan(self):
        assert normalizar_texto("CUM​ 7.0﻿") == "CUM 7.0"

    def test_espacios_repetidos_se_colapsan(self):
        assert normalizar_texto("Se  aplica     a todos") == "Se aplica a todos"


class TestCaracteresDeControl:
    def test_salto_de_pagina_se_elimina(self):
        assert normalizar_texto("Página uno\x0cPágina dos") == "Página unoPágina dos"

    def test_salto_y_tabulacion_se_conservan(self):
        assert normalizar_texto("a\nb\tc") == "a\nb\tc"


class TestEstructura:
    def test_saltos_excesivos_se_reducen_a_parrafo(self):
        assert normalizar_texto("Uno\n\n\n\n\nDos") == "Uno\n\nDos"

    def test_separacion_de_parrafos_se_respeta(self):
        assert normalizar_texto("Uno\n\nDos") == "Uno\n\nDos"

    def test_espacios_al_final_de_linea_se_quitan(self):
        assert normalizar_texto("Uno   \nDos") == "Uno\nDos"

    def test_encabezados_markdown_se_conservan(self):
        texto = "# Reglamento\n\n## Artículo 1\n\nContenido."
        assert normalizar_texto(texto) == texto


class TestTablas:
    def test_tabla_markdown_se_conserva_intacta(self):
        tabla = "| CUM | Modalidad |\n|---|---|\n| 8.0 | Pasantía |"
        assert normalizar_texto(tabla) == tabla

    def test_alineacion_interna_de_tabla_no_se_colapsa(self):
        """El espaciado dentro de una fila delimita columnas: colapsarlo
        rompería la lectura de la tabla."""
        tabla = "| CUM   | Modalidad |\n|-------|-----------|\n| 8.0   | Pasantía  |"
        assert normalizar_texto(tabla) == tabla


class TestArtefactosDePdf:
    def test_separador_de_pagina_se_elimina(self):
        assert normalizar_texto("Uno\n\n-----\n\nDos") == "Uno\n\nDos"

    def test_pie_de_pagina_se_elimina(self):
        assert normalizar_texto("Contenido\n\nPágina 3 de 12\n\nMás") == "Contenido\n\nMás"

    def test_numeracion_de_pagina_se_elimina(self):
        assert normalizar_texto("Contenido\n\n3 / 12\n\nMás") == "Contenido\n\nMás"

    def test_palabra_partida_por_guion_se_reconstruye(self):
        assert normalizar_texto("gradua-\nción") == "graduación"

    def test_guion_tipografico_pasa_a_guion_simple(self):
        assert normalizar_texto("8.0 – 8.9") == "8.0 - 8.9"

    def test_comillas_tipograficas_se_unifican(self):
        assert normalizar_texto("“Pasantía”") == '"Pasantía"'


class TestCasosLimite:
    def test_texto_vacio(self):
        assert normalizar_texto("") == ""

    def test_solo_espacios(self):
        assert normalizar_texto("   \n\n\t  ") == ""

    def test_texto_ya_limpio_no_cambia(self):
        texto = "Artículo 1. El presente reglamento se aplica a todos."
        assert normalizar_texto(texto) == texto

    def test_acentos_se_preservan(self):
        assert normalizar_texto("graduación, pasantía, inscripción") == "graduación, pasantía, inscripción"

    def test_extraccion_completa_de_pdf(self):
        """Caso integrado: los artefactos conviven en una misma extracción."""
        crudo = (
            "Artículo 1.\xa0 El presente\xa0reglamento\n\n\n\n"
            "Se aplica    a todos.\n\n-----\n\n"
            "| CUM | Modalidad |\n|---|---|\n| 8.0 | Pasantía |\n\n\n\n"
            "Página 1 de 12\x0c"
        )
        esperado = (
            "Artículo 1. El presente reglamento\n\n"
            "Se aplica a todos.\n\n"
            "| CUM | Modalidad |\n|---|---|\n| 8.0 | Pasantía |"
        )
        assert normalizar_texto(crudo) == esperado
