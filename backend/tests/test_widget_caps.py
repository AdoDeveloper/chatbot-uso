from __future__ import annotations

from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from app.core import redis as redis_mod
from app.services.widget import service as widget_svc


def _widget(**kwargs) -> SimpleNamespace:
    defaults = dict(api_key="test-widget-key", max_chats_per_session=None, max_chats_per_day=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    return fake


class TestEnforceWidgetCaps:
    async def test_no_limits_configured_is_noop(self):
        await widget_svc.enforce_widget_caps(_widget(), "some-session")

    async def test_session_limit_without_session_id_is_rejected(self):
        """El fix: sin session_id, el límite por-sesión configurado no se
        puede evaluar - antes esto se interpretaba como "sin límite" y
        dejaba pasar sin restricción alguna."""
        widget = _widget(max_chats_per_session=5)
        with pytest.raises(HTTPException) as exc_info:
            await widget_svc.enforce_widget_caps(widget, "")
        assert exc_info.value.status_code == 400

    async def test_session_limit_with_session_id_is_enforced(self):
        widget = _widget(max_chats_per_session=2)
        await widget_svc.enforce_widget_caps(widget, "session-a")
        await widget_svc.enforce_widget_caps(widget, "session-a")
        with pytest.raises(HTTPException) as exc_info:
            await widget_svc.enforce_widget_caps(widget, "session-a")
        assert exc_info.value.status_code == 429

    async def test_session_limit_is_independent_per_session(self):
        """Cada session_id tiene su propio contador - no se agrupa por IP
        ni entre usuarios distintos."""
        widget = _widget(max_chats_per_session=1)
        await widget_svc.enforce_widget_caps(widget, "session-a")
        await widget_svc.enforce_widget_caps(widget, "session-b")

    async def test_day_limit_applies_without_session_id(self):
        """max_chats_per_day no depende de session_id - ya se aplicaba
        siempre y sigue haciéndolo tras el fix."""
        widget = _widget(max_chats_per_day=1)
        await widget_svc.enforce_widget_caps(widget, "")
        with pytest.raises(HTTPException) as exc_info:
            await widget_svc.enforce_widget_caps(widget, "")
        assert exc_info.value.status_code == 429
