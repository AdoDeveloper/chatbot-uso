"""Tests unitarios para app/services/system/scheduler.py.

Cubre la lógica de cada job (health snapshot, digest diario, warm-up de
embeddings, auto-resolución de conversaciones inactivas) mockeando Redis,
la sesión de BD y los servicios externos que cada loop invoca. No se
ejercita el scheduling real (asyncio.sleep se mockea o se corta con
CancelledError tras una iteración).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.schemas.report_schedule import ReportSchedule
from app.services.system import scheduler
from app.models.global_setting import GlobalSetting


class _StopLoop(Exception):
    """Usada para cortar un while True tras N iteraciones controladas."""


def _sleep_raises_after(n_calls: list[int], limit: int = 1):
    async def _fake_sleep(_seconds):
        n_calls[0] += 1
        if n_calls[0] >= limit:
            raise _StopLoop
    return _fake_sleep


class TestAcquireOnce:
    async def test_acquires_lock_when_no_row_exists(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        key = f"lock-{uuid4()}"
        result = await scheduler._acquire_once(key, ttl=60)
        assert result is True

        async with Session() as verify_session:
            row = await verify_session.execute(
                select(GlobalSetting).where(GlobalSetting.key == key)
            )
            gs = row.scalar_one()
            assert gs.value["owner"] == scheduler._OWNER_ID

    async def test_acquires_lock_when_expired_row_exists(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        key = f"lock-{uuid4()}"
        from datetime import timedelta
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        async with Session() as write_session:
            write_session.add(GlobalSetting(key=key, value={"owner": "", "expires_at": expired}))
            await write_session.commit()

        result = await scheduler._acquire_once(key, ttl=60)
        assert result is True

        async with Session() as verify_session:
            row = await verify_session.execute(
                select(GlobalSetting).where(GlobalSetting.key == key)
            )
            gs = row.scalar_one()
            assert gs.value["owner"] == scheduler._OWNER_ID

    async def test_returns_false_when_lock_still_valid(self):
        row = AsyncMock()
        row.value = {
            "owner": "other-worker",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        fake_scalars = AsyncMock()
        fake_scalars.scalar_one_or_none.return_value = row
        fake_execute = AsyncMock()
        fake_execute.scalar_one_or_none.return_value = row
        fake_session = AsyncMock()
        fake_session.execute.return_value = fake_execute
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = None

        with patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_session):
            result = await scheduler._acquire_once("key1", ttl=60)
        assert result is False

    async def test_fails_closed_when_db_unavailable(self):
        with patch("app.services.system.scheduler.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            result = await scheduler._acquire_once("key1", ttl=60)
        assert result is False


class TestPurgeExpiredLocks:
    async def test_deletes_only_stale_scheduler_locks(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        now = datetime.now(timezone.utc)
        stale_key = f"scheduler:health:{uuid4()}"
        fresh_key = f"scheduler:health:{uuid4()}"
        config_key = f"cfg-{uuid4()}"

        async with Session() as s:
            s.add(GlobalSetting(
                key=stale_key,
                value={"owner": "x", "expires_at": (now - timedelta(days=10)).isoformat()},
            ))
            s.add(GlobalSetting(
                key=fresh_key,
                value={"owner": "x", "expires_at": (now + timedelta(hours=1)).isoformat()},
            ))
            s.add(GlobalSetting(key=config_key, value={"algo": "importante"}))
            await s.commit()

        await scheduler._purge_expired_locks()

        async with Session() as s:
            remaining = set((await s.execute(
                select(GlobalSetting.key).where(
                    GlobalSetting.key.in_([stale_key, fresh_key, config_key])
                )
            )).scalars().all())

        assert stale_key not in remaining, "el lock caducado debia borrarse"
        assert fresh_key in remaining, "un lock aun vigente no debe borrarse"
        assert config_key in remaining, "la configuracion real no debe tocarse"

    async def test_returns_zero_when_db_unavailable(self):
        with patch("app.services.system.scheduler.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            assert await scheduler._purge_expired_locks() == 0


class TestPurgeOldHealthSnapshots:
    async def test_deletes_only_snapshots_past_retention(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.health_snapshot import HealthSnapshot
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        now = datetime.now(timezone.utc)
        old_id = uuid4()
        recent_id = uuid4()
        service = f"svc-{uuid4().hex[:8]}"

        async with Session() as s:
            s.add(HealthSnapshot(
                id=old_id, service_name=service, is_ok=True,
                recorded_at=now - timedelta(days=scheduler._SNAPSHOT_RETENTION_DAYS + 5),
            ))
            s.add(HealthSnapshot(
                id=recent_id, service_name=service, is_ok=True,
                recorded_at=now - timedelta(days=1),
            ))
            await s.commit()

        await scheduler._purge_old_health_snapshots()

        async with Session() as s:
            remaining = set((await s.execute(
                select(HealthSnapshot.id).where(HealthSnapshot.id.in_([old_id, recent_id]))
            )).scalars().all())

        assert old_id not in remaining, "el snapshot fuera de retencion debia borrarse"
        assert recent_id in remaining, "un snapshot reciente no debe borrarse"

    async def test_returns_zero_when_db_unavailable(self):
        with patch("app.services.system.scheduler.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            assert await scheduler._purge_old_health_snapshots() == 0


class TestCumpleAgenda:
    def _dt_utc(self, hour_sv, minute_sv, *, year=2026, month=7, day=16):
        # El Salvador es UTC-6, sin DST: hora UTC = hora_sv + 6
        return datetime(year, month, day, hour_sv + 6, minute_sv, tzinfo=timezone.utc)

    def test_daily_matches_exact_hour_minute(self):
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)
        now = self._dt_utc(8, 0)
        assert scheduler._cumple_agenda(now, schedule) is True

    def test_daily_does_not_match_other_minute(self):
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)
        now = self._dt_utc(8, 1)
        assert scheduler._cumple_agenda(now, schedule) is False

    def test_weekly_matches_configured_weekday(self):
        # 2026-07-16 es jueves -> weekday()==3
        now = self._dt_utc(8, 0, year=2026, month=7, day=16)
        schedule = ReportSchedule(unit="weekly", hour=8, minute=0, days_of_week=[3])
        assert scheduler._cumple_agenda(now, schedule) is True

    def test_weekly_does_not_match_other_weekday(self):
        now = self._dt_utc(8, 0, year=2026, month=7, day=16)
        schedule = ReportSchedule(unit="weekly", hour=8, minute=0, days_of_week=[0])
        assert scheduler._cumple_agenda(now, schedule) is False

    def test_monthly_matches_configured_day(self):
        now = self._dt_utc(8, 0, year=2026, month=7, day=15)
        schedule = ReportSchedule(unit="monthly", hour=8, minute=0, day_of_month=15)
        assert scheduler._cumple_agenda(now, schedule) is True

    def test_monthly_does_not_match_other_day(self):
        now = self._dt_utc(8, 0, year=2026, month=7, day=16)
        schedule = ReportSchedule(unit="monthly", hour=8, minute=0, day_of_month=15)
        assert scheduler._cumple_agenda(now, schedule) is False

    def test_yearly_matches_configured_month_and_day(self):
        now = self._dt_utc(8, 0, year=2026, month=12, day=25)
        schedule = ReportSchedule(unit="yearly", hour=8, minute=0, day_of_month=25, month=12)
        assert scheduler._cumple_agenda(now, schedule) is True

    def test_yearly_does_not_match_other_month(self):
        now = self._dt_utc(8, 0, year=2026, month=11, day=25)
        schedule = ReportSchedule(unit="yearly", hour=8, minute=0, day_of_month=25, month=12)
        assert scheduler._cumple_agenda(now, schedule) is False


class TestHealthLoop:
    async def test_runs_snapshot_and_alerts_when_lock_acquired(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        collect_snapshot_mock = AsyncMock()
        check_alerts_mock = AsyncMock()

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.monitoring.health.collect_snapshot", collect_snapshot_mock), \
             patch("app.services.monitoring.alerts.check_rate_limit_threshold", check_alerts_mock), \
             patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._health_loop()

        collect_snapshot_mock.assert_awaited_once_with(fake_db)
        check_alerts_mock.assert_awaited_once_with(fake_db)

    async def test_skips_work_when_lock_not_acquired(self):
        calls = [0]
        collect_snapshot_mock = AsyncMock()

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=False)), \
             patch("app.services.monitoring.health.collect_snapshot", collect_snapshot_mock), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._health_loop()

        collect_snapshot_mock.assert_not_awaited()

    async def test_survives_exception_in_snapshot(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.monitoring.health.collect_snapshot", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("app.services.monitoring.alerts.check_rate_limit_threshold", AsyncMock()), \
             patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._health_loop()
        # No debe propagar el RuntimeError: el loop lo captura y continúa (llega al sleep).
        assert calls[0] == 1


class TestWarmupLoop:
    async def test_calls_embed_texts_after_initial_delay(self):
        calls = [0]
        embed_mock = AsyncMock()
        sleep_mock = AsyncMock(side_effect=lambda s: _sleep_raises_after(calls)(s))

        async def fake_sleep(seconds):
            if seconds == 30:
                return  # initial delay, let it pass
            calls[0] += 1
            raise _StopLoop

        with patch("app.services.ai.embedding.embed_texts_async", embed_mock), \
             patch("asyncio.sleep", fake_sleep):
            with pytest.raises(_StopLoop):
                await scheduler._warmup_loop()

        embed_mock.assert_awaited_once_with(["ping"], prefix="query: ")

    async def test_survives_exception_in_embedding(self):
        async def fake_sleep(seconds):
            if seconds == 30:
                return
            raise _StopLoop

        with patch("app.services.ai.embedding.embed_texts_async", AsyncMock(side_effect=RuntimeError("onnx down"))), \
             patch("asyncio.sleep", fake_sleep):
            with pytest.raises(_StopLoop):
                await scheduler._warmup_loop()
        # No propaga la excepción del embedding; llega hasta el segundo sleep.


class TestDigestLoop:
    async def test_sends_digest_when_schedule_matches_and_lock_acquired(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)
        stats = {"total_open": 3, "resolved_today": 0, "escalated_today": 0}
        send_notification_mock = AsyncMock()

        with patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("app.services.system.report_schedule.get_report_schedule", AsyncMock(return_value=schedule)), \
             patch("app.services.system.scheduler._cumple_agenda", return_value=True), \
             patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.notifications.digest.collect_digest_stats", AsyncMock(return_value=stats)), \
             patch("app.services.notifications.service.send_notification", send_notification_mock), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._digest_loop()

        send_notification_mock.assert_awaited_once()
        _, kwargs = send_notification_mock.await_args
        assert kwargs["payload"] == stats

    async def test_does_not_send_when_schedule_does_not_match(self):
        # Cuando _cumple_agenda es False, el loop hace `await
        # asyncio.sleep(3600)` antes del `continue`, evitando un busy-loop.
        # Cortamos el loop igual que en los demás tests: _sleep_raises_after
        # levanta _StopLoop en la primera llamada a sleep.
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)
        send_mock = AsyncMock()

        with patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("app.services.system.report_schedule.get_report_schedule", AsyncMock(return_value=schedule)), \
             patch("app.services.system.scheduler._cumple_agenda", return_value=False), \
             patch("app.services.notifications.service.send_notification", send_mock), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._digest_loop()

        send_mock.assert_not_awaited()

    async def test_does_not_send_when_lock_not_acquired(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)

        with patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("app.services.system.report_schedule.get_report_schedule", AsyncMock(return_value=schedule)), \
             patch("app.services.system.scheduler._cumple_agenda", return_value=True), \
             patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=False)), \
             patch("app.services.notifications.service.send_notification", AsyncMock()) as send_mock, \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._digest_loop()

        send_mock.assert_not_awaited()

    async def test_does_not_send_when_stats_are_all_empty(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        schedule = ReportSchedule(unit="daily", hour=8, minute=0)
        stats = {"total_open": 0, "resolved_today": 0, "escalated_today": 0}

        with patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("app.services.system.report_schedule.get_report_schedule", AsyncMock(return_value=schedule)), \
             patch("app.services.system.scheduler._cumple_agenda", return_value=True), \
             patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.notifications.digest.collect_digest_stats", AsyncMock(return_value=stats)), \
             patch("app.services.notifications.service.send_notification", AsyncMock()) as send_mock, \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._digest_loop()

        send_mock.assert_not_awaited()

    async def test_survives_exception_in_schedule_lookup(self):
        calls = [0]

        with patch("app.services.system.scheduler.AsyncSessionLocal", side_effect=RuntimeError("db down")), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._digest_loop()
        assert calls[0] == 1


class TestStaleConversationsLoop:
    async def test_resolves_stale_conversations_when_lock_acquired(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None
        auto_resolve_mock = AsyncMock(return_value=5)

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.chat.history.auto_resolve_stale_conversations", auto_resolve_mock), \
             patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._stale_conversations_loop()

        auto_resolve_mock.assert_awaited_once_with(fake_db, inactive_minutes=scheduler._STALE_CONV_MINUTES)

    async def test_skips_when_lock_not_acquired(self):
        calls = [0]
        auto_resolve_mock = AsyncMock()

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=False)), \
             patch("app.services.chat.history.auto_resolve_stale_conversations", auto_resolve_mock), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._stale_conversations_loop()

        auto_resolve_mock.assert_not_awaited()

    async def test_survives_exception_in_auto_resolve(self):
        calls = [0]
        fake_db = AsyncMock()
        fake_db.__aenter__.return_value = fake_db
        fake_db.__aexit__.return_value = None

        with patch("app.services.system.scheduler._acquire_once", AsyncMock(return_value=True)), \
             patch("app.services.chat.history.auto_resolve_stale_conversations", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("app.services.system.scheduler.AsyncSessionLocal", return_value=fake_db), \
             patch("asyncio.sleep", _sleep_raises_after(calls)):
            with pytest.raises(_StopLoop):
                await scheduler._stale_conversations_loop()
        assert calls[0] == 1


async def _forever():
    """Coroutine que nunca termina por sí sola (se cancela explícitamente)."""
    await asyncio.sleep(3600)


class TestStartStop:
    def teardown_method(self, _method):
        scheduler.stop()

    async def test_start_creates_all_four_tasks(self):
        scheduler.stop()
        with patch("app.services.system.scheduler._health_loop", _forever), \
             patch("app.services.system.scheduler._digest_loop", _forever), \
             patch("app.services.system.scheduler._warmup_loop", _forever), \
             patch("app.services.system.scheduler._stale_conversations_loop", _forever):
            scheduler.start()
            await asyncio.sleep(0)
            assert scheduler._health_task is not None
            assert scheduler._digest_task is not None
            assert scheduler._warmup_task is not None
            assert scheduler._stale_conv_task is not None
            assert not scheduler._health_task.done()
            scheduler.stop()

    async def test_start_is_idempotent_when_tasks_already_running(self):
        scheduler.stop()
        with patch("app.services.system.scheduler._health_loop", _forever), \
             patch("app.services.system.scheduler._digest_loop", _forever), \
             patch("app.services.system.scheduler._warmup_loop", _forever), \
             patch("app.services.system.scheduler._stale_conversations_loop", _forever):
            scheduler.start()
            first_task = scheduler._health_task
            scheduler.start()
            assert scheduler._health_task is first_task
            scheduler.stop()

    async def test_stop_cancels_running_tasks(self):
        scheduler.stop()

        with patch("app.services.system.scheduler._health_loop", _forever), \
             patch("app.services.system.scheduler._digest_loop", _forever), \
             patch("app.services.system.scheduler._warmup_loop", _forever), \
             patch("app.services.system.scheduler._stale_conversations_loop", _forever):
            scheduler.start()
            health_task = scheduler._health_task
            scheduler.stop()
            await asyncio.sleep(0)
            assert health_task.cancelled() or health_task.done()
            assert scheduler._health_task is None
            assert scheduler._digest_task is None
            assert scheduler._warmup_task is None
            assert scheduler._stale_conv_task is None

    async def test_stop_is_safe_when_nothing_started(self):
        scheduler.stop()
        scheduler.stop()  # no debe lanzar
        assert scheduler._health_task is None
