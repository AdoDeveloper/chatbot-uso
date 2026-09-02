from __future__ import annotations

import pytest

from app.core import rate_limit as rl_mod
from app.core.rate_limit import RateLimitExceeded, check_rate_limit


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Aísla el estado global mutable del módulo entre tests."""
    rl_mod._LOCAL_LIMITS.clear()
    rl_mod._LOCAL_FALLBACK_WARNED = False
    yield
    rl_mod._LOCAL_LIMITS.clear()
    rl_mod._LOCAL_FALLBACK_WARNED = False


@pytest.fixture
async def fake_redis(monkeypatch):
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: fake)
    yield fake
    await fake.aclose()


class _BrokenRedis:
    async def incr(self, *a, **k):
        raise ConnectionError("redis down")


class TestCheckRateLimitWithRedis:
    async def test_within_limit_returns_true(self, fake_redis):
        assert await check_rate_limit("test:dim", "1.2.3.4", max_requests=5, window_seconds=60) is True

    async def test_exceeding_limit_raises(self, fake_redis):
        for _ in range(3):
            await check_rate_limit("test:dim2", "1.2.3.5", max_requests=3, window_seconds=60)
        with pytest.raises(RateLimitExceeded):
            await check_rate_limit("test:dim2", "1.2.3.5", max_requests=3, window_seconds=60)


class TestRedisFallback:
    async def test_falls_open_when_redis_unavailable(self, monkeypatch):
        monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: _BrokenRedis())
        assert await check_rate_limit("test:dim3", "9.9.9.9", max_requests=5, window_seconds=60) is True

    async def test_local_fallback_still_enforces_a_limit(self, monkeypatch):
        """El fallback local no debe ser ilimitado: permisivo (1.3x) pero
        con techo real, para no dejar el endpoint público completamente
        abierto mientras Redis está caído."""
        monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: _BrokenRedis())
        # limit=1 * 1.3 factor → techo real de 1 request (int(1.3) == 1)
        await check_rate_limit("test:dim4", "9.9.9.10", max_requests=1, window_seconds=60)
        with pytest.raises(RateLimitExceeded):
            await check_rate_limit("test:dim4", "9.9.9.10", max_requests=1, window_seconds=60)

    async def test_warned_flag_resets_after_redis_recovers(self, monkeypatch, fake_redis):
        warnings: list[str] = []
        monkeypatch.setattr(
            rl_mod.log, "warning",
            lambda event, **kwargs: warnings.append(event),
        )

        # 1ª caída de Redis: debe loguear una vez.
        monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: _BrokenRedis())
        await check_rate_limit("test:dim5", "9.9.9.11", max_requests=5, window_seconds=60)
        assert warnings.count("ratelimit.local_fallback_active") == 1
        assert rl_mod._LOCAL_FALLBACK_WARNED is True

        # Redis se recupera: el flag debe resetearse en la siguiente llamada exitosa.
        monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: fake_redis)
        await check_rate_limit("test:dim5", "9.9.9.11", max_requests=5, window_seconds=60)
        assert rl_mod._LOCAL_FALLBACK_WARNED is False

        # 2ª caída: debe volver a loguear (antes del fix quedaba en silencio porque el flag seguía en True desde la 1ª vez).
        monkeypatch.setattr(rl_mod.redis_mod, "get_redis", lambda: _BrokenRedis())
        await check_rate_limit("test:dim5", "9.9.9.11", max_requests=5, window_seconds=60)
        assert warnings.count("ratelimit.local_fallback_active") == 2
