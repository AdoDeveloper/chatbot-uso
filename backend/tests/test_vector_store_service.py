"""Tests unitarios directos para app/services/ingestion/vector_store.py.

Este módulo encapsula operaciones contra Qdrant. No hay Qdrant real en el
entorno de test: se sustituye app.services.ingestion.vector_store._get_client
por un stub/AsyncMock que imita la interfaz de AsyncQdrantClient usada por
cada función. No duplica los casos ya cubiertos indirectamente por
test_chunks_router.py (que ejercía get_chunk/list_all_chunks/upsert_chunks
vía monkeypatch de esas mismas funciones, sin pasar por _get_client).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ingestion import vector_store as vs


def _point(point_id, payload, score=None):
    return SimpleNamespace(id=point_id, payload=payload, score=score)


class FakeCollectionsResult:
    def __init__(self, names):
        self.collections = [SimpleNamespace(name=n) for n in names]


@pytest.fixture
def fake_client():
    """AsyncMock que imita AsyncQdrantClient, con defaults razonables."""
    client = AsyncMock()
    client.get_collections.return_value = FakeCollectionsResult([])
    return client


@pytest.fixture
def patch_client(monkeypatch, fake_client):
    monkeypatch.setattr(vs, "_get_client", lambda: fake_client)
    return fake_client


class TestEnsureCollection:
    async def test_creates_collection_when_missing(self, patch_client):
        patch_client.get_collections.return_value = FakeCollectionsResult([])

        await vs.ensure_collection()

        patch_client.create_collection.assert_awaited_once()
        kwargs = patch_client.create_collection.call_args.kwargs
        assert kwargs["collection_name"] == vs.COLLECTION
        patch_client.create_payload_index.assert_awaited_once()

    async def test_skips_creation_when_collection_exists(self, patch_client):
        patch_client.get_collections.return_value = FakeCollectionsResult([vs.COLLECTION])

        await vs.ensure_collection()

        patch_client.create_collection.assert_not_awaited()
        # El índice de texto se intenta crear siempre, exista o no la colección.
        patch_client.create_payload_index.assert_awaited_once()

    async def test_swallows_already_exists_race_on_create(self, patch_client):
        patch_client.get_collections.return_value = FakeCollectionsResult([])
        patch_client.create_collection.side_effect = Exception("Collection already exists (409)")

        await vs.ensure_collection()  # no debe propagar

        patch_client.create_payload_index.assert_awaited_once()

    async def test_reraises_unexpected_error_on_create(self, patch_client):
        patch_client.get_collections.return_value = FakeCollectionsResult([])
        patch_client.create_collection.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await vs.ensure_collection()

    async def test_swallows_payload_index_errors(self, patch_client):
        patch_client.get_collections.return_value = FakeCollectionsResult([vs.COLLECTION])
        patch_client.create_payload_index.side_effect = Exception("index already exists")

        await vs.ensure_collection()  # no debe propagar


class TestUpsertChunks:
    async def test_upserts_points_with_expected_payload_and_vectors(self, patch_client):
        chunks = [
            {
                "text": "hola mundo",
                "source_id": "src-1",
                "source_name": "Fuente 1",
                "chunk_index": 0,
                "section": "Cap 1",
                "parent_id": "parent-1",
                "parent_text": "texto padre",
                "warnings": ["short"],
            },
            {
                "text": "segundo chunk",
                "source_id": "src-1",
                "source_name": "Fuente 1",
                "chunk_index": 1,
            },
        ]
        embeddings = [
            {"dense": [0.1, 0.2], "sparse_indices": [1], "sparse_values": [0.9]},
            {"dense": [0.3, 0.4], "sparse_indices": [2], "sparse_values": [0.8]},
        ]

        count = await vs.upsert_chunks(chunks, embeddings)

        assert count == 2
        patch_client.upsert.assert_awaited_once()
        kwargs = patch_client.upsert.call_args.kwargs
        assert kwargs["collection_name"] == vs.COLLECTION
        assert kwargs["wait"] is True
        points = kwargs["points"]
        assert len(points) == 2

        p0 = points[0]
        assert p0.payload["text"] == "hola mundo"
        assert p0.payload["source_id"] == "src-1"
        assert p0.payload["is_discarded"] is False
        assert p0.payload["section"] == "Cap 1"
        assert p0.payload["parent_id"] == "parent-1"
        assert p0.payload["parent_text"] == "texto padre"
        assert p0.payload["warnings"] == ["short"]
        assert p0.vector[vs.DENSE_VECTOR] == [0.1, 0.2]
        assert p0.vector[vs.SPARSE_VECTOR].indices == [1]
        assert p0.vector[vs.SPARSE_VECTOR].values == [0.9]
        # UUID válido como id
        uuid.UUID(p0.id)

        p1 = points[1]
        # Campos opcionales ausentes no deben aparecer en el payload
        assert "section" not in p1.payload
        assert "parent_id" not in p1.payload
        assert "parent_text" not in p1.payload
        assert p1.payload["warnings"] == []

    async def test_upsert_empty_lists_returns_zero(self, patch_client):
        count = await vs.upsert_chunks([], [])
        assert count == 0
        patch_client.upsert.assert_awaited_once()
        assert patch_client.upsert.call_args.kwargs["points"] == []


class TestListAllChunks:
    async def test_returns_chunks_sorted_by_chunk_index(self, patch_client):
        points = [
            _point("id-b", {"source_id": "src-1", "chunk_index": 2, "text": "b"}),
            _point("id-a", {"source_id": "src-1", "chunk_index": 0, "text": "a"}),
        ]
        patch_client.scroll.return_value = (points, None)

        result = await vs.list_all_chunks("src-1")

        assert [c["id"] for c in result] == ["id-a", "id-b"]
        assert result[0]["chunk_index"] == 0
        kwargs = patch_client.scroll.call_args.kwargs
        assert kwargs["collection_name"] == vs.COLLECTION
        assert kwargs["limit"] == vs.ALL_CHUNKS_CAP
        assert kwargs["with_vectors"] is False

    async def test_returns_empty_list_when_no_points(self, patch_client):
        patch_client.scroll.return_value = ([], None)

        result = await vs.list_all_chunks("src-empty")

        assert result == []

    async def test_missing_chunk_index_defaults_to_zero_for_sort(self, patch_client):
        points = [
            _point("id-1", {"source_id": "src-1", "text": "sin index"}),
            _point("id-2", {"source_id": "src-1", "chunk_index": -1, "text": "negativo"}),
        ]
        patch_client.scroll.return_value = (points, None)

        result = await vs.list_all_chunks("src-1")

        assert [c["id"] for c in result] == ["id-2", "id-1"]


class TestCountChunks:
    async def test_returns_count_from_client(self, patch_client):
        patch_client.count.return_value = SimpleNamespace(count=42)

        result = await vs.count_chunks("src-1")

        assert result == 42
        kwargs = patch_client.count.call_args.kwargs
        assert kwargs["collection_name"] == vs.COLLECTION
        assert kwargs["exact"] is True

    async def test_returns_zero_when_no_chunks(self, patch_client):
        patch_client.count.return_value = SimpleNamespace(count=0)

        result = await vs.count_chunks("src-empty")

        assert result == 0


class TestGetChunk:
    async def test_returns_none_when_not_found(self, patch_client):
        patch_client.retrieve.return_value = []

        result = await vs.get_chunk("missing-id")

        assert result is None

    async def test_returns_chunk_dict_when_found(self, patch_client):
        patch_client.retrieve.return_value = [
            _point("point-1", {"text": "hola", "source_id": "src-1"})
        ]

        result = await vs.get_chunk("point-1")

        assert result == {"id": "point-1", "text": "hola", "source_id": "src-1"}
        kwargs = patch_client.retrieve.call_args.kwargs
        assert kwargs["ids"] == ["point-1"]
        assert kwargs["with_vectors"] is False


class TestDeleteSource:
    async def test_calls_client_delete_with_source_filter(self, patch_client):
        await vs.delete_source("src-1")

        patch_client.delete.assert_awaited_once()
        kwargs = patch_client.delete.call_args.kwargs
        assert kwargs["collection_name"] == vs.COLLECTION
        selector = kwargs["points_selector"]
        assert selector.must[0].key == "source_id"
        assert selector.must[0].match.value == "src-1"


class TestHybridSearch:
    async def test_empty_source_ids_list_returns_empty_without_querying(self, patch_client):
        result = await vs.hybrid_search([0.1], {"indices": [], "values": []}, source_ids=[])

        assert result == []
        patch_client.query_points.assert_not_awaited()

    async def test_none_source_ids_searches_without_filter(self, patch_client):
        patch_client.query_points.return_value = SimpleNamespace(
            points=[_point("p1", {"source_id": "src-1"}, score=0.9)]
        )

        result = await vs.hybrid_search([0.1], {"indices": [1], "values": [0.5]}, source_ids=None)

        assert len(result) == 1
        assert result[0]["source_id"] == "src-1"
        kwargs = patch_client.query_points.call_args.kwargs
        # is_discarded always excluded, no explicit source filter -> only must_not present
        assert kwargs["query_filter"].must == []
        assert kwargs["query_filter"].must_not[0].key == "is_discarded"

    async def test_source_ids_applies_match_any_filter(self, patch_client):
        patch_client.query_points.return_value = SimpleNamespace(points=[])

        await vs.hybrid_search(
            [0.1], {"indices": [1], "values": [0.5]}, source_ids=["src-1", "src-2"], top_k=3
        )

        kwargs = patch_client.query_points.call_args.kwargs
        cond = kwargs["query_filter"].must[0]
        assert cond.key == "source_id"
        assert set(cond.match.any) == {"src-1", "src-2"}
        assert kwargs["limit"] == 3  # fetch_limit == top_k when source_ids given

    async def test_score_threshold_filters_low_scoring_docs(self, patch_client):
        patch_client.query_points.return_value = SimpleNamespace(
            points=[
                _point("p1", {"source_id": "src-1"}, score=0.9),
                _point("p2", {"source_id": "src-1"}, score=0.1),
            ]
        )

        result = await vs.hybrid_search(
            [0.1], {"indices": [1], "values": [0.5]}, score_threshold=0.5
        )

        assert len(result) == 1
        assert result[0]["score"] == 0.9

    async def test_parent_child_dedup_keeps_best_scoring_child(self, patch_client):
        patch_client.query_points.return_value = SimpleNamespace(
            points=[
                _point("p1", {"source_id": "src-1", "parent_id": "parent-A"}, score=0.9),
                _point("p2", {"source_id": "src-1", "parent_id": "parent-A"}, score=0.5),
                _point("p3", {"source_id": "src-1", "parent_id": "parent-B"}, score=0.8),
            ]
        )

        result = await vs.hybrid_search([0.1], {"indices": [1], "values": [0.5]}, top_k=5)

        parent_ids = [d["parent_id"] for d in result]
        assert parent_ids.count("parent-A") == 1
        assert result[0]["score"] == 0.9  # el de mayor score sobrevive

    async def test_source_diversity_cap_applies_without_explicit_filter(self, patch_client):
        # 5 docs de src-web dominante + 2 de src-doc, top_k=5 -> cap 60% = 3 de src-web
        web_docs = [
            _point(f"w{i}", {"source_id": "src-web"}, score=1.0 - i * 0.01) for i in range(5)
        ]
        doc_docs = [
            _point(f"d{i}", {"source_id": "src-doc"}, score=0.5 - i * 0.01) for i in range(2)
        ]
        patch_client.query_points.return_value = SimpleNamespace(points=web_docs + doc_docs)

        result = await vs.hybrid_search(
            [0.1], {"indices": [1], "values": [0.5]}, source_ids=None, top_k=5
        )

        assert len(result) == 5
        web_count = sum(1 for d in result if d["source_id"] == "src-web")
        doc_count = sum(1 for d in result if d["source_id"] == "src-doc")
        assert web_count == 3  # capped at round(5 * 0.6)
        assert doc_count == 2  # both non-dominant docs fill remaining slots

    async def test_diversity_cap_skipped_when_source_ids_given(self, patch_client):
        web_docs = [
            _point(f"w{i}", {"source_id": "src-web"}, score=1.0 - i * 0.01) for i in range(5)
        ]
        patch_client.query_points.return_value = SimpleNamespace(points=web_docs)

        result = await vs.hybrid_search(
            [0.1], {"indices": [1], "values": [0.5]}, source_ids=["src-web"], top_k=5
        )

        # Con filtro explícito de fuente no se aplica el cap de diversidad.
        assert len(result) == 5
        assert all(d["source_id"] == "src-web" for d in result)

    async def test_results_truncated_to_top_k_when_fewer_than_cap_case(self, patch_client):
        patch_client.query_points.return_value = SimpleNamespace(
            points=[_point("p1", {"source_id": "src-1"}, score=0.9)]
        )

        result = await vs.hybrid_search([0.1], {"indices": [1], "values": [0.5]}, top_k=5)

        assert len(result) == 1
