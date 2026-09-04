"""Tests unitarios para app/services/rag/corrective.py.

Ejercita la lógica del LangGraph CRAG (expand → retrieve → grade → rewrite)
y las funciones auxiliares mockeando dependencias externas (embedding, Qdrant, LLM).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.corrective import (
    MAX_REWRITES,
    _classify_and_store_topic,
    _decide_after_grade,
    _expand,
    _maybe_flag_unanswered,
    _rewrite,
    grade_documents,
    run_adaptive_rag,
    run_corrective_rag,
    run_simple_rag,
)
from app.services.rag.router import QueryRoute

pytestmark = pytest.mark.asyncio

SAMPLE_DOC = {"id": "chunk-1", "content": "texto", "source_id": "src-1"}
SAMPLE_EMB = {"dense": [0.1], "sparse_indices": [0], "sparse_values": [0.5]}

# Provider stub for tests - external deps are mocked, so the actual value
# doesn't need to be a real LLMProvider row (just hashable / passable).
_PROVIDER_STUB = object()


def _make_state(**overrides):
    base = {
        "question": "¿Qué carrera ofrece?",
        "original_question": "¿Qué carrera ofrece?",
        "source_ids": None,
        "top_k": 5,
        "score_threshold": 0.0,
        "documents": [],
        "relevant_docs": [],
        "rewrite_count": 0,
        "provider": _PROVIDER_STUB,
        "api_key": None,
    }
    base.update(overrides)
    return base


class TestExpand:
    async def test_expands_using_rewrite_query(self):
        state = _make_state()
        with patch("app.services.rag.corrective.rewrite_query", AsyncMock(return_value="versión expandida")):
            result = await _expand(state)
        assert result == {"question": "versión expandida"}


class TestRetrieve:
    async def test_calls_hybrid_search_and_returns_docs(self):
        state = _make_state(top_k=5)
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=[SAMPLE_DOC])),
        ):
            result = await _retrieve(state)
        assert result["documents"] == [SAMPLE_DOC]


class TestGrade:
    async def test_returns_empty_when_no_docs(self):
        state = _make_state(documents=[])
        result = await _grade(state)
        assert result == {"relevant_docs": []}

    async def test_filters_by_grade(self):
        state = _make_state(documents=[SAMPLE_DOC, {"id": "chunk-2"}, {"id": "chunk-3"}])
        with patch("app.services.rag.corrective.grade_documents", AsyncMock(return_value=[True, False, True])):
            result = await _grade(state)
        assert len(result["relevant_docs"]) == 2
        assert result["relevant_docs"][0]["id"] == "chunk-1"
        assert result["relevant_docs"][1]["id"] == "chunk-3"


class TestDecideAfterGrade:
    def test_returns_done_when_relevant_docs_exist(self):
        state = _make_state(relevant_docs=[SAMPLE_DOC])
        assert _decide_after_grade(state) == "done"

    def test_returns_rewrite_when_below_max(self):
        state = _make_state(relevant_docs=[], rewrite_count=0)
        assert _decide_after_grade(state) == "rewrite"

    def test_returns_done_when_at_max_rewrites(self):
        state = _make_state(relevant_docs=[], rewrite_count=MAX_REWRITES)
        assert _decide_after_grade(state) == "done"


class TestRewrite:
    async def test_increments_rewrite_count(self):
        state = _make_state(rewrite_count=0)
        with patch("app.services.rag.corrective.rewrite_query", AsyncMock(return_value="refined")):
            result = await _rewrite(state)
        assert result["question"] == "refined"
        assert result["rewrite_count"] == 1


class TestMaybeFlagUnanswered:
    async def test_persists_question_when_conversation_id_provided(self):
        with patch("app.db.session.AsyncSessionLocal") as mock_local:
            fake_db = AsyncMock()
            fake_db.add = MagicMock()
            fake_db.__aenter__.return_value = fake_db
            mock_local.return_value = fake_db
            await _maybe_flag_unanswered("¿test?", conversation_id="00000000-0000-0000-0000-000000000001")
            fake_db.add.assert_called_once()
            fake_db.commit.assert_awaited_once()

    async def test_persists_question_when_no_conversation_id(self):
        with patch("app.db.session.AsyncSessionLocal") as mock_local:
            fake_db = AsyncMock()
            fake_db.add = MagicMock()
            fake_db.__aenter__.return_value = fake_db
            mock_local.return_value = fake_db
            await _maybe_flag_unanswered("¿test?")
            fake_db.add.assert_called_once()

    async def test_handles_exception_gracefully(self):
        with patch("app.db.session.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            await _maybe_flag_unanswered("¿test?")

    async def test_schedules_topic_classification_when_provider_given(self):
        """Con provider, debe programar una tarea de clasificación en
        background sin esperarla (fire-and-forget)."""
        import asyncio

        with patch("app.db.session.AsyncSessionLocal") as mock_local, \
             patch(
                 "app.services.rag.corrective._classify_and_store_topic",
                 new=AsyncMock(return_value=None),
             ) as mock_classify:
            fake_db = AsyncMock()
            fake_db.add = MagicMock()
            fake_db.__aenter__.return_value = fake_db
            mock_local.return_value = fake_db
            await _maybe_flag_unanswered(
                "¿test?", provider=_PROVIDER_STUB, api_key="key-123",
            )
            await asyncio.sleep(0)
            mock_classify.assert_called_once()

    async def test_no_topic_classification_without_provider(self):
        with patch("app.db.session.AsyncSessionLocal") as mock_local, \
             patch("app.services.rag.corrective._classify_and_store_topic") as mock_classify:
            fake_db = AsyncMock()
            fake_db.add = MagicMock()
            fake_db.__aenter__.return_value = fake_db
            mock_local.return_value = fake_db
            await _maybe_flag_unanswered("¿test?")
            mock_classify.assert_not_called()


class TestClassifyAndStoreTopic:
    async def test_stores_topic_when_classification_succeeds(self):
        with patch("app.services.ai.llm_gateway.classify_topic", new=AsyncMock(return_value="Becas")) as mock_cls, \
             patch("app.db.session.AsyncSessionLocal") as mock_local:
            fake_row = MagicMock(detected_topic=None)
            fake_db = AsyncMock()
            fake_db.get = AsyncMock(return_value=fake_row)
            fake_db.__aenter__.return_value = fake_db
            mock_local.return_value = fake_db

            await _classify_and_store_topic("q-1", "¿hay becas?", _PROVIDER_STUB, None)

            mock_cls.assert_awaited_once()
            assert fake_row.detected_topic == "Becas"
            fake_db.commit.assert_awaited_once()

    async def test_no_write_when_classification_returns_none(self):
        with patch("app.services.ai.llm_gateway.classify_topic", new=AsyncMock(return_value=None)), \
             patch("app.db.session.AsyncSessionLocal") as mock_local:
            fake_db = AsyncMock()
            mock_local.return_value = fake_db

            await _classify_and_store_topic("q-1", "¿hay becas?", _PROVIDER_STUB, None)

            mock_local.assert_not_called()

    async def test_handles_exception_gracefully(self):
        with patch("app.services.ai.llm_gateway.classify_topic", new=AsyncMock(return_value="Becas")), \
             patch("app.db.session.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            await _classify_and_store_topic("q-1", "¿hay becas?", _PROVIDER_STUB, None)


from app.services.rag.corrective import _retrieve, _grade


class TestRunSimpleRag:
    async def test_returns_empty_list_when_no_docs(self):
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=[])),
        ):
            docs, ratio = await run_simple_rag("¿Qué carrera ofrece?")
        assert docs == []
        assert ratio is None

    async def test_truncates_to_top_k(self):
        docs = [{"id": f"chunk-{i}"} for i in range(20)]
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=docs)),
        ):
            result, ratio = await run_simple_rag("¿Qué carrera ofrece?", top_k=5)
        assert len(result) == 5
        assert ratio == 1.0

    async def test_without_provider_skips_grading(self):
        """provider=None (default) - comportamiento histórico sin costo LLM."""
        docs = [{"id": "chunk-1"}, {"id": "chunk-2"}]
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=docs)),
            patch("app.services.rag.corrective.grade_documents", AsyncMock()) as mock_grade,
        ):
            result, ratio = await run_simple_rag("¿Qué carrera ofrece?")
        mock_grade.assert_not_called()
        assert result == docs
        assert ratio == 1.0

    async def test_with_provider_filters_by_grade(self):
        """provider pasado - el filtro de relevancia (mismo grade_documents que
        corrective RAG) descarta los chunks marcados como no relevantes, sin
        pasar por el ciclo expand/rewrite del grafo completo."""
        docs = [{"id": "chunk-1"}, {"id": "chunk-2"}, {"id": "chunk-3"}]
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=docs)),
            patch("app.services.rag.corrective.grade_documents", AsyncMock(return_value=[True, False, True])),
        ):
            result, ratio = await run_simple_rag("¿Qué carrera ofrece?", provider=_PROVIDER_STUB, api_key="key")
        assert result == [docs[0], docs[2]]
        assert ratio == 2 / 3

    async def test_no_docs_skips_grading_call(self):
        with (
            patch("app.services.rag.corrective.embed_texts_async", AsyncMock(return_value=[SAMPLE_EMB])),
            patch("app.services.rag.corrective.vector_store.hybrid_search", AsyncMock(return_value=[])),
            patch("app.services.rag.corrective.grade_documents", AsyncMock()) as mock_grade,
        ):
            result, ratio = await run_simple_rag("¿Qué carrera ofrece?", provider=_PROVIDER_STUB, api_key="key")
        mock_grade.assert_not_called()
        assert result == []
        assert ratio is None


class TestRunCorrectiveRag:
    async def test_invokes_graph_and_returns_relevant_docs(self):
        initial_doc = {"id": "chunk-1", "contenido": "test"}
        fake_graph = AsyncMock()
        fake_graph.ainvoke.return_value = {"documents": [initial_doc], "relevant_docs": [initial_doc]}
        with patch("app.services.rag.corrective._graph", fake_graph):
            result, ratio = await run_corrective_rag(
                question="¿Qué carrera ofrece?",
                provider=_PROVIDER_STUB,
                api_key=None,
            )
        assert result == [initial_doc]
        assert ratio == 1.0

    async def test_returns_empty_when_no_relevant_docs(self):
        fake_graph = AsyncMock()
        fake_graph.ainvoke.return_value = {"documents": [{"id": "chunk-1"}], "relevant_docs": []}
        with patch("app.services.rag.corrective._graph", fake_graph):
            result, ratio = await run_corrective_rag(
                question="¿Qué carrera ofrece?",
                provider=_PROVIDER_STUB,
                api_key=None,
            )
        assert result == []
        assert ratio == 0.0


class TestRunAdaptiveRag:
    async def test_greeting_route_returns_string(self):
        with patch("app.services.rag.router.classify_query", return_value=QueryRoute.GREETING):
            result = await run_adaptive_rag(
                question="hola",
                provider=_PROVIDER_STUB,
                api_key=None,
            )
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_greeting_route_uses_custom_response(self):
        with patch("app.services.rag.router.classify_query", return_value=QueryRoute.GREETING):
            result = await run_adaptive_rag(
                question="hola",
                provider=_PROVIDER_STUB,
                api_key=None,
                greeting_response="¡Bienvenido!",
            )
        assert result == "¡Bienvenido!"

    async def test_factual_route_calls_simple_rag(self):
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.FACTUAL),
            patch("app.services.rag.corrective.run_simple_rag", AsyncMock(return_value=([SAMPLE_DOC], 1.0))),
        ):
            result, ratio = await run_adaptive_rag(
                question="¿Cuándo hay clases?",
                provider=_PROVIDER_STUB,
                api_key=None,
            )
        assert result == [SAMPLE_DOC]
        assert ratio == 1.0

    async def test_factual_route_with_corrective_enabled_passes_provider_for_grading(self):
        """Regresión: preguntas factual con use_corrective_rag=True (default)
        deben pasar provider/api_key a run_simple_rag para activar el filtro
        de relevancia - sin esto, un retrieval con contexto ruidoso podía
        pasar chunks irrelevantes al LLM de generación sin verificar."""
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.FACTUAL),
            patch("app.services.rag.corrective.run_simple_rag", AsyncMock(return_value=([SAMPLE_DOC], 1.0))) as mock_simple,
        ):
            await run_adaptive_rag(
                question="¿Cuándo hay clases?",
                provider=_PROVIDER_STUB,
                api_key="real-key",
                use_corrective_rag=True,
            )
        _, kwargs = mock_simple.call_args
        assert kwargs["provider"] is _PROVIDER_STUB
        assert kwargs["api_key"] == "real-key"

    async def test_factual_route_with_corrective_disabled_skips_grading(self):
        """Si el admin desactivó corrective RAG por completo, factual no debe
        pagar el costo de grading tampoco - respeta la config existente."""
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.FACTUAL),
            patch("app.services.rag.corrective.run_simple_rag", AsyncMock(return_value=([SAMPLE_DOC], 1.0))) as mock_simple,
        ):
            await run_adaptive_rag(
                question="¿Cuándo hay clases?",
                provider=_PROVIDER_STUB,
                api_key="real-key",
                use_corrective_rag=False,
            )
        _, kwargs = mock_simple.call_args
        assert kwargs["provider"] is None
        assert kwargs["api_key"] is None

    async def test_factual_route_flags_unanswered_when_no_docs(self):
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.FACTUAL),
            patch("app.services.rag.corrective.run_simple_rag", AsyncMock(return_value=([], None))),
            patch("app.services.rag.corrective._maybe_flag_unanswered", AsyncMock()) as flag,
        ):
            result, ratio = await run_adaptive_rag(
                question="¿Cuándo hay clases?",
                provider=_PROVIDER_STUB,
                api_key=None,
                conversation_id="00000000-0000-0000-0000-000000000001",
            )
        assert result == []
        assert ratio is None
        flag.assert_awaited_once()

    async def test_no_corrective_rag_uses_simple_rag(self):
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.COMPLEX),
            patch("app.services.rag.corrective.run_simple_rag", AsyncMock(return_value=([SAMPLE_DOC], 1.0))),
        ):
            result, ratio = await run_adaptive_rag(
                question="Diferencia entre X y Y",
                provider=_PROVIDER_STUB,
                api_key=None,
                use_corrective_rag=False,
            )
        assert result == [SAMPLE_DOC]
        assert ratio == 1.0

    async def test_complex_route_calls_corrective_rag(self):
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.COMPLEX),
            patch("app.services.rag.corrective.run_corrective_rag", AsyncMock(return_value=([SAMPLE_DOC], 1.0))),
        ):
            result, ratio = await run_adaptive_rag(
                question="Diferencia entre X y Y",
                provider=_PROVIDER_STUB,
                api_key=None,
                use_corrective_rag=True,
            )
        assert result == [SAMPLE_DOC]
        assert ratio == 1.0

    async def test_complex_route_flags_unanswered_when_no_docs(self):
        with (
            patch("app.services.rag.router.classify_query", return_value=QueryRoute.COMPLEX),
            patch("app.services.rag.corrective.run_corrective_rag", AsyncMock(return_value=([], None))),
            patch("app.services.rag.corrective._maybe_flag_unanswered", AsyncMock()) as flag,
        ):
            result, ratio = await run_adaptive_rag(
                question="Diferencia entre X y Y",
                provider=_PROVIDER_STUB,
                api_key=None,
                use_corrective_rag=True,
                conversation_id="00000000-0000-0000-0000-000000000001",
            )
        assert result == []
        assert ratio is None
        flag.assert_awaited_once()
