from __future__ import annotations

import structlog

log = structlog.get_logger()

# Por encima de este ratio de caracteres de control, el contenido no es texto legítimo.
_MAX_CONTROL_CHAR_RATIO = 0.05


def _looks_like_binary(text: str) -> bool:
    if not text:
        return False
    control = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    return (control / len(text)) > _MAX_CONTROL_CHAR_RATIO


async def parse_txt(file_path: str) -> str:
    """Extrae texto de un archivo .txt con detección automática de encoding."""
    import aiofiles

    for encoding in ("utf-8", "latin-1"):
        try:
            async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
                text = await f.read()
        except UnicodeDecodeError:
            continue
        text = text.strip()
        if _looks_like_binary(text):
            # latin-1 "decodificó" con éxito pero el contenido es binario.
            break
        log.info("txt.parsed", path=file_path, chars=len(text), encoding=encoding)
        return text

    raise RuntimeError("No se pudo leer el archivo TXT: el contenido no parece texto legible")
