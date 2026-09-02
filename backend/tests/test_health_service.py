"""Tests unitarios para app/services/monitoring/health.py.

Ejercita la lógica de recolección de snapshots, cálculo de percentiles,
historial, resumen de uptime y derivación de incidentes usando mocks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.monitoring import health

pytestmark = pytest.mark.asyncio


class TestPct:
    def test_empty_data_returns_zero(self):
        assert health._pct([], 0.5) == 0.0

    def test_single_element(self):
        assert health._pct([42.0], 0.5) == 42.0

    def test_p50_odd_count(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert health._pct(data, 0.50) == 3.0

    def test_p50_even_count(self):
        data = [1.0, 2.0, 3.0, 4.0]
        assert health._pct(data, 0.50) == 2.5

    def test_p95(self):
        data = [float(i) for i in range(1, 101)]
        assert 94.0 <= health._pct(data, 0.95) <= 96.0


class TestCollectSnapshot:
    async def test_collects_all_services_and_returns_dict(self, db_session):
        with (
            patch.dict(health._CHECKS, {
                "MySQL": AsyncMock(return_value=(True, 5, None)),
                "Redis": AsyncMock(return_value=(True, 3, None)),
                "Qdrant": AsyncMock(return_value=(True, 10, None)),
            }),
            patch("app.services.monitoring.health._read_resource_utilization", return_value=(50.0, 60.0, 70.0)),
            patch("app.services.monitoring.alerts.check_service_down", AsyncMock()),
        ):
            result = await health.collect_snapshot(db_session)

        assert "services" in result
        assert set(result["services"].keys()) == {"MySQL", "Redis", "Qdrant"}
        assert result["cpu_percent"] == 50.0
        assert result["mem_percent"] == 60.0
        assert result["disk_percent"] == 70.0

    async def test_records_failures(self, db_session):
        with (
            patch.dict(health._CHECKS, {
                "MySQL": AsyncMock(return_value=(False, None, "timeout")),
                "Redis": AsyncMock(return_value=(True, 3, None)),
                "Qdrant": AsyncMock(return_value=(True, 10, None)),
            }),
            patch("app.services.monitoring.health._read_resource_utilization", return_value=(None, None, None)),
            patch("app.services.monitoring.alerts.check_service_down", AsyncMock()),
        ):
            result = await health.collect_snapshot(db_session)

        assert result["services"]["MySQL"]["ok"] is False
        assert result["services"]["MySQL"]["error"] == "timeout"
        assert result["services"]["Redis"]["ok"] is True

    async def test_survives_alert_check_failure(self, db_session):
        with (
            patch.dict(health._CHECKS, {
                "MySQL": AsyncMock(return_value=(True, 1, None)),
                "Redis": AsyncMock(return_value=(True, 1, None)),
                "Qdrant": AsyncMock(return_value=(True, 1, None)),
            }),
            patch("app.services.monitoring.health._read_resource_utilization", return_value=(None, None, None)),
            patch("app.services.monitoring.alerts.check_service_down", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            result = await health.collect_snapshot(db_session)

        assert result["services"]["MySQL"]["ok"] is True


class TestGetHistory:
    async def test_filters_by_service(self, db_session):
        snap = health.HealthSnapshot(
            service_name="MySQL", is_ok=True, latency_ms=5,
        )
        db_session.add(snap)
        await db_session.commit()

        mysql_history = await health.get_history(db_session, service="MySQL")
        assert len(mysql_history) == 1

        redis_history = await health.get_history(db_session, service="Redis")
        assert len(redis_history) == 0

    async def test_returns_empty_when_no_data(self, db_session):
        result = await health.get_history(db_session)
        assert result == []


class TestGetUptimeSummary:
    async def test_returns_empty_when_no_snapshots(self, db_session):
        result = await health.get_uptime_summary(db_session, since=datetime.now(timezone.utc) - timedelta(hours=1))
        assert result == []

    async def test_returns_uptime_and_latencies(self, db_session):
        now = datetime.now(timezone.utc)
        snap = health.HealthSnapshot(
            service_name="MySQL", is_ok=True, latency_ms=10,
            recorded_at=now - timedelta(minutes=5),
        )
        snap2 = health.HealthSnapshot(
            service_name="MySQL", is_ok=True, latency_ms=20,
            recorded_at=now - timedelta(minutes=1),
        )
        db_session.add_all([snap, snap2])
        await db_session.commit()

        result = await health.get_uptime_summary(
            db_session, since=now - timedelta(hours=1), until=now,
        )
        assert len(result) == 1
        entry = result[0]
        assert entry["service_name"] == "MySQL"
        assert entry["uptime_pct"] == 100.0
        assert entry["samples"] == 2

    async def test_handles_mixed_ok_and_failure(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            health.HealthSnapshot(service_name="Redis", is_ok=True, latency_ms=5, recorded_at=now - timedelta(minutes=10)),
            health.HealthSnapshot(service_name="Redis", is_ok=True, latency_ms=5, recorded_at=now - timedelta(minutes=9)),
            health.HealthSnapshot(service_name="Redis", is_ok=False, latency_ms=None, recorded_at=now - timedelta(minutes=8)),
            health.HealthSnapshot(service_name="Redis", is_ok=True, latency_ms=5, recorded_at=now - timedelta(minutes=7)),
        ])
        await db_session.commit()

        result = await health.get_uptime_summary(
            db_session, since=now - timedelta(hours=1), until=now,
        )
        entry = result[0]
        assert entry["uptime_pct"] == 75.0
        assert entry["samples"] == 4


class TestGetIncidents:
    async def test_empty_when_no_failures(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add(health.HealthSnapshot(service_name="MySQL", is_ok=True, recorded_at=now))
        await db_session.commit()

        incidents = await health.get_incidents(db_session, since=now - timedelta(hours=1), until=now)
        assert incidents == []

    async def test_single_incident(self, db_session):
        now = datetime.now(timezone.utc)
        fail_snap = health.HealthSnapshot(
            service_name="MySQL", is_ok=False, error="timeout",
            recorded_at=now - timedelta(minutes=30),
        )
        recovery_snap = health.HealthSnapshot(
            service_name="MySQL", is_ok=True, latency_ms=5,
            recorded_at=now - timedelta(minutes=20),
        )
        db_session.add_all([fail_snap, recovery_snap])
        await db_session.commit()

        incidents = await health.get_incidents(db_session, since=now - timedelta(hours=2), until=now)
        assert len(incidents) == 1
        inc = incidents[0]
        assert inc["service_name"] == "MySQL"
        assert inc["duration_seconds"] == 600
        assert inc["last_error"] == "timeout"

    async def test_open_incident_at_end_of_window(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            health.HealthSnapshot(service_name="MySQL", is_ok=False, error="down", recorded_at=now - timedelta(minutes=15)),
            health.HealthSnapshot(service_name="MySQL", is_ok=False, error="still down", recorded_at=now - timedelta(minutes=5)),
        ])
        await db_session.commit()

        incidents = await health.get_incidents(db_session, since=now - timedelta(hours=1), until=now)
        assert len(incidents) == 1
        inc = incidents[0]
        assert inc["ended_at"] is None
        assert inc["duration_seconds"] is None
        assert inc["samples"] == 2
        assert inc["last_error"] == "still down"

    async def test_multiple_services_with_separate_incidents(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            health.HealthSnapshot(service_name="MySQL", is_ok=False, recorded_at=now - timedelta(minutes=30)),
            health.HealthSnapshot(service_name="Redis", is_ok=False, recorded_at=now - timedelta(minutes=25)),
            health.HealthSnapshot(service_name="MySQL", is_ok=True, recorded_at=now - timedelta(minutes=20)),
            health.HealthSnapshot(service_name="Redis", is_ok=True, recorded_at=now - timedelta(minutes=15)),
        ])
        await db_session.commit()

        incidents = await health.get_incidents(db_session, since=now - timedelta(hours=2), until=now)
        assert len(incidents) == 2

    async def test_consecutive_failures_grouped(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add_all([
            health.HealthSnapshot(service_name="MySQL", is_ok=False, recorded_at=now - timedelta(minutes=30)),
            health.HealthSnapshot(service_name="MySQL", is_ok=False, recorded_at=now - timedelta(minutes=25)),
            health.HealthSnapshot(service_name="MySQL", is_ok=True, recorded_at=now - timedelta(minutes=20)),
        ])
        await db_session.commit()

        incidents = await health.get_incidents(db_session, since=now - timedelta(hours=2), until=now)
        assert len(incidents) == 1
        assert incidents[0]["samples"] == 2
