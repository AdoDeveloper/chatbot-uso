"""Servicio de historial de salud. Recolecta muestras y deriva incidentes."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select


def _pct(data: list[float], p: float) -> float:
    """Percentil p (0-1) sobre una lista ya ordenada ascendentemente."""
    if not data:
        return 0.0
    n = len(data)
    k = (n - 1) * p
    lo, hi = int(k), min(int(k) + 1, n - 1)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.health_snapshot import HealthSnapshot

log = structlog.get_logger()


# Lista de checks que ejecuta el recolector. Cada tupla es (nombre, función async que devuelve (ok, latency_ms, error))
async def _check_database():
    from sqlalchemy import text
    t0 = time.monotonic()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True, int((time.monotonic() - t0) * 1000), None
    except Exception as exc:
        return False, None, str(exc)[:200]


async def _check_redis():
    try:
        from app.core.redis import get_redis
        t0 = time.monotonic()
        await get_redis().ping()
        return True, int((time.monotonic() - t0) * 1000), None
    except Exception as exc:
        return False, None, str(exc)[:200]


async def _check_qdrant():
    try:
        from app.services.ingestion.vector_store import _get_client
        t0 = time.monotonic()
        await _get_client().get_collections()
        return True, int((time.monotonic() - t0) * 1000), None
    except Exception as exc:
        return False, None, str(exc)[:200]


_CHECKS = {
    "MySQL": _check_database,
    "Redis": _check_redis,
    "Qdrant": _check_qdrant,
}


def _read_resource_utilization() -> tuple[float | None, float | None, float | None]:
    """CPU, RAM y disco en %. Si psutil no está, retorna None."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        return cpu, mem, disk
    except Exception:
        return None, None, None


