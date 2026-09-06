"""Normalización del texto extraído, común a todos los formatos."""
from __future__ import annotations

import re
import unicodedata

# Espacios Unicode que el buscador no equipara con un espacio normal: si
# "Artículo 1" trae un espacio duro, la consulta del usuario no coincide.
_ESPACIOS_UNICODE = dict.fromkeys(
    [
        0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005,
        0x2006, 0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000,
    ],
    " ",
)

# Marcas invisibles que llegan de PDF y de texto copiado de la web.
_INVISIBLES = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF], None)

_GUIONES = dict.fromkeys([0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212], "-")
_COMILLAS = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'}

_TRADUCCIONES = {**_ESPACIOS_UNICODE, **_INVISIBLES, **_GUIONES, **_COMILLAS}

_SEPARADOR_PAGINA = re.compile(r"^[-–—_*=]{3,}$", re.MULTILINE)
_PIE_PAGINA = re.compile(r"^\s*(?:P[áa]gina\s+\d+(?:\s+de\s+\d+)?|\d+\s*/\s*\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_ESPACIOS_REPETIDOS = re.compile(r"[ \t]{2,}")
_ESPACIO_ANTES_SALTO = re.compile(r"[ \t]+\n")
_SALTOS_EXCESIVOS = re.compile(r"\n{3,}")
_GUION_CORTE = re.compile(r"(\w)-\n(\w)")


def _es_fila_de_tabla(linea: str) -> bool:
    return linea.lstrip().startswith("|")


def normalizar_texto(texto: str) -> str:
    """Limpia artefactos de extracción preservando la estructura del documento.

    Quita caracteres de control e invisibles, unifica espacios y guiones
    tipográficos, junta palabras partidas por guion al final de línea y
    elimina separadores y pies de página. Respeta las tablas Markdown, cuyo
    espaciado interno delimita las columnas.
    """
    if not texto:
        return ""

    texto = unicodedata.normalize("NFC", texto)
    texto = texto.translate(_TRADUCCIONES)

    # Los caracteres de control no aportan nada y ensucian el vector; se
    # conservan salto de línea y tabulación.
    texto = "".join(
        c for c in texto
        if c in "\n\t" or unicodedata.category(c) != "Cc"
    )

    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _GUION_CORTE.sub(r"\1\2", texto)
    texto = _SEPARADOR_PAGINA.sub("", texto)
    texto = _PIE_PAGINA.sub("", texto)

    lineas = [
        linea if _es_fila_de_tabla(linea) else _ESPACIOS_REPETIDOS.sub(" ", linea)
        for linea in texto.split("\n")
    ]
    texto = "\n".join(lineas)

    texto = _ESPACIO_ANTES_SALTO.sub("\n", texto)
    texto = _SALTOS_EXCESIVOS.sub("\n\n", texto)

    return texto.strip()
