"""Endpoints de mantenimiento del sistema."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.health_snapshot import HealthSnapshot
from app.models.user import User
from app.services.ingestion.qdrant_sync import sync_qdrant as sync_qdrant_svc
from app.services.system import audit as audit_svc

log = structlog.get_logger()
router = APIRouter(prefix="/maintenance", tags=["system:maintenance"])
_admin = require_perm(P.SYSTEM_MANAGE)


class QdrantSyncResult(BaseModel):
    """Resultado del sync Qdrant ↔ MySQL."""
    qdrant_chunks_total: int
    valid_source_ids: int
    orphan_chunks_deleted: int
    cache_invalidated_count: int


@router.post("/sync-qdrant", response_model=QdrantSyncResult)
async def sync_qdrant(
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
) -> QdrantSyncResult:
    """Limpia chunks huérfanos en Qdrant (source_id sin fuente activa en MySQL)."""
    result = await sync_qdrant_svc(db)
    await audit_svc.log_action(
        db,
        action="maintenance.sync_qdrant",
        resource_type="system",
        actor_id=current_user.id,
        meta=result,
        ip=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    await db.commit()
    return QdrantSyncResult(**result)


class PurgeHealthResult(BaseModel):
    deleted: int
    threshold_ms: int


@router.delete("/health-snapshots/outliers", response_model=PurgeHealthResult)
async def purge_health_outliers(
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
) -> PurgeHealthResult:
    """Elimina snapshots de salud con latencias anómalas (> 2 s).

    Útil cuando el historial acumula mediciones del arranque inicial o de
    momentos de caída severa que distorsionan los percentiles P95/P99.
    """
    threshold = 2_000
    result = await db.execute(
        delete(HealthSnapshot).where(HealthSnapshot.latency_ms > threshold)
    )
    deleted = result.rowcount or 0
    await audit_svc.log_action(
        db,
        action="maintenance.purge_health_outliers",
        resource_type="system",
        actor_id=current_user.id,
        meta={"deleted": deleted, "threshold_ms": threshold},
        ip=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    await db.commit()
    log.info("maintenance.purge_health_outliers", deleted=deleted, threshold_ms=threshold)
    return PurgeHealthResult(deleted=deleted, threshold_ms=threshold)
