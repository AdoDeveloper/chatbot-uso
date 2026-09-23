"""Tests de app/services/monitoring/alerts.py - notify_provider_down()."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import fakeredis.aioredis

from app.services.monitoring import alerts


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Parchea el nombre `get_redis` tal como cada módulo lo importó."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    from app.core import redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    monkeypatch.setattr(alerts, "get_redis", lambda: fake)
    yield fake


class TestNotifyProviderDown:
    async def test_payload_includes_provider_names(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("boom", providers=["Groq Produccion", "Mistral Free"])

        assert mock_send.await_count == 1
        _, kwargs = mock_send.call_args
        assert kwargs["payload"]["providers"] == "Groq Produccion, Mistral Free"
        assert kwargs["payload"]["error"] == "boom"

    async def test_payload_includes_since_timestamp(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("boom", providers=["Groq"])

        payload = mock_send.call_args.kwargs["payload"]
        assert "since" in payload
        assert payload["since"]  # non-empty ISO string

    async def test_since_is_stable_across_calls_within_the_same_incident(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("boom", providers=["Groq"])
            first_since = mock_send.call_args.kwargs["payload"]["since"]

            second_since = await alerts._provider_down_since()

        assert first_since == second_since

    async def test_no_providers_falls_back_to_placeholder(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("boom", providers=None)

        assert mock_send.call_args.kwargs["payload"]["providers"] == "(desconocido)"

    async def test_missing_error_falls_back_to_placeholder(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("", providers=["Groq"])

        assert mock_send.call_args.kwargs["payload"]["error"] == "(sin detalle)"

    async def test_respects_cooldown(self, fake_redis):
        """Una segunda llamada dentro del cooldown no debe reenviar."""
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock()) as mock_send:
            await alerts.notify_provider_down("boom", providers=["Groq"])
            await alerts.notify_provider_down("boom again", providers=["Groq"])

        assert mock_send.await_count == 1

    async def test_never_raises_if_send_notification_fails(self, fake_redis):
        with patch("app.services.monitoring.alerts.send_notification", AsyncMock(side_effect=RuntimeError("smtp down"))):
            await alerts.notify_provider_down("boom", providers=["Groq"])  # should not raise
