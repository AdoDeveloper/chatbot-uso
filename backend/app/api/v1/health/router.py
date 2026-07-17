from __future__ import annotations

import time
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dates import since_until as _since_until
from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.health import (
    ComputeDevice, HealthDetailed, HealthHistoryEntry,
    HealthSnapshotResult, IncidentEntry, ServiceStatus, UptimeSummary,
)
from app.services.monitoring import health as health_history

log = structlog.get_logger()
router = APIRouter(prefix="/health", tags=["health"])
_admin = require_perm(P.SYSTEM_READ)


class LivenessResponse(BaseModel):
    """Confirmación simple de que el proceso de la app está vivo."""
    status: str = "ok"


class ReadinessResponse(BaseModel):
    """Estado de readiness del sistema completo (BD + Redis + Qdrant)."""
    status: str
    checks: dict[str, str]


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness probe — responde 200 si el proceso está vivo, sin tocar dependencias.

    Apto para Kubernetes liveness probe o para uptimers que solo quieren saber
    si el contenedor responde.
    """
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    """Readiness probe — verifica BD + Redis + Qdrant.

    Retorna 200 si todas las dependencias responden, 503 si alguna falla.
    Pensado para UptimeRobot / Healthchecks.io / Kubernetes readiness probe.
    """
    checks: dict[str, str] = {}
    all_ok = True

    # MySQL
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception as exc:
        log.warning("health.ready.mysql_error", error=str(exc))
        checks["mysql"] = "error"
        all_ok = False

    # Redis
    try:
        from app.core.redis import get_redis
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        log.warning("health.ready.redis_error", error=str(exc))
        checks["redis"] = "error"
        all_ok = False

    # Qdrant
    try:
        from app.services.ingestion.vector_store import _get_client
        await _get_client().get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        log.warning("health.ready.qdrant_error", error=str(exc))
        checks["qdrant"] = "error"
        all_ok = False

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if all_ok else "degraded",
        checks=checks,
    )


@router.get("/detailed", response_model=HealthDetailed)
async def health_detailed(_: object = Depends(_admin)):
    settings = get_settings()
    services: list[ServiceStatus] = []
    overall = "ok"

    t0 = time.monotonic()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        latency = int((time.monotonic() - t0) * 1000)
        services.append(ServiceStatus(name="MySQL", status="ok", latency_ms=latency))
    except Exception as exc:
        overall = "degraded"
        services.append(ServiceStatus(name="MySQL", status="error", detail=str(exc)[:128]))

    t0 = time.monotonic()
    try:
        from app.core.redis import get_redis
        r = get_redis()
        await r.ping()
        latency = int((time.monotonic() - t0) * 1000)
        services.append(ServiceStatus(name="Redis", status="ok", latency_ms=latency))
    except Exception as exc:
        overall = "degraded"
        services.append(ServiceStatus(name="Redis", status="error", detail=str(exc)[:128]))

    t0 = time.monotonic()
    try:
        from app.services.ingestion.vector_store import _get_client
        client = _get_client()
        await client.get_collections()
        latency = int((time.monotonic() - t0) * 1000)
        services.append(ServiceStatus(name="Qdrant", status="ok", latency_ms=latency))
    except Exception as exc:
        overall = "degraded"
        services.append(ServiceStatus(name="Qdrant", status="error", detail=str(exc)[:128]))

    try:
        from app.services.ai.embedding import embed_texts_async
        await embed_texts_async(["test"], prefix="query: ")
        services.append(ServiceStatus(name="Embedding Model", status="ok"))
    except Exception as exc:
        overall = "degraded"
        services.append(ServiceStatus(name="Embedding Model", status="error", detail=str(exc)[:128]))

    gpu_available = False
    embedding_device = "cpu"
    reranker_device = "cpu"
    try:
        import onnxruntime
        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            gpu_available = True
            embedding_device = "cuda"
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            gpu_available = True
            reranker_device = "cuda"
    except Exception:
        pass

    return HealthDetailed(
        status=overall,
        services=services,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        compute=ComputeDevice(
            embedding=embedding_device,
            reranker=reranker_device,
            gpu_available=gpu_available,
        ),
    )



@router.post("/snapshot", response_model=HealthSnapshotResult)
async def take_snapshot(
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Recolecta una muestra inmediata de todos los servicios y la persiste.

    Pensado para llamarse periódicamente (cron, background task externo, o
    auto-refresh del UI). Retorna el resultado de los checks.
    """
    return await health_history.collect_snapshot(db)


@router.get("/history", response_model=list[HealthHistoryEntry])
async def history(
    service: str | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Serie temporal de snapshots (default: últimas 24h). Filtrable por servicio."""
    return await health_history.get_history(db, service=service, hours=hours)


@router.get("/uptime", response_model=list[UptimeSummary])
async def uptime_summary(
    hours: int = Query(24, ge=1, le=168),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Por servicio: % uptime + P50/P95/P99 de latencia + último estado."""
    since, until = _since_until(date_from, date_to)
    return await health_history.get_uptime_summary(db, hours=hours, since=since, until=until)


@router.get("/incidents", response_model=list[IncidentEntry])
async def incidents(
    hours: int = Query(168, ge=1, le=720),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Lista de incidentes (rachas con is_ok=False) en los últimos N horas (default 7d)."""
    since, until = _since_until(date_from, date_to)
    return await health_history.get_incidents(db, hours=hours, since=since, until=until)
