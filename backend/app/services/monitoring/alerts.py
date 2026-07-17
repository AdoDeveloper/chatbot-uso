"""Motor de alertas proactivas.

Evalúa condiciones del sistema y dispara `send_notification()` cuando se cumplen.
Aplica un cooldown por tipo de alerta + identificador para evitar spam.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.enums import NotificationEvent
from app.models.health_snapshot import HealthSnapshot
from app.services.notifications.service import send_notification

log = structlog.get_logger()

COOLDOWN_SEC = {
    NotificationEvent.service_down: 600,
    NotificationEvent.rate_limit_threshold: 1800,
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
        if all(not s.is_ok for s in snaps):
            if await _can_fire(NotificationEvent.service_down, svc):
                await send_notification(db, event=NotificationEvent.service_down, payload={
                    "service": svc,
                    "error": snaps[0].error or "(sin detalle)",
                    "since": snaps[1].recorded_at.isoformat(),
                })
                fired += 1
    return fired


async def check_rate_limit_threshold(db: AsyncSession, *, ratio: float = 0.8) -> int:
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    limit_per_hour = int(overrides.get("rate_limit_chat_per_hour") or 0)
    if limit_per_hour <= 0:
        return 0

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    from app.models.chat_message import ChatMessage
    from app.models.enums import MessageRole
    cnt_q = await db.execute(
        select(func.count(ChatMessage.id))
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= since)
    )
    cnt = int(cnt_q.scalar_one() or 0)
    pct = cnt / limit_per_hour

    if pct >= ratio:
        if await _can_fire(NotificationEvent.rate_limit_threshold, "global"):
            await send_notification(db, event=NotificationEvent.rate_limit_threshold, payload={
                "current_requests_last_hour": cnt,
                "limit_per_hour": limit_per_hour,
                "percent": round(pct * 100, 1),
            })
            return 1
    return 0


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
