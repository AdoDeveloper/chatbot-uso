"""Background scheduler: snapshots de salud y digest diario de preguntas sin respuesta."""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.core.timezone import now_sv
from app.db.session import AsyncSessionLocal
from app.models.global_setting import GlobalSetting
from app.schemas.report_schedule import ReportSchedule

log = structlog.get_logger()

_HEALTH_INTERVAL = 300      # seconds between health snapshots (5 min)
_WARMUP_INTERVAL = 240      # seconds between embedding warm-up pings (4 min)
_STALE_CONV_INTERVAL = 600  # seconds between stale-conversation sweeps (10 min)
_STALE_CONV_MINUTES = 120  # inactivity threshold before auto-resolving (2h — Zendesk-style default)
# Identificador estable de este proceso, usado para marcar la adquisición del
# lock en BD (ayuda a depurar, no es estrictamente necesario para el claim).
_OWNER_ID = uuid.uuid4().hex
_health_task: asyncio.Task | None = None
_digest_task: asyncio.Task | None = None
_warmup_task: asyncio.Task | None = None
_stale_conv_task: asyncio.Task | None = None


async def _acquire_once(key: str, ttl: int) -> bool:
    """Mutex distribuido basado en BD (sin Redis).

    Guarda en `global_settings` una fila con el `key` dado y un `expires_at`.
    Solo un worker puede adquirirlo a la vez gracias a `SELECT ... FOR UPDATE`
    (pessimistic row lock) a nivel de base de datos. El lock se libera solo
    cuando expira `expires_at` (no hay DELETE explícito).

    Devuelve True si este worker adquirió el lock (debe correr el job);
    False si otro worker ya lo tiene o si la BD falla.

    A diferencia de la versión anterior (Redis SET NX), no depende de Redis
    ni falla cerrado si Redis no está disponible: la base de datos ya es un
    requisito del sistema, así que el scheduler sigue funcionando sin Redis.
    """
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl)
            try:
                row = (
                    await db.execute(
                        select(GlobalSetting)
                        .where(GlobalSetting.key == key)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
            except Exception:
                # Dialectos sin soporte de FOR UPDATE (p. ej. SQLite en dev):
                # reintenta sin el lock de fila. La carrera es rara y el peor
                # caso es un envío duplicado ocasional, no un correo perdido.
                row = (
                    await db.execute(
                        select(GlobalSetting).where(GlobalSetting.key == key)
                    )
                ).scalar_one_or_none()

            if row is None:
                db.add(
                    GlobalSetting(
                        key=key,
                        value={"owner": "", "expires_at": (now - timedelta(seconds=1)).isoformat()},
                    )
                )
                await db.commit()
                row = (
                    await db.execute(
                        select(GlobalSetting)
                        .where(GlobalSetting.key == key)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    # Rara condición de carrera en la creación inicial: otro
                    # worker ganó el INSERT. Este ciclo no corre; reintenta luego.
                    return False

            cur = datetime.fromisoformat(row.value.get("expires_at", "2000-01-01T00:00:00+00:00"))
            if cur > now:
                return False  # otro worker ya adquirió el lock vigente

            row.value = {"owner": _OWNER_ID, "expires_at": expires_at.isoformat()}
            await db.commit()
            return True
    except Exception:
        log.warning("scheduler.lock_acquire_failed", key=key)
        return False

async def _warmup_loop() -> None:
    """Runs a dummy embedding every _WARMUP_INTERVAL seconds to keep the ONNX
    Runtime inference thread pool alive.
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

    Usa un mutex en BD (FOR UPDATE) para que solo un worker por ventana de 5
    minutos ejecute el snapshot, evitando snapshots y notificaciones duplicadas
    con WORKERS>1.
    """
    log.info("scheduler.health_loop_started", interval=_HEALTH_INTERVAL)
    while True:
        try:
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
    """Envía el reporte unanswered_digest según la cadencia configurada.

    Usa un mutex en BD (FOR UPDATE) con TTL de 23h para que solo un worker
    envíe el digest por día, independientemente de cuántos workers estén
    corriendo (WORKERS>1), incluso si la cadencia se edita a mitad de día.

    Se chequea cada minuto (no cada hora): el loop anterior dormía 3600s desde
    un arranque arbitrario, así que los chequeos caían en minutos como :05, :05…
    y casi nunca coincidían con el minuto exacto configurado en el schedule,
    por lo que el correo programado rara vez se disparaba. Al evaluar cada 60s
    el minuto configurado sí se alcanza; el lock en BD ya evita el envío doble.
    """
    log.info("scheduler.digest_loop_started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                from app.services.system.report_schedule import get_report_schedule
                schedule = await get_report_schedule(db)
                if not _cumple_agenda(now, schedule):
                    await asyncio.sleep(60)
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
                        await send_notification(db, event=NotificationEvent.unanswered_digest, payload=stats)
                        log.info("scheduler.digest_sent", total_open=stats["total_open"])
                else:
                    log.debug("scheduler.digest_skipped_by_lock")
        except Exception:
            log.exception("scheduler.digest_failed")
        await asyncio.sleep(60)  # check every minute


async def _stale_conversations_loop() -> None:
    """Auto-resuelve conversaciones `active` sin actividad por _STALE_CONV_MINUTES.
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
