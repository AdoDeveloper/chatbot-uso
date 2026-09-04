"""Tests para app/services/ai/embedding.py - sin cobertura propia hasta ahora,
solo se ejercía indirectamente vía mocks en los módulos que lo consumen.

Los tests rápidos mockean _get_dense_model/_get_sparse_model (nunca cargan
fastembed real). El test de integración, marcado @pytest.mark.slow, carga el
modelo ONNX real una sola vez para verificar que sigue produciendo embeddings
coherentes - se excluye de las corridas normales con `pytest -m "not slow"`.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.services.ai import embedding


class _FakeVector:
    """Imita el objeto que fastembed.TextEmbedding.embed() produce por texto."""

    def __init__(self, values: list[float]):
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeSparseVector:
    def __init__(self, indices: list[int], values: list[float]):
        self.indices = _FakeVector(indices)
        self.values = _FakeVector(values)


class _FakeDenseModel:
    """Registra los textos recibidos para verificar el prefijo aplicado."""

    def __init__(self):
        self.received: list[str] = []

    def embed(self, texts):
        self.received.extend(texts)
        return [_FakeVector([0.1, 0.2, 0.3]) for _ in texts]


class _FakeSparseModel:
    def __init__(self):
        self.received: list[str] = []

    def embed(self, texts):
        self.received.extend(texts)
        return [_FakeSparseVector([1, 5], [0.9, 0.4]) for _ in texts]


@pytest.fixture
def fake_models(monkeypatch):
    dense = _FakeDenseModel()
    sparse = _FakeSparseModel()
    monkeypatch.setattr(embedding, "_get_dense_model", lambda: dense)
    monkeypatch.setattr(embedding, "_get_sparse_model", lambda: sparse)
    return dense, sparse


class TestOnnxProviders:
    def _fake_onnxruntime(self, monkeypatch, available: list[str]):
        fake = types.ModuleType("onnxruntime")
        fake.get_available_providers = lambda: available
        monkeypatch.setitem(sys.modules, "onnxruntime", fake)

    def test_prefers_cuda_when_available(self, monkeypatch):
        self._fake_onnxruntime(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
        assert embedding._onnx_providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_falls_back_to_cpu_without_cuda(self, monkeypatch):
        self._fake_onnxruntime(monkeypatch, ["CPUExecutionProvider"])
        assert embedding._onnx_providers() == ["CPUExecutionProvider"]

    def test_falls_back_to_cpu_when_onnxruntime_is_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "onnxruntime", None)
        assert embedding._onnx_providers() == ["CPUExecutionProvider"]


class TestEmbedTexts:
    def test_empty_list_returns_empty_without_loading_models(self, monkeypatch):
        """Una lista vacía no debe intentar calcular dense_dim sobre un
        resultado inexistente, ni cargar los modelos ONNX para un input que
        de todas formas no produce nada."""
        def _fail_if_called():
            raise AssertionError("no debería cargar el modelo dense para una lista vacía")

        monkeypatch.setattr(embedding, "_get_dense_model", _fail_if_called)
        monkeypatch.setattr(embedding, "_get_sparse_model", _fail_if_called)

        assert embedding.embed_texts([]) == []

    def test_applies_the_prefix_before_embedding(self, fake_models):
        dense, sparse = fake_models
        embedding.embed_texts(["hola", "adiós"], prefix="query: ")

        assert dense.received == ["query: hola", "query: adiós"]
        assert sparse.received == ["query: hola", "query: adiós"]

    def test_omits_the_prefix_when_not_given(self, fake_models):
        dense, _ = fake_models
        embedding.embed_texts(["hola"])

        assert dense.received == ["hola"]

    def test_result_shape_has_dense_and_sparse_fields(self, fake_models):
        result = embedding.embed_texts(["hola"])

        assert len(result) == 1
        assert result[0]["dense"] == [0.1, 0.2, 0.3]
        assert result[0]["sparse_indices"] == [1, 5]
        assert result[0]["sparse_values"] == [0.9, 0.4]

    def test_preserves_input_order(self, fake_models):
        dense, _ = fake_models
        dense.embed = lambda texts: [_FakeVector([float(i)]) for i, _ in enumerate(texts)]

        result = embedding.embed_texts(["a", "b", "c"])

        assert [r["dense"] for r in result] == [[0.0], [1.0], [2.0]]


class TestEmbedTextsAsync:
    async def test_delegates_to_the_sync_function(self, fake_models):
        result = await embedding.embed_texts_async(["hola"], prefix="passage: ")
        assert result[0]["dense"] == [0.1, 0.2, 0.3]

    async def test_serializes_concurrent_calls_through_the_semaphore(self, fake_models):
        """_ONNX_SEM(1) garantiza una sola inferencia ONNX a la vez: dos
        llamadas concurrentes no deben solaparse en el tiempo."""
        dense, _ = fake_models
        active = 0
        max_concurrent = 0

        def _tracking_embed(texts):
            nonlocal active, max_concurrent
            active += 1
            max_concurrent = max(max_concurrent, active)
            active -= 1
            return [_FakeVector([0.0]) for _ in texts]

        dense.embed = _tracking_embed

        await asyncio.gather(
            embedding.embed_texts_async(["uno"]),
            embedding.embed_texts_async(["dos"]),
            embedding.embed_texts_async(["tres"]),
        )

        assert max_concurrent == 1


@pytest.mark.slow
class TestEmbedTextsRealModel:
    """Carga el modelo ONNX real (multilingual-e5-large + Qdrant/bm25).
    No se mockea nada aquí a propósito: es la única verificación de que el
    modelo real sigue disponible y produce embeddings con sentido semántico.
    """

    async def test_real_embedding_has_the_expected_dense_dimension(self):
        result = await embedding.embed_texts_async(["hola, ¿cómo estás?"], prefix="query: ")
        assert len(result[0]["dense"]) == 1024

    async def test_semantically_related_words_are_closer_than_unrelated_ones(self):
        import numpy as np

        words = ["gato", "perro", "factura"]
        result = await embedding.embed_texts_async(
            [f"passage: {w}" for w in words]
        )
        vecs = [np.array(r["dense"]) for r in result]

        def cos(a, b):
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        gato_perro = cos(vecs[0], vecs[1])
        gato_factura = cos(vecs[0], vecs[2])
        assert gato_perro > gato_factura
