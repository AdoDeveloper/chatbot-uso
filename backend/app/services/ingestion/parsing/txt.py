from __future__ import annotations

import structlog

log = structlog.get_logger()


async def parse_txt(file_path: str) -> str:
    """Extrae texto de un archivo .txt con detección automática de encoding."""
    import aiofiles

    for encoding in ("utf-8", "latin-1"):
        try:
            async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
                text = await f.read()
            text = text.strip()
            log.info("txt.parsed", path=file_path, chars=len(text), encoding=encoding)
            return text
        except UnicodeDecodeError:
            continue

    raise RuntimeError("No se pudo leer el archivo TXT: encoding no soportado")
