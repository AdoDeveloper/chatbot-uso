"""Tests de la lógica de orquestación del LLM Gateway que NO es específica de
un adaptador: circuit breaker, retries, selección/fallback entre proveedores
en la cadena, fetch_models, test_connection, grade_documents, rewrite_query
y el helper _clean_rewrite.

test_llm_adapters.py ya cubre el parsing SSE/JSON de cada adaptador — este
archivo cubre el código que decide QUÉ adaptador usar, CUÁNDO reintentar,
CUÁNDO saltar a otro proveedor de la cadena, y qué mensaje de error final
llega al usuario cuando todo falla. Es exactamente el código que puede fallar
silenciosamente en producción si el fallback nunca se dispara.
"""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.ai import llm_gateway as gw


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _reset_http_client(monkeypatch):
    monkeypatch.setattr(gw, "_http_client", None)
    monkeypatch.setattr(gw, "_breaker", gw.CircuitBreaker())
    yield
    monkeypatch.setattr(gw, "_http_client", None)


def _patch_client(monkeypatch, handler) -> None:
    client = _mock_client(handler)
    monkeypatch.setattr(gw, "_get_http_client", lambda: client)


def _make_provider(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        name="Test Provider",
        provider_type="custom",
        model_name="my-model",
        api_base="https://custom.example.com/v1",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestGetHttpClient:
    def test_creates_client_once_and_reuses(self, monkeypatch):
        monkeypatch.setattr(gw, "_http_client", None)
        c1 = gw._get_http_client()
        c2 = gw._get_http_client()
        assert c1 is c2

    def test_recreates_client_if_closed(self, monkeypatch):
        monkeypatch.setattr(gw, "_http_client", None)
        c1 = gw._get_http_client()
        monkeypatch.setattr(type(c1), "is_closed", property(lambda self: True))
        c2 = gw._get_http_client()
        assert c2 is not None
        assert c2 is not c1


class TestIsRetryable:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_status_codes(self, status):
        req = httpx.Request("POST", "https://x.example.com")
        resp = httpx.Response(status, request=req)
        exc = httpx.HTTPStatusError("boom", request=req, response=resp)
        assert gw._is_retryable(exc) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_non_retryable_status_codes(self, status):
        req = httpx.Request("POST", "https://x.example.com")
        resp = httpx.Response(status, request=req)
        exc = httpx.HTTPStatusError("boom", request=req, response=resp)
        assert gw._is_retryable(exc) is False

    def test_connect_error_is_retryable(self):
        assert gw._is_retryable(httpx.ConnectError("conn refused")) is True

    def test_read_timeout_is_retryable(self):
        assert gw._is_retryable(httpx.ReadTimeout("timed out")) is True

    def test_generic_exception_is_not_retryable(self):
        assert gw._is_retryable(ValueError("weird")) is False


class TestCircuitBreaker:
    def test_starts_closed(self):
        b = gw.CircuitBreaker()
        assert b.is_open("p1") is False

    def test_opens_after_threshold_failures(self):
        b = gw.CircuitBreaker(failure_threshold=3, window=60, cooldown=30)
        b.record_failure("p1")
        b.record_failure("p1")
        assert b.is_open("p1") is False
        b.record_failure("p1")
        assert b.is_open("p1") is True

    def test_success_resets_failure_count(self):
        b = gw.CircuitBreaker(failure_threshold=3, window=60, cooldown=30)
        b.record_failure("p1")
        b.record_failure("p1")
        b.record_success("p1")
        b.record_failure("p1")
        assert b.is_open("p1") is False

    def test_closes_again_after_cooldown_expires(self, monkeypatch):
        b = gw.CircuitBreaker(failure_threshold=1, window=60, cooldown=30)
        t0 = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: t0)
        b.record_failure("p1")
        assert b.is_open("p1") is True

        monkeypatch.setattr(time, "monotonic", lambda: t0 + 31)
        assert b.is_open("p1") is False

    def test_failures_outside_window_are_dropped(self, monkeypatch):
        b = gw.CircuitBreaker(failure_threshold=2, window=10, cooldown=30)
        t0 = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: t0)
        b.record_failure("p1")

        monkeypatch.setattr(time, "monotonic", lambda: t0 + 20)
        b.record_failure("p1")
        assert b.is_open("p1") is False

    def test_independent_per_provider(self):
        b = gw.CircuitBreaker(failure_threshold=1, window=60, cooldown=30)
        b.record_failure("p1")
        assert b.is_open("p1") is True
        assert b.is_open("p2") is False


