from __future__ import annotations

import pytest

from app.services.ai import semantic_cache as cache_svc


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    import fakeredis.aioredis
    from app.core import redis as redis_mod

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    # semantic_cache.py hace `from app.core.redis import get_redis` (import directo) - ese binding ya quedó resuelto, así que el monkeypatch de arriba no lo alcanza por sí solo.
    monkeypatch.setattr(cache_svc, "get_redis", lambda: fake)
    return fake


class TestCacheGeneration:
    async def test_generation_starts_at_zero(self):
        assert await cache_svc.get_cache_generation() == 0

    async def test_invalidate_by_source_bumps_generation(self):
        gen_before = await cache_svc.get_cache_generation()
        await cache_svc.invalidate_by_source("some-source-id")
        gen_after = await cache_svc.get_cache_generation()
        assert gen_after == gen_before + 1

    async def test_multiple_invalidations_bump_generation_each_time(self):
        for i in range(3):
            await cache_svc.invalidate_by_source(f"source-{i}")
        assert await cache_svc.get_cache_generation() == 3


class TestStoreCachedResponseGenerationGuard:
    async def test_store_skipped_when_generation_advanced(self, monkeypatch):
        async def _fake_embed(texts, prefix=""):
            return [{"dense": [0.1] * 8} for _ in texts]

        monkeypatch.setattr(cache_svc, "embed_texts_async", _fake_embed)

        await cache_svc.invalidate_by_source("some-source")  # generación pasa a 1

        await cache_svc.store_cached_response(
            "¿cuál es el costo de matrícula?", None, [], "precio viejo",
            min_generation=0,  # capturado ANTES de la invalidación
        )

        result = await cache_svc.get_cached_response(
            "¿cuál es el costo de matrícula?", None, threshold=0.0,
        )
        assert result is None, "la escritura obsoleta no debió persistirse"

    async def test_store_succeeds_when_generation_unchanged(self, monkeypatch):
        async def _fake_embed(texts, prefix=""):
            return [{"dense": [0.1] * 8} for _ in texts]

        monkeypatch.setattr(cache_svc, "embed_texts_async", _fake_embed)

        current_gen = await cache_svc.get_cache_generation()
        await cache_svc.store_cached_response(
            "¿cuáles son los requisitos de admisión?", None, [], "respuesta correcta",
            min_generation=current_gen,
        )

        result = await cache_svc.get_cached_response(
            "¿cuáles son los requisitos de admisión?", None, threshold=0.0,
        )
        assert result is not None
        assert result["content"] == "respuesta correcta"

    async def test_store_without_min_generation_always_succeeds(self, monkeypatch):
        """Compatibilidad hacia atrás: sin min_generation (llamadas que no
        pasan por el pipeline de chat), el comportamiento no cambia."""
        async def _fake_embed(texts, prefix=""):
            return [{"dense": [0.2] * 8} for _ in texts]

        monkeypatch.setattr(cache_svc, "embed_texts_async", _fake_embed)

        await cache_svc.invalidate_by_source("whatever")
        await cache_svc.store_cached_response(
            "pregunta sin guard de generación", None, [], "contenido",
        )

        result = await cache_svc.get_cached_response(
            "pregunta sin guard de generación", None, threshold=0.0,
        )
        assert result is not None


class TestStoreCachedResponseAtomicTTL:
    """hset + expire eran dos round-trips de red separados: si el proceso
    moría entre ambos, la clave quedaba persistida sin TTL (crecimiento
    indefinido del caché). Ahora van en un pipeline."""

    async def test_stored_key_always_has_ttl(self, monkeypatch, _fake_redis):
        async def _fake_embed(texts, prefix=""):
            return [{"dense": [0.3] * 8} for _ in texts]

        monkeypatch.setattr(cache_svc, "embed_texts_async", _fake_embed)

        await cache_svc.store_cached_response(
            "¿cuándo son las inscripciones?", None, [], "respuesta", ttl=999,
        )

        key = cache_svc._cache_key("¿cuándo son las inscripciones?", None, False)
        ttl = await _fake_redis.ttl(key)
        assert ttl > 0, f"la clave se guardó sin TTL (ttl={ttl})"
        assert ttl <= 999
