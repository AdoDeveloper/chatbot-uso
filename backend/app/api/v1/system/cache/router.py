"""Cache management endpoints — view stats, list entries, clear, configure."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.schemas.common import DeletedCount, OperationStatus
from app.services.ai import semantic_cache as cache_svc

router = APIRouter(prefix="/cache", tags=["system:cache"])
_reader = require_perm(P.SYSTEM_READ)
_admin  = require_perm(P.SYSTEM_MANAGE)


class CacheStats(BaseModel):
    total_entries: int
    enabled: bool
    ttl_seconds: int
    similarity_threshold: float


class CacheEntry(BaseModel):
    key: str
    question: str


class CacheConfigUpdate(BaseModel):
    enabled: bool | None = None
    ttl_seconds: int | None = None
    similarity_threshold: float | None = None


@router.get("/stats", response_model=CacheStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(_reader),
):
    count = await cache_svc.count_entries()
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    return CacheStats(
        total_entries=count,
        enabled=overrides["semantic_cache_enabled"],
        ttl_seconds=overrides["semantic_cache_ttl"],
        similarity_threshold=overrides["semantic_cache_threshold"],
    )


@router.get("/entries", response_model=list[CacheEntry])
async def list_entries(
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(_reader),
):
    entries = await cache_svc.list_entries(limit=page_size)
    return [CacheEntry(key=e["key"], question=e["question"]) for e in entries]


@router.delete("/clear", response_model=DeletedCount)
async def clear_cache(_=Depends(_admin)) -> DeletedCount:
    """Vacía todo el caché semántico. Devuelve el número de entradas borradas."""
    deleted = await cache_svc.clear_all()
    return DeletedCount(deleted=deleted)


@router.delete("/entry/{key}", response_model=OperationStatus)
async def delete_entry(key: str, _=Depends(_admin)) -> OperationStatus:
    """Borra una entrada específica del caché por su key Redis."""
    await cache_svc.delete_entry(key)
    return OperationStatus()


@router.patch("/config", response_model=OperationStatus)
async def update_config(
    body: CacheConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
) -> OperationStatus:
    """Actualiza la configuración del caché semántico (TTL, threshold, on/off)."""
    updates = {}
    if body.enabled is not None:
        updates["semantic_cache_enabled"] = body.enabled
    if body.ttl_seconds is not None:
        updates["semantic_cache_ttl"] = body.ttl_seconds
    if body.similarity_threshold is not None:
        updates["semantic_cache_threshold"] = body.similarity_threshold
    if updates:
        from app.models.global_setting import GlobalSetting
        from app.services.system.settings import invalidate_runtime_overrides
        for k, v in updates.items():
            await db.merge(GlobalSetting(key=k, value=v))
        await db.commit()
        invalidate_runtime_overrides()
    return OperationStatus()