async def collect_snapshot(db: AsyncSession) -> dict:
    """Ejecuta todos los checks y persiste una fila por servicio.

    Tras persistir, dispara el chequeo proactivo de `service_down` para emitir
    notificaciones si una racha de fallos lo amerita.
    """
    cpu, mem, disk = _read_resource_utilization()
    results: dict[str, dict] = {}
    for name, fn in _CHECKS.items():
        ok, latency, error = await fn()
        snap = HealthSnapshot(
            service_name=name,
            is_ok=ok,
            latency_ms=latency,
            error=error,
            cpu_percent=cpu, mem_percent=mem, disk_percent=disk,
        )
        db.add(snap)
        results[name] = {
            "ok": ok, "latency_ms": latency, "error": error,
        }
    await db.commit()

    # tras cada snapshot, evaluar si alguna racha amerita alerta
    try:
        from app.services.monitoring.alerts import check_service_down
        await check_service_down(db)
    except Exception as exc:
        log.warning("alerts.service_down_check_failed", error=str(exc))

    return {
        "services": results,
        "cpu_percent": cpu, "mem_percent": mem, "disk_percent": disk,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_history(db: AsyncSession, *, service: str | None = None, hours: int = 24) -> list[dict]:
    """Serie temporal de las últimas N horas. Devuelve los snapshots crudos."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = select(HealthSnapshot).where(HealthSnapshot.recorded_at >= since)
    if service:
        q = q.where(HealthSnapshot.service_name == service)
    q = q.order_by(HealthSnapshot.recorded_at.asc())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "service_name": r.service_name,
            "is_ok": r.is_ok,
            "latency_ms": r.latency_ms,
            "error": r.error,
            "recorded_at": r.recorded_at.isoformat(),
            "cpu_percent": r.cpu_percent,
            "mem_percent": r.mem_percent,
            "disk_percent": r.disk_percent,
        }
        for r in rows
    ]


async def get_uptime_summary(
    db: AsyncSession, *, hours: int = 24, since: datetime | None = None, until: datetime | None = None
) -> list[dict]:
    """Por cada servicio: % uptime + P50 + P95 + P99 + última latencia.

    Ventana: [since, until]. Si no se pasan, se deriva de `hours` (últimas N horas hasta ahora).
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
    if until is None:
        until = datetime.now(timezone.utc)

    from sqlalchemy import case

    # 3 queries bulk agrupadas por service_name (evita el N+1 anterior que
    # ejecutaba 3 SELECT por cada servicio dentro del loop).
    agg_q = await db.execute(
        select(
            HealthSnapshot.service_name,
            func.count(HealthSnapshot.id).label("total"),
            func.sum(case((HealthSnapshot.is_ok.is_(True), 1), else_=0)).label("oks"),
        )
        .where(HealthSnapshot.recorded_at >= since, HealthSnapshot.recorded_at <= until)
        .group_by(HealthSnapshot.service_name)
    )
    agg_by_svc = {r.service_name: (int(r.total or 0), int(r.oks or 0) if r.oks is not None else 0)
                  for r in agg_q.all()}

    lat_q = await db.execute(
        select(
            HealthSnapshot.service_name,
            HealthSnapshot.latency_ms,
        )
        .where(HealthSnapshot.recorded_at >= since, HealthSnapshot.recorded_at <= until)
        .where(HealthSnapshot.is_ok.is_(True))
        .where(HealthSnapshot.latency_ms.is_not(None))
        .order_by(HealthSnapshot.service_name, HealthSnapshot.latency_ms)
    )
    lats_by_svc: dict[str, list] = {}
    for r in lat_q.all():
        lats_by_svc.setdefault(r.service_name, []).append(r.latency_ms)

    last_q = await db.execute(
        select(HealthSnapshot)
        .where(HealthSnapshot.recorded_at >= since, HealthSnapshot.recorded_at <= until)
        .order_by(HealthSnapshot.service_name, HealthSnapshot.recorded_at.desc())
    )
    # Quedarse con el registro más reciente por servicio.
    last_by_svc: dict[str, "HealthSnapshot"] = {}
    for r in last_q.scalars().all():
        last_by_svc.setdefault(r.service_name, r)

    output = []
    for svc, (total, oks) in agg_by_svc.items():
        uptime_pct = round(oks / total * 100, 2) if total else 100.0
        _lats = lats_by_svc.get(svc, [])
        p50 = _pct(_lats, 0.50)
        p95 = _pct(_lats, 0.95)
        p99 = _pct(_lats, 0.99)
        last = last_by_svc.get(svc)
        output.append({
            "service_name": svc,
            "uptime_pct": uptime_pct,
            "samples": total,
            "p50_ms": float(p50) if p50 is not None else None,
            "p95_ms": float(p95) if p95 is not None else None,
            "p99_ms": float(p99) if p99 is not None else None,
            "last_ok": last.is_ok if last else None,
            "last_latency_ms": last.latency_ms if last else None,
            "last_recorded_at": last.recorded_at.isoformat() if last else None,
        })
    return output


async def get_incidents(
    db: AsyncSession, *, hours: int = 168, since: datetime | None = None, until: datetime | None = None
) -> list[dict]:
    """Deriva incidentes por servicio: tramos contiguos con `is_ok=False`.

    Ventana: [since, until]. Si no se pasan, se deriva de `hours` (default 7 días hasta ahora).
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
    if until is None:
        until = datetime.now(timezone.utc)
    result = await db.execute(
        select(HealthSnapshot)
        .where(HealthSnapshot.recorded_at >= since, HealthSnapshot.recorded_at <= until)
        .order_by(HealthSnapshot.service_name.asc(), HealthSnapshot.recorded_at.asc())
    )
    rows = list(result.scalars().all())

    incidents: list[dict] = []
    current: dict | None = None
    last_service: str | None = None

    for snap in rows:
        if snap.service_name != last_service:
            # Cierre forzado al cambiar de servicio
            if current is not None:
                incidents.append(current)
                current = None
            last_service = snap.service_name

        if not snap.is_ok:
            if current is None:
                current = {
                    "service_name": snap.service_name,
                    "started_at": snap.recorded_at.isoformat(),
                    "ended_at": None,
                    "duration_seconds": None,
                    "samples": 1,
                    "last_error": snap.error,
                }
            else:
                current["samples"] += 1
                current["last_error"] = snap.error or current["last_error"]
        else:
            if current is not None:
                current["ended_at"] = snap.recorded_at.isoformat()
                current["duration_seconds"] = int(
                    (snap.recorded_at - datetime.fromisoformat(current["started_at"])).total_seconds()
                )
                incidents.append(current)
                current = None

    if current is not None:
        incidents.append(current)

    incidents.sort(key=lambda x: x["started_at"], reverse=True)
    return incidents
