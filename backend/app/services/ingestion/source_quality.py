"""Helpers de calidad para Sources.

Funciones puras que viven separadas del pipeline de ingesta para que la UI
admin pueda inspeccionar/explicar el estado de cualquier fuente sin reejecutar.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession



def file_hash(content: bytes) -> str:
    """SHA-256 hex del archivo. Usado para detectar uploads duplicados."""
    return hashlib.sha256(content).hexdigest()



_ERROR_PATTERNS: list[tuple[str, str, str, str]] = [
    # (substring/keyword en lower, code, mensaje legible, hint)
    ("password", "PDF_ENCRYPTED", "El PDF está protegido con contraseña.",
     "Quita la protección del PDF y vuelve a subirlo."),
    ("encrypted", "PDF_ENCRYPTED", "El archivo está cifrado.",
     "Desbloquea el archivo antes de subirlo."),
    ("not a pdf", "INVALID_PDF", "El archivo no es un PDF válido.",
     "Verifica que el archivo sea un PDF y no esté corrupto."),
    ("openai", "EMBEDDING_ERROR", "Error en el modelo de embeddings.",
     "Verifica conectividad a OpenAI/Groq y que la API key sea válida."),
    ("qdrant", "VECTOR_STORE_ERROR", "Error escribiendo en el almacén vectorial.",
     "Revisa que Qdrant esté arriba (Sistema → Estado)."),
    ("memory", "OUT_OF_MEMORY", "Sin memoria suficiente para procesar el archivo.",
     "El archivo es muy grande. Divídelo o aumenta los recursos del worker."),
    ("token", "TOO_MANY_TOKENS", "El documento excede el límite de tokens.",
     "Sube un documento más corto o aumenta `max_chars` por chunk."),
    ("encoding", "ENCODING_ERROR", "Codificación de archivo no soportada.",
     "Guarda el archivo en UTF-8 antes de subirlo."),
    ("xlsx", "XLSX_PARSE_ERROR", "El archivo Excel tiene un formato no estándar.",
     "Re-exporta el Excel desde la fuente original."),
]


def classify_error(message: str | None) -> tuple[str | None, str | None, str | None]:
    """Dado un mensaje de error crudo, retorna (code, friendly_message, hint).

    Si no hay patrón, devuelve (None, message, None) — la UI mostrará el
    mensaje crudo, pero al menos no lanza "error" sin más.
    """
    if not message:
        return None, None, None
    low = message.lower()
    for substring, code, friendly, hint in _ERROR_PATTERNS:
        if substring in low:
            return code, friendly, hint
    return None, message, None



async def quality_report(db: AsyncSession, source_id) -> dict:
    """Resumen de calidad de chunks: cobertura, longitud promedio, warnings.

    Datos:
    - total_chunks
    - avg_chars: promedio de longitud por chunk
    - short_chunks: <100 chars
    - long_chunks: >2000 chars
    - last_used_at: última vez que un chunk fue recuperado (chat_messages.sources_json)
    """
    from app.models.source import Source
    from app.models.chat_message import ChatMessage

    # No tenemos tabla de chunks SQL (viven en Qdrant). Aproximamos via campos del Source.
    source = await db.get(Source, source_id)
    if not source:
        return {"error": "Source no encontrada"}

    sid = str(source.id)

    def _matches(srcs: list) -> bool:
        for s in srcs:
            if not isinstance(s, dict):
                continue
            if s.get("source_id"):
                if s["source_id"] == sid:
                    return True
            elif s.get("source_name") == source.name:
                return True
        return False

    last_used: datetime | None = None
    try:
        rows = await db.execute(
            select(ChatMessage.created_at, ChatMessage.sources_json)
            .where(ChatMessage.sources_json.is_not(None))
            .order_by(ChatMessage.created_at.desc())
            .limit(500)
        )
        for created_at, sources in rows.all():
            if _matches(sources if isinstance(sources, list) else []):
                last_used = created_at
                break
    except Exception:
        last_used = None

    # Hits en últimos 7 días
    hits_7d = 0
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        rows_7d = await db.execute(
            select(ChatMessage.sources_json)
            .where(ChatMessage.created_at >= since)
            .where(ChatMessage.sources_json.is_not(None))
        )
        for (sources,) in rows_7d.all():
            if _matches(sources if isinstance(sources, list) else []):
                hits_7d += 1
    except Exception:
        hits_7d = 0

    return {
        "source_id": str(source.id),
        "name": source.name,
        "total_chunks": source.chunk_count,
        "last_used_at": last_used.isoformat() if last_used else None,
        "hits_7d": hits_7d,
        "review_status": source.review_status.value if hasattr(source.review_status, "value") else str(source.review_status),
    }


async def find_duplicate(db: AsyncSession, content_hash: str, exclude_id=None):
    """Devuelve la primera Source con el mismo `content_hash` (no eliminada)."""
    from app.models.source import Source
    q = select(Source).where(Source.content_hash == content_hash).where(Source.deleted_at.is_(None))
    if exclude_id is not None:
        q = q.where(Source.id != exclude_id)
    result = await db.execute(q.limit(1))
    return result.scalar_one_or_none()