class TestGetAdapterAzure:
    def test_azure_requires_api_key(self):
        with pytest.raises(RuntimeError, match="requiere una API key"):
            gw._get_adapter("Azure Prov", "azure", "gpt-4", "https://x.openai.azure.com", None)

    def test_azure_with_key_returns_azure_adapter(self):
        adapter = gw._get_adapter("Azure Prov", "azure_openai", "gpt-4", "https://x.openai.azure.com", "key")
        assert isinstance(adapter, gw.AzureOpenAIAdapter)

    def test_provider_type_is_case_and_whitespace_insensitive(self):
        adapter = gw._get_adapter("Anthropic Prov", "  ANTHROPIC  ", "claude-3", None, "key")
        assert isinstance(adapter, gw.AnthropicAdapter)


class TestAzureOpenAIAdapterUrls:
    def test_chat_url_appends_deployment_path(self):
        adapter = gw.AzureOpenAIAdapter("gpt-4", "key", "https://x.openai.azure.com")
        url = adapter._chat_url()
        assert url.startswith("https://x.openai.azure.com/openai/deployments/gpt-4/chat/completions")
        assert "api-version=" in url

    def test_chat_url_not_duplicated_if_already_present(self):
        base = "https://x.openai.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2024-01-01"
        adapter = gw.AzureOpenAIAdapter("gpt-4", "key", base)
        assert adapter._chat_url() == base

    def test_headers_use_api_key_header_not_bearer(self):
        adapter = gw.AzureOpenAIAdapter("gpt-4", "secret123", "https://x.openai.azure.com")
        headers = adapter._headers()
        assert headers["api-key"] == "secret123"
        assert "Authorization" not in headers

    async def test_stream_chat_parses_sse(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"choices":[{"delta":{"content":"Hola"}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.AzureOpenAIAdapter("gpt-4", "key", "https://x.openai.azure.com")
        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola"]

    async def test_complete_returns_content(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _patch_client(monkeypatch, handler)
        adapter = gw.AzureOpenAIAdapter("gpt-4", "key", "https://x.openai.azure.com")
        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result == "ok"

    async def test_complete_raises_on_http_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        _patch_client(monkeypatch, handler)
        adapter = gw.AzureOpenAIAdapter("gpt-4", "key", "https://x.openai.azure.com")
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.complete([{"role": "user", "content": "hi"}])


class TestStreamChatOrchestration:
    """El corazón del fallback: stream_chat() de alto nivel que recorre la
    cadena de proveedores y decide cuándo pasar al siguiente."""

    async def test_raises_if_chain_is_empty(self):
        with pytest.raises(RuntimeError, match="No hay proveedores"):
            gen = gw.stream_chat("pregunta", [], [])
            await gen.__anext__()

    async def test_uses_context_chunks_when_present(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "respuesta"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        chunks = [
            c async for c in gw.stream_chat(
                "pregunta", [{"text": "dato relevante"}], [(provider, "key")]
            )
        ]
        assert chunks == ["respuesta"]
        system_msg = captured["messages"][0]["content"]
        assert "dato relevante" in system_msg

    async def test_uses_placeholder_when_no_context_chunks(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "x"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        async for _ in gw.stream_chat("pregunta", [], [(provider, "key")]):
            pass
        system_msg = captured["messages"][0]["content"]
        assert "SIN DOCUMENTOS RELEVANTES" in system_msg

    async def test_custom_system_prompt_overrides_template(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "x"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        async for _ in gw.stream_chat(
            "pregunta", [{"text": "d"}], [(provider, "key")],
            system_prompt="Prompt custom con {context}",
        ):
            pass
        assert captured["messages"][0]["content"] == "Prompt custom con d"

    async def test_history_is_truncated_to_last_six_and_ordered_before_question(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "x"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        async for _ in gw.stream_chat(
            "pregunta final", [{"text": "d"}], [(provider, "key")], history=history,
        ):
            pass
        msgs = captured["messages"]
        # system + last 6 history + final question
        assert len(msgs) == 1 + 6 + 1
        assert msgs[1]["content"] == "msg4"
        assert msgs[-2]["content"] == "msg9"
        assert msgs[-1]["content"] == "pregunta final"

    async def test_no_history_still_appends_question(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "x"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        async for _ in gw.stream_chat("sola pregunta", [], [(provider, "key")], history=None):
            pass
        msgs = captured["messages"]
        assert len(msgs) == 2
        assert msgs[-1] == {"role": "user", "content": "sola pregunta"}

    async def test_falls_back_to_second_provider_when_first_fails_before_any_token(self, monkeypatch):
        p1 = _make_provider(name="Fails")
        p2 = _make_provider(name="Works")

        async def fail_stream(self, messages, temperature, max_tokens):
            raise httpx.ConnectError("down")
            yield  # pragma: no cover

        async def ok_stream(self, messages, temperature, max_tokens):
            yield "resultado"

        call_count = {"n": 0}

        def stream_dispatch(self, messages, temperature, max_tokens):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fail_stream(self, messages, temperature, max_tokens)
            return ok_stream(self, messages, temperature, max_tokens)

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", stream_dispatch)

        chunks = [
            c async for c in gw.stream_chat(
                "pregunta", [{"text": "d"}], [(p1, "k1"), (p2, "k2")]
            )
        ]
        assert chunks == ["resultado"]
        assert call_count["n"] == 2

    async def test_does_not_fallback_once_tokens_were_already_yielded(self, monkeypatch):
        """Bug-sensitive: si el primer proveedor ya entregó tokens y luego se
        corta, NO debe reintentar con el siguiente proveedor (repetiría
        contenido parcial al usuario) — debe lanzar un error claro."""
        p1 = _make_provider(name="PartialFail")
        p2 = _make_provider(name="ShouldNotBeCalled")

        async def partial_then_fail(self, messages, temperature, max_tokens):
            yield "un poco de texto"
            raise httpx.ReadTimeout("cut mid-stream")

        second_call_happened = {"v": False}

        def stream_dispatch(self, messages, temperature, max_tokens):
            if self.model_name == p1.model_name and self.api_base == p1.api_base:
                return partial_then_fail(self, messages, temperature, max_tokens)
            second_call_happened["v"] = True

            async def ok():
                yield "no deberia llegar"
            return ok()

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", stream_dispatch)

        gen = gw.stream_chat("pregunta", [{"text": "d"}], [(p1, "k1"), (p2, "k2")])
        received = []
        with pytest.raises(RuntimeError, match="interrumpió"):
            async for tok in gen:
                received.append(tok)
        assert received == ["un poco de texto"]
        assert second_call_happened["v"] is False

    async def test_all_providers_fail_raises_generic_unavailable_error(self, monkeypatch):
        p1 = _make_provider(name="A")
        p2 = _make_provider(name="B")

        async def always_fail(self, messages, temperature, max_tokens):
            raise httpx.ConnectError("down")
            yield  # pragma: no cover

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", always_fail)

        with pytest.raises(RuntimeError, match="no está disponible"):
            async for _ in gw.stream_chat("pregunta", [{"text": "d"}], [(p1, "k1"), (p2, "k2")]):
                pass

    async def test_skips_provider_whose_circuit_is_open(self, monkeypatch):
        p1 = _make_provider(name="OpenCircuit")
        p2 = _make_provider(name="Healthy")

        gw._breaker.record_failure(str(p1.id))
        gw._breaker.record_failure(str(p1.id))
        gw._breaker.record_failure(str(p1.id))
        gw._breaker.record_failure(str(p1.id))
        gw._breaker.record_failure(str(p1.id))
        assert gw._breaker.is_open(str(p1.id)) is True

        calls = []

        async def ok_stream(self, messages, temperature, max_tokens):
            calls.append(self.model_name)
            yield "ok"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", ok_stream)

        chunks = [
            c async for c in gw.stream_chat(
                "pregunta", [{"text": "d"}], [(p1, "k1"), (p2, "k2")]
            )
        ]
        assert chunks == ["ok"]
        assert calls == [p2.model_name]

    async def test_success_records_breaker_success(self, monkeypatch):
        provider = _make_provider()

        async def ok_stream(self, messages, temperature, max_tokens):
            yield "ok"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", ok_stream)
        gw._breaker.record_failure(str(provider.id))

        async for _ in gw.stream_chat("pregunta", [{"text": "d"}], [(provider, "key")]):
            pass
        assert gw._breaker.is_open(str(provider.id)) is False

    async def test_failure_records_breaker_failure(self, monkeypatch):
        provider = _make_provider()

        async def fail_stream(self, messages, temperature, max_tokens):
            raise httpx.ConnectError("down")
            yield  # pragma: no cover

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fail_stream)

        with pytest.raises(RuntimeError):
            async for _ in gw.stream_chat("pregunta", [{"text": "d"}], [(provider, "key")]):
                pass

        # una sola falla no abre el breaker (umbral 5) pero sí quedó registrada
        assert len(gw._breaker._failures.get(str(provider.id), [])) == 1


class TestFetchModels:
    async def test_anthropic_maps_display_name(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "data": [{"id": "claude-3-opus", "display_name": "Claude 3 Opus"}]
            })

        _patch_client(monkeypatch, handler)
        models = await gw.fetch_models("anthropic", api_key="key")
        assert models == [{"id": "claude-3-opus", "name": "Claude 3 Opus"}]

    async def test_gemini_filters_by_generate_content_support(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "models": [
                    {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"],
                     "displayName": "Gemini 1.5 Flash"},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            })

        _patch_client(monkeypatch, handler)
        models = await gw.fetch_models("gemini", api_key="key")
        assert models == [{"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash"}]

    async def test_cohere_maps_name_field(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"name": "command-r"}, {"name": ""}]})

        _patch_client(monkeypatch, handler)
        models = await gw.fetch_models("cohere", api_key="key")
        assert models == [{"id": "command-r", "name": "command-r"}]

    async def test_openai_filters_chat_models_and_excludes_non_chat(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-audio-preview"},
                {"id": "whisper-1"},
                {"id": "text-embedding-3-small"},
                {"id": "o1-preview"},
            ]})

        _patch_client(monkeypatch, handler)
        models = await gw.fetch_models("openai", api_key="key")
        ids = [m["id"] for m in models]
        assert ids == sorted(["gpt-4o", "o1-preview"])

    async def test_generic_openai_compat_does_not_filter(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "llama3"}, {"id": "mixtral"}]})

        _patch_client(monkeypatch, handler)
        models = await gw.fetch_models("groq", api_key="key")
        assert models == [{"id": "llama3", "name": "llama3"}, {"id": "mixtral", "name": "mixtral"}]

    async def test_unknown_provider_without_api_base_raises_value_error(self):
        with pytest.raises(ValueError, match="URL base desconocida"):
            await gw.fetch_models("no-existe-este-proveedor")

    async def test_http_error_becomes_value_error_with_status_code(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        _patch_client(monkeypatch, handler)
        with pytest.raises(ValueError, match="error 401"):
            await gw.fetch_models("anthropic", api_key="bad-key")

    async def test_generic_connection_failure_becomes_value_error(self, monkeypatch):
        async def raise_conn_error(*args, **kwargs):
            raise httpx.ConnectError("dns failure")

        client = _mock_client(lambda r: httpx.Response(200))
        monkeypatch.setattr(client, "get", raise_conn_error)
        monkeypatch.setattr(gw, "_get_http_client", lambda: client)

        with pytest.raises(ValueError, match="No se pudo conectar"):
            await gw.fetch_models("anthropic", api_key="key")


class TestTestConnection:
    async def test_success_reports_latency(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

        _patch_client(monkeypatch, handler)
        result = await gw.test_connection("custom", "my-model", api_key="key", api_base="https://x.example.com/v1")
        assert result["success"] is True
        assert isinstance(result["latency_ms"], int)
        assert result["error"] is None

    async def test_failure_reports_error_string(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patch_client(monkeypatch, handler)
        result = await gw.test_connection("custom", "my-model", api_key="key", api_base="https://x.example.com/v1")
        assert result["success"] is False
        assert result["latency_ms"] is None
        assert result["error"] is not None

    async def test_missing_api_key_for_cloud_provider_reports_failure(self):
        """Regresión: test_connection() de alto nivel (llm_gateway.py) envuelve
        _get_adapter() en try/except para que un proveedor cloud sin api_key
        devuelva el mismo shape de error {"success": False, "error": ...} que
        LLMAdapter.test_connection(), en vez de propagar un RuntimeError sin
        capturar (antes rompía con 500 el endpoint /providers/test)."""
        result = await gw.test_connection("anthropic", "claude-3", api_key=None, api_base=None)
        assert result["success"] is False
        assert result["latency_ms"] is None
        assert "API key" in result["error"]


class TestGradeDocuments:
    async def test_empty_documents_returns_empty_list(self):
        provider = _make_provider()
        result = await gw.grade_documents("pregunta", [], provider, "key")
        assert result == []

    async def test_parses_grades_json_response(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return '{"grades": [true, false, true]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, False, True]

    async def test_pads_missing_grades_with_true(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return '{"grades": [false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [False, True, True]

    async def test_truncates_extra_grades(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return '{"grades": [false, false, false, false, false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [False]

    async def test_llm_failure_defaults_to_all_true_fail_open(self, monkeypatch):
        """Bug-sensitive: si el LLM evaluador falla, el sistema debe fallar
        ABIERTO (dejar pasar todos los documentos) para no bloquear
        respuestas legítimas por un error transitorio del grader."""
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, True]

    async def test_malformed_json_response_defaults_to_all_true(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return "esto no es json"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True]

    async def test_truncates_document_text_to_1000_chars_in_prompt(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            captured["messages"] = messages
            return '{"grades": [true]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        long_text = "x" * 5000
        await gw.grade_documents("pregunta", [{"text": long_text}], provider, "key")
        user_msg = captured["messages"][1]["content"]
        assert "x" * 1000 in user_msg
        assert "x" * 1001 not in user_msg


class TestRewriteQuery:
    async def test_returns_cleaned_rewrite(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return "  - trámite matrícula requisitos  "

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.rewrite_query("como me matriculo", provider, "key")
        assert result == "trámite matrícula requisitos"

    async def test_llm_failure_falls_back_to_original_question(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            raise httpx.ReadTimeout("slow")

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.rewrite_query("pregunta original", provider, "key")
        assert result == "pregunta original"

    async def test_empty_rewrite_falls_back_to_original_question(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None):
            return "   "

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.rewrite_query("pregunta original", provider, "key")
        assert result == "pregunta original"


class TestCleanRewrite:
    def test_strips_bullet_prefixes(self):
        assert gw._clean_rewrite("- trámite de matrícula") == "trámite de matrícula"

    def test_strips_numbered_prefixes(self):
        assert gw._clean_rewrite("1. requisitos de graduación") == "requisitos de graduación"

    def test_strips_asterisk_and_bullet_dot_prefixes(self):
        assert gw._clean_rewrite("* becas disponibles") == "becas disponibles"
        assert gw._clean_rewrite("• horario de clases") == "horario de clases"

    def test_takes_first_non_empty_line_only(self):
        text = "\n\ntrámite de matrícula\nrequisitos adicionales\n"
        assert gw._clean_rewrite(text) == "trámite de matrícula"

    def test_all_blank_lines_returns_stripped_original(self):
        assert gw._clean_rewrite("   \n   \n  ") == ""

    def test_plain_text_without_prefix_unchanged(self):
        assert gw._clean_rewrite("consulta de notas") == "consulta de notas"
