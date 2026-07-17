"""Schemas reutilizables compartidos entre routers."""
from __future__ import annotations

from pydantic import BaseModel


class OperationStatus(BaseModel):
    """Estado genérico de una operación mutating (toggle, clear, reset, patch sin entidad)."""
    ok: bool = True
    message: str | None = None


class DeletedCount(BaseModel):
    """Número de filas afectadas por una operación de borrado masivo."""
    deleted: int


class BulkItemError(BaseModel):
    """Un item que falló dentro de una operación bulk."""
    name: str
    error: str


class BulkUploadResult(BaseModel):
    """Resultado de un upload masivo: items creados + items que fallaron."""
    created: list[dict]          # [{id: str, name: str}]
    errors: list[BulkItemError]


class BulkQueueResult(BaseModel):
    """Resultado de encolar operaciones en background (reingest, re-embed…)."""
    queued: int
