"""Background scheduler: snapshots de salud y digest diario de preguntas sin respuesta."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from app.core.timezone import now_sv
from app.db.session import AsyncSessionLocal
from app.schemas.report_schedule import ReportSchedule

log = structlog.get_logger()

_HEALTH_INTERVAL = 300      # seconds between health snapshots (5 min)
_WARMUP_INTERVAL = 240      # seconds between embedding warm-up pings (4 min)
_STALE_CONV_INTERVAL = 600  # seconds between stale-conversation sweeps (10 min)
_STALE_CONV_MINUTES = 120   # inactivity threshold before auto-resolving (2h — Zendesk-style default)
_health_task: asyncio.Task | None = None
_digest_task: asyncio.Task | None = None
_warmup_task: asyncio.Task | None = None
_stale_conv_task: asyncio.Task | None = None


async def _acquire_once(key: str, ttl: int) -> bool:
    """Distributed mutex using Redis SET NX.

    Returns True if this worker acquired the lock (and should run the job).
    Returns False if another worker already holds it.
    Falls back to False if Redis is unavailable (fail-closed): con WORKERS>1,
    un fail-open permitiría que cada worker ejecutara el job y disparara
    correos/registros duplicados. Mejor no enviar el digest a que enviarlo
    repetido; se reintenta al volver Redis.
    """
    try:
        from app.core.redis import get_redis
        redis = get_redis()
        acquired = await redis.set(key, "1", nx=True, ex=ttl)
        return bool(acquired)
    except Exception:
        return False  # Redis down → skip this cycle rather than risk duplicates


async def _warmup_loop() -> None:
    """Runs a dummy embedding every _WARMUP_INTERVAL seconds to keep the ONNX
    Runtime inference thread pool alive.

    Without this, the first request after a period of inactivity takes 15-20 s
    while the runtime re-initializes its threads and pages model weights back
    into RAM. Each worker runs its own warm-up independently (no Redis lock
    needed — the goal is to keep every worker's model hot).
    """
    await asyncio.sleep(30)
    log.info("scheduler.warmup_loop_started", interval=_WARMUP_INTERVAL)
    while True:
        try:
            from app.services.ai.embedding import embed_texts_async
            await embed_texts_async(["ping"], prefix="query: ")
            log.debug("scheduler.embedding_warmup_ok")
        except Exception:
            log.warning("scheduler.embedding_warmup_failed")
        await asyncio.sleep(_WARMUP_INTERVAL)


async def _health_loop() -> None:
    """Toma un snapshot de salud y ejecuta chequeos de alertas cada _HEALTH_INTERVAL segundos.

    Usa Redis SET NX para que solo un worker por ventana de 5 minutos ejecute
    el snapshot, evitando snapshots y notificaciones duplicadas con WORKERS>1.
    """
    log.info("scheduler.health_loop_started", interval=_HEALTH_INTERVAL)
    while True:
        try:
            # Bucket = floor(unix_ts / 300) — mismo valor en todos los workers
            # durante la misma ventana de 5 min. TTL=270s < 300s para liberar
            # el lock antes de la siguiente ventana.
            bucket = int(time.time() / _HEALTH_INTERVAL)
            lock_key = f"scheduler:health:{bucket}"
            if await _acquire_once(lock_key, ttl=270):
                from app.services.monitoring.health import collect_snapshot
                from app.services.monitoring.alerts import check_rate_limit_threshold
                async with AsyncSessionLocal() as db:
                    await collect_snapshot(db)
                    await check_rate_limit_threshold(db)
                log.debug("scheduler.health_snapshot_recorded")
            else:
                log.debug("scheduler.health_snapshot_skipped_by_lock")
        except Exception:
            log.exception("scheduler.health_snapshot_failed")
        await asyncio.sleep(_HEALTH_INTERVAL)


def _cumple_agenda(now: datetime, schedule: ReportSchedule) -> bool:
    """Indica si el instante `now` (UTC) coincide con la cadencia del reporte.

    `hour`/`minute` se interpretan en la zona de El Salvador (UTC-6): se
    convierte `now` a esa zona antes de comparar la hora y la fecha.
    """
    local = now.astimezone(now_sv().tzinfo)
    if schedule.hour != local.hour or schedule.minute != local.minute:
        return False
    if schedule.unit == "daily":
        return True
    if schedule.unit == "weekly":
        return local.weekday() in (schedule.days_of_week or [])
    if schedule.unit == "monthly":
        return local.day == schedule.day_of_month
    if schedule.unit == "yearly":
        return local.month == schedule.month and local.day == schedule.day_of_month
    return False


async def _digest_loop() -> None:
    """Envía el reporte unanswered_daily según la cadencia configurada.

    Usa Redis SET NX con TTL de 23h para que solo un worker envíe el digest
    por día, independientemente de cuántos workers estén corriendo (WORKERS>1),
    incluso si la cadencia se edita a mitad de día.
    """
    log.info("scheduler.digest_loop_started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                from app.services.system.report_schedule import get_report_schedule
                schedule = await get_report_schedule(db)
                if not _cumple_agenda(now, schedule):
                    continue
                today = now.astimezone(now_sv().tzinfo).strftime("%Y-%m-%d")
                lock_key = f"scheduler:digest:{today}"
                if await _acquire_once(lock_key, ttl=82800):  # 23h — libera antes del próximo día
                    from app.models.enums import NotificationEvent
                    from app.services.notifications.digest import collect_digest_stats
                    from app.services.notifications.service import send_notification
                    stats = await collect_digest_stats(db)
                    # Enviar solo si hay algo que reportar (pendientes o actividad del día).
                    if stats["total_open"] > 0 or stats["resolved_today"] > 0 or stats["escalated_today"] > 0:
                        await send_notification(db, event=NotificationEvent.unanswered_daily, payload=stats)
                        log.info("scheduler.digest_sent", total_open=stats["total_open"])
                else:
                    log.debug("scheduler.digest_skipped_by_lock")
        except Exception:
            log.exception("scheduler.digest_failed")
        await asyncio.sleep(3600)  # check once per hour


async def _stale_conversations_loop() -> None:
    """Auto-resuelve conversaciones `active` sin actividad por _STALE_CONV_MINUTES.

    El chat es HTTP por-turno (sin conexión persistente): si el usuario cierra
    la pestaña, nada avisa al backend, así que sin este barrido la conversación
    queda `active` para siempre. Usa Redis SET NX igual que _health_loop para
    que solo un worker ejecute el barrido por ventana con WORKERS>1.
    """
    log.info("scheduler.stale_conversations_loop_started", interval=_STALE_CONV_INTERVAL, threshold_min=_STALE_CONV_MINUTES)
    while True:
        try:
            bucket = int(time.time() / _STALE_CONV_INTERVAL)
            lock_key = f"scheduler:stale_conv:{bucket}"
            if await _acquire_once(lock_key, ttl=_STALE_CONV_INTERVAL - 30):
                from app.services.chat.history import auto_resolve_stale_conversations
                async with AsyncSessionLocal() as db:
                    n = await auto_resolve_stale_conversations(db, inactive_minutes=_STALE_CONV_MINUTES)
                    if n:
                        log.info("scheduler.stale_conversations_resolved", count=n)
            else:
                log.debug("scheduler.stale_conversations_skipped_by_lock")
        except Exception:
            log.exception("scheduler.stale_conversations_failed")
        await asyncio.sleep(_STALE_CONV_INTERVAL)


def start() -> None:
    """Start the health monitor, daily digest, embedding warm-up and stale-conversation sweep as background asyncio tasks."""
    global _health_task, _digest_task, _warmup_task, _stale_conv_task
    if _health_task is None or _health_task.done():
        _health_task = asyncio.create_task(_health_loop())
        log.info("scheduler.health_task_created")
    if _digest_task is None or _digest_task.done():
        _digest_task = asyncio.create_task(_digest_loop())
        log.info("scheduler.digest_task_created")
    if _warmup_task is None or _warmup_task.done():
        _warmup_task = asyncio.create_task(_warmup_loop())
        log.info("scheduler.warmup_task_created")
    if _stale_conv_task is None or _stale_conv_task.done():
        _stale_conv_task = asyncio.create_task(_stale_conversations_loop())
        log.info("scheduler.stale_conversations_task_created")


def stop() -> None:
    """Cancel the scheduler tasks."""
    global _health_task, _digest_task, _warmup_task, _stale_conv_task
    if _health_task and not _health_task.done():
        _health_task.cancel()
        log.info("scheduler.health_stopped")
    _health_task = None
    if _digest_task and not _digest_task.done():
        _digest_task.cancel()
        log.info("scheduler.digest_stopped")
    _digest_task = None
    if _warmup_task and not _warmup_task.done():
        _warmup_task.cancel()
        log.info("scheduler.warmup_stopped")
    _warmup_task = None
    if _stale_conv_task and not _stale_conv_task.done():
        _stale_conv_task.cancel()
        log.info("scheduler.stale_conversations_stopped")
    _stale_conv_task = None
