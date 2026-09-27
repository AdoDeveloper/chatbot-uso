"""Motor de alertas proactivas."""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.enums import NotificationEvent
from app.models.health_snapshot import HealthSnapshot
from app.services.notifications.service import send_notification

log = structlog.get_logger()

COOLDOWN_SEC = {
    NotificationEvent.service_down: 600,
    NotificationEvent.rate_limit_threshold: 1800,
    NotificationEvent.provider_down: 600,
    # Más espaciado que la caída total: es informativo y el servicio sigue en pie.
    NotificationEvent.provider_degraded: 3600,
    # Un error permanente no se resuelve solo entre avisos: recordarlo cada
    # hora sería ruido hasta que alguien corrija la configuración a mano.
    NotificationEvent.provider_misconfigured: 21600,
}


async def _can_fire(event: NotificationEvent, key: str) -> bool:
    try:
        redis = get_redis()
        rk = f"alert:cooldown:{event.value}:{key}"
        ttl = COOLDOWN_SEC.get(event, 300)
        ok = await redis.set(rk, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        return True


async def check_service_down(db: AsyncSession) -> int:
    fired = 0
    distinct_q = await db.execute(
        select(HealthSnapshot.service_name).group_by(HealthSnapshot.service_name)
    )
    services = [row[0] for row in distinct_q.all()]

    for svc in services:
        last_q = await db.execute(
            select(HealthSnapshot)
            .where(HealthSnapshot.service_name == svc)
            .order_by(HealthSnapshot.recorded_at.desc())
            .limit(2)
        )
        snaps = last_q.scalars().all()
        if len(snaps) < 2:
            continue
        if all(not s.is_ok for s in snaps) and await _can_fire(NotificationEvent.service_down, svc):
            await send_notification(db, event=NotificationEvent.service_down, payload={
                "service": svc,
                "error": snaps[0].error or "(sin detalle)",
                "since": snaps[1].recorded_at.isoformat(),
            })
            fired += 1
    return fired


async def check_rate_limit_threshold(db: AsyncSession, *, ratio: float = 0.8) -> int:
    """Avisa cuando alguna IP se acerca a su límite de mensajes por hora (el límite es por IP)."""
    from app.core.rate_limit import get_throttled_ips
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    limit_per_hour = int(overrides.get("rate_limit_chat_per_hour") or 0)
    if limit_per_hour <= 0:
        return 0
    near = [
        ip for ip in await get_throttled_ips(
            limit_per_min=int(overrides.get("rate_limit_chat_per_min") or 0) or None,
            limit_per_hour=limit_per_hour,
            window="per_hour",
        )
        if ip["current_count"] >= ratio * limit_per_hour
    ]
    if not near:
        return 0
    top = max(near, key=lambda ip: ip["current_count"])
    if not await _can_fire(NotificationEvent.rate_limit_threshold, "global"):
        return 0
    await send_notification(db, event=NotificationEvent.rate_limit_threshold, payload={
        "ip": top["ip"],
        "ips_near_limit": len(near),
        "current_requests_last_hour": top["current_count"],
        "limit_per_hour": limit_per_hour,
        "percent": round(top["current_count"] / limit_per_hour * 100, 1),
    })
    return 1


_PROVIDER_DOWN_SINCE_KEY = "alert:since:provider_down:all"
_PROVIDER_DOWN_SINCE_TTL = 6 * 3600


async def _provider_down_since() -> str:
    """Devuelve el timestamp ISO del primer fallo de la racha actual (SET NX)."""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        redis = get_redis()
        await redis.set(_PROVIDER_DOWN_SINCE_KEY, now_iso, ex=_PROVIDER_DOWN_SINCE_TTL, nx=True)
        stored = await redis.get(_PROVIDER_DOWN_SINCE_KEY)
        return stored or now_iso
    except Exception:
        return now_iso


async def clear_provider_down_streak() -> None:
    """Un turno respondido cierra la racha: la próxima caída contará desde su propio inicio."""
    try:
        await get_redis().delete(_PROVIDER_DOWN_SINCE_KEY)
    except Exception:
        pass


async def notify_provider_down(error: str, providers: list[str] | None = None) -> None:
    """Notifica que todos los proveedores LLM de la cadena fallaron."""
    if not await _can_fire(NotificationEvent.provider_down, "all"):
        return
    try:
        from app.db.session import AsyncSessionLocal
        since = await _provider_down_since()
        payload = {
            "providers": ", ".join(providers) if providers else "(desconocido)",
            "error": error[:300] if error else "(sin detalle)",
            "since": since,
        }
        async with AsyncSessionLocal() as db:
            await send_notification(db, event=NotificationEvent.provider_down, payload=payload)
    except Exception as exc:
        log.warning("alerts.provider_down_notify_failed", error=str(exc))


async def notify_provider_degraded(provider_name: str, error: str) -> None:
    """Avisa que un proveedor quedó fuera de la cadena, con los demás activos."""
    if not await _can_fire(NotificationEvent.provider_degraded, provider_name):
        return
    try:
        from app.db.session import AsyncSessionLocal
        payload = {
            "providers": provider_name,
            "error": error[:300] if error else "(sin detalle)",
        }
        async with AsyncSessionLocal() as db:
            await send_notification(
                db, event=NotificationEvent.provider_degraded, payload=payload,
            )
    except Exception as exc:
        log.warning("alerts.provider_degraded_notify_failed", error=str(exc))


async def notify_provider_misconfigured(provider_name: str, error: str) -> None:
    """Avisa que un proveedor falla de forma permanente: modelo retirado, credencial inválida o sin crédito."""
    if not await _can_fire(NotificationEvent.provider_misconfigured, provider_name):
        return
    try:
        from app.db.session import AsyncSessionLocal
        payload = {
            "providers": provider_name,
            "error": error[:300] if error else "(sin detalle)",
        }
        async with AsyncSessionLocal() as db:
            await send_notification(
                db, event=NotificationEvent.provider_misconfigured, payload=payload,
            )
    except Exception as exc:
        log.warning("alerts.provider_misconfigured_notify_failed", error=str(exc))


async def run_all_checks(db: AsyncSession) -> dict:
    counters: dict[str, int] = {}
    for name, fn in [
        ("service_down", check_service_down),
        ("rate_limit_threshold", check_rate_limit_threshold),
    ]:
        try:
            counters[name] = await fn(db)
        except Exception as exc:
            log.error("alerts.check_failed", check=name, error=str(exc))
            counters[name] = 0
    return counters
