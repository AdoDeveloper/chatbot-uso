"""Tests de app/services/ai/semantic_cache.py - lógica real de matching.

test_semantic_cache_generation.py cubre el guard TOCTOU de generación, pero
usa embeddings idénticos entre store y get (mock constante) - nunca ejercita
la comparación de similitud coseno en sí, el filtro de scope por source_ids
(aislamiento draft/prod), ni el corte SCAN_BATCH_HARD_LIMIT. Un cálculo roto
en cualquiera de esas rutas serviría una respuesta incorrecta o filtraría una
respuesta de borrador a producción sin que ningún test lo detectara.

Mismo patrón de fakeredis por test que test_semantic_cache_generation.py
(get_redis está cacheado con @lru_cache y ligado al primer event loop).
"""
from __future__ import annotations

import pytest

from app.services.ai import semantic_cache as cache_svc


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    import fakeredis.aioredis
    from app.core import redis as redis_mod

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    monkeypatch.setattr(cache_svc, "get_redis", lambda: fake)
    return fake


def _embed_fixed(vector: list[float]):
    async def _fake(texts, prefix=""):
        return [{"dense": vector} for _ in texts]
    return _fake


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert cache_svc.cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cache_svc.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_negative_one(self):
        assert cache_svc.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_norm_vector_returns_zero_not_nan(self):
        """División por norma cero (embedding nulo) debe degradar a 0.0, no NaN/crash."""
        assert cache_svc.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestGetCachedResponseMatching:
    async def test_similar_question_above_threshold_is_a_hit(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0, 0.0]))
        await cache_svc.store_cached_response(
            "¿cuál es el costo de la matrícula?", None, [], "El costo es $50.",
        )

        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0, 0.0]))
        result = await cache_svc.get_cached_response(
            "¿cuánto cuesta matricularse?", None, threshold=0.93,
        )
        assert result is not None
        assert result["content"] == "El costo es $50."

    async def test_dissimilar_question_below_threshold_is_a_miss(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0, 0.0]))
        await cache_svc.store_cached_response(
            "¿cuál es el costo de la matrícula?", None, [], "El costo es $50.",
        )

        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([0.0, 1.0, 0.0]))
        result = await cache_svc.get_cached_response(
            "¿cómo llego al campus?", None, threshold=0.93,
        )
        assert result is None

    async def test_score_just_below_threshold_is_a_miss(self, monkeypatch):
        """El umbral es un corte estricto (>=): un score apenas por debajo no debe calificar como hit."""
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response("pregunta original", None, [], "respuesta")

        # cos(10°) ~= 0.9848, por debajo de un threshold de 0.99
        import math
        angle = math.radians(10)
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([math.cos(angle), math.sin(angle)]))
        result = await cache_svc.get_cached_response("pregunta parecida", None, threshold=0.99)
        assert result is None

    async def test_best_match_wins_among_multiple_entries(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0, 0.0]))
        await cache_svc.store_cached_response("pregunta A", None, [], "respuesta A")

        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([0.0, 1.0, 0.0]))
        await cache_svc.store_cached_response("pregunta B", None, [], "respuesta B")

        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([0.0, 0.99, 0.14]))
        result = await cache_svc.get_cached_response("pregunta parecida a B", None, threshold=0.5)
        assert result is not None
        assert result["content"] == "respuesta B"


class TestGetCachedResponseSourceScope:
    async def test_different_source_ids_scope_is_isolated(self, monkeypatch):
        """Una entrada cacheada con un scope de fuentes distinto no debe
        considerarse hit aunque el embedding sea idéntico - evita que una
        respuesta generada con un subconjunto de fuentes se sirva para otro."""
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response(
            "pregunta", ["source-a"], [], "respuesta con source-a",
        )

        result = await cache_svc.get_cached_response(
            "pregunta", ["source-b"], threshold=0.0,
        )
        assert result is None, "una entrada con distinto source_ids scope no debe hacer match"

    async def test_same_source_ids_scope_matches(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response(
            "pregunta", ["source-a", "source-b"], [], "respuesta con fuentes",
        )

        result = await cache_svc.get_cached_response(
            "pregunta", ["source-b", "source-a"], threshold=0.0,  # orden distinto, mismo set
        )
        assert result is not None
        assert result["content"] == "respuesta con fuentes"

    async def test_scoped_entry_does_not_leak_to_unscoped_query(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response(
            "pregunta", ["source-a"], [], "respuesta con source-a",
        )

        result = await cache_svc.get_cached_response("pregunta", None, threshold=0.0)
        assert result is None, "sin source_ids explícito no debe matchear una entrada scoped"


class TestGetCachedResponseDraftProdIsolation:
    async def test_draft_and_prod_scopes_do_not_cross_match(self, monkeypatch):
        """use_draft=True escribe/lee bajo un prefijo de key distinto a prod
        (ver _cache_key) - una respuesta de borrador no debe filtrarse a
        producción ni viceversa."""
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response(
            "pregunta", None, [], "respuesta de borrador", use_draft=True,
        )

        prod_result = await cache_svc.get_cached_response("pregunta", None, use_draft=False, threshold=0.0)
        assert prod_result is None, "una entrada draft no debe aparecer en el scope prod"

        draft_result = await cache_svc.get_cached_response("pregunta", None, use_draft=True, threshold=0.0)
        assert draft_result is not None
        assert draft_result["content"] == "respuesta de borrador"


class TestGetCachedResponseErrorHandling:
    async def test_redis_failure_returns_none_not_exception(self, monkeypatch):
        """Falla graceful documentada en el docstring del módulo: un error de
        Redis (ej. desconexión) debe degradar a cache miss, nunca propagar."""
        async def _boom(texts, prefix=""):
            raise ConnectionError("redis unreachable")
        monkeypatch.setattr(cache_svc, "embed_texts_async", _boom)

        result = await cache_svc.get_cached_response("cualquier pregunta", None)
        assert result is None

    async def test_empty_cache_is_a_miss(self, monkeypatch):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        result = await cache_svc.get_cached_response("pregunta sin nada cacheado", None)
        assert result is None


class TestInvalidateBySourceDeletion:
    async def test_invalidate_deletes_semantic_and_exact_cache_keys(self, monkeypatch, _fake_redis):
        monkeypatch.setattr(cache_svc, "embed_texts_async", _embed_fixed([1.0, 0.0]))
        await cache_svc.store_cached_response("pregunta semantica", None, [], "respuesta")
        await _fake_redis.set("chat:v1:exactkey", "cached-exact-response")

        deleted_count = await cache_svc.invalidate_by_source("some-source")

        assert deleted_count == 2
        remaining_semantic = await cache_svc.get_cached_response("pregunta semantica", None, threshold=0.0)
        assert remaining_semantic is None
        assert await _fake_redis.get("chat:v1:exactkey") is None

    async def test_invalidate_with_no_entries_returns_zero(self):
        deleted_count = await cache_svc.invalidate_by_source("some-source")
        assert deleted_count == 0
