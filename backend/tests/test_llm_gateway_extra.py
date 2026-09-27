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
        extra_headers={},
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
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retryable_status_codes(self, status):
        req = httpx.Request("POST", "https://x.example.com")
        resp = httpx.Response(status, request=req)
        exc = httpx.HTTPStatusError("boom", request=req, response=resp)
        assert gw._is_retryable(exc) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
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
    async def test_azure_requires_api_key(self):
        with pytest.raises(RuntimeError, match="requiere una API key"):
            await gw._get_adapter("Azure Prov", "azure", "gpt-4", "https://x.openai.azure.com", None)

    async def test_azure_with_key_returns_azure_adapter(self):
        adapter = await gw._get_adapter("Azure Prov", "azure_openai", "gpt-4", "https://x.openai.azure.com", "key")
        assert isinstance(adapter, gw.AzureOpenAIAdapter)

    async def test_provider_type_is_case_and_whitespace_insensitive(self):
        adapter = await gw._get_adapter("Anthropic Prov", "  ANTHROPIC  ", "claude-3", None, "key")
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

    async def test_empty_stream_falls_back_and_reports_served_provider(self, monkeypatch):
        first = _make_provider(name="Primero", model_name="m1")
        second = _make_provider(name="Segundo", model_name="m2")

        async def fake_stream(self, messages, temperature, max_tokens):
            if self.model_name == "m1":
                return
            yield "respuesta"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        served: dict = {}
        chunks = [
            c async for c in gw.stream_chat(
                "pregunta", [], [(first, "k1"), (second, "k2")], served=served,
            )
        ]
        assert chunks == ["respuesta"]
        assert served == {"provider_name": "Segundo", "model_name": "m2"}

    async def test_all_empty_streams_raise(self, monkeypatch):
        provider = _make_provider()

        async def fake_stream(self, messages, temperature, max_tokens):
            return
            yield

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        with pytest.raises(RuntimeError, match="no está disponible"):
            async for _ in gw.stream_chat("pregunta", [], [(provider, "key")]):
                pass

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
        system_msg = captured["messages"][0]["content"]
        assert system_msg.startswith("Prompt custom con d")
        assert "[[CANARY_TOKEN_2024]]" in system_msg

    async def test_history_is_truncated_to_last_six_and_ordered_before_question(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_stream(self, messages, temperature, max_tokens):
            captured["messages"] = messages
            yield "x"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        history = [{"role": ("user", "assistant")[i % 2], "content": f"msg{i}"} for i in range(10)]
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

    async def test_falls_back_when_primary_has_invalid_config(self, monkeypatch):
        # provider_type "anthropic" exige api_key en _get_adapter(); se pasa
        # api_key=None para forzar el RuntimeError de configuración inválida.
        p1 = _make_provider(name="SinApiKey", provider_type="anthropic")
        p2 = _make_provider(name="Sano")

        async def ok_stream(self, messages, temperature, max_tokens):
            yield "resultado"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", ok_stream)

        chunks = [
            c async for c in gw.stream_chat(
                "pregunta", [{"text": "d"}], [(p1, None), (p2, "k2")]
            )
        ]
        assert chunks == ["resultado"]
        assert len(gw._breaker._failures.get(str(p1.id), [])) == 1

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

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return '{"grades": [true, false, true]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, False, True]

    async def test_never_forces_reasoning_effort_explicitly(self, monkeypatch):
        for provider_type in ("groq", "openai", "openrouter"):
            provider = _make_provider(provider_type=provider_type)
            captured = {}

            async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
                captured["reasoning_effort"] = reasoning_effort
                return '{"grades": [true]}'

            monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
            await gw.grade_documents("pregunta", [{"text": "a"}], provider, "key")
            assert captured["reasoning_effort"] is None

    async def test_retries_once_then_fails_open_on_persistent_short_array(self, monkeypatch):
        provider = _make_provider()
        llamadas = []

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            llamadas.append(1)
            return '{"grades": [false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, True, True]
        assert len(llamadas) == 2

    async def test_short_array_recovers_on_retry(self, monkeypatch):
        provider = _make_provider()
        respuestas = iter([
            '{"grades": [false]}',
            '{"grades": [true, false, true]}',
        ])

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return next(respuestas)

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, False, True]

    async def test_truncates_extra_grades(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return '{"grades": [false, false, false, false, false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [False]

    async def test_llm_failure_defaults_to_all_true_fail_open(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}, {"text": "b"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True, True]

    async def test_malformed_json_response_defaults_to_all_true(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return "esto no es json"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        docs = [{"text": "a"}]
        result = await gw.grade_documents("pregunta", docs, provider, "key")
        assert result == [True]

    async def test_truncates_document_text_in_prompt(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            captured["messages"] = messages
            return '{"grades": [true]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        long_text = "x" * 5000
        await gw.grade_documents("pregunta", [{"text": long_text}], provider, "key")
        user_msg = captured["messages"][1]["content"]
        assert "x" * gw._GRADE_EXCERPT_CHARS in user_msg
        assert "x" * (gw._GRADE_EXCERPT_CHARS + 1) not in user_msg


class TestOpenAICompatAdapterCompleteReasoningEffort:

    async def test_reasoning_effort_included_in_payload_when_set(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("groq", "openai/gpt-oss-120b", "key", "https://api.groq.com/openai/v1")
        await adapter.complete([{"role": "user", "content": "hi"}], reasoning_effort="low")
        assert captured["body"]["reasoning_effort"] == "low"

    async def test_reasoning_effort_omitted_from_payload_when_none(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("openai", "gpt-4o", "key", "https://api.openai.com/v1")
        await adapter.complete([{"role": "user", "content": "hi"}])
        assert "reasoning_effort" not in captured["body"]


class TestRewriteQuery:
    async def test_returns_cleaned_rewrite(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return "  - trámite matrícula requisitos  "

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.rewrite_query("como me matriculo", provider, "key")
        assert result == "trámite matrícula requisitos"

    async def test_llm_failure_falls_back_to_original_question(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            raise httpx.ReadTimeout("slow")

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.rewrite_query("pregunta original", provider, "key")
        assert result == "pregunta original"

    async def test_empty_rewrite_falls_back_to_original_question(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
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


class TestClassifyTopic:
    async def test_parses_topic_json_response(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return '{"topic": "becas"}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic("¿hay becas disponibles?", provider, "key")
        assert result == "Becas"

    async def test_falls_back_to_regex_on_malformed_json(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return 'claro, el tema es "topic": "Inscripciones" según lo pedido'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic("¿cómo me inscribo?", provider, "key")
        assert result == "Inscripciones"

    async def test_empty_response_returns_none(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return ""

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic("pregunta", provider, "key")
        assert result is None

    async def test_unparseable_response_returns_none(self, monkeypatch):
        provider = _make_provider()

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return "no puedo ayudar con eso"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic("pregunta", provider, "key")
        assert result is None

    async def test_exception_fails_open_to_none(self, monkeypatch):
        provider = _make_provider()

        async def failing_complete(self, *a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", failing_complete)
        result = await gw.classify_topic("pregunta", provider, "key")
        assert result is None

    async def test_truncates_to_128_chars(self, monkeypatch):
        provider = _make_provider()
        long_topic = "x" * 200

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            return f'{{"topic": "{long_topic}"}}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic("pregunta", provider, "key")
        assert result is not None
        assert len(result) == 128

    async def test_existing_topics_included_in_prompt(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            captured["system_prompt"] = messages[0]["content"]
            return '{"topic": "Inscripciones"}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        result = await gw.classify_topic(
            "¿cómo me inscribo?", provider, "key",
            existing_topics=["Inscripciones", "Becas"],
        )
        assert result == "Inscripciones"
        assert "Inscripciones" in captured["system_prompt"]
        assert "Becas" in captured["system_prompt"]

    async def test_no_existing_topics_omits_hint(self, monkeypatch):
        provider = _make_provider()
        captured = {}

        async def fake_complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
            captured["system_prompt"] = messages[0]["content"]
            return '{"topic": "Becas"}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        await gw.classify_topic("pregunta", provider, "key")
        assert "Temas ya existentes" not in captured["system_prompt"]


class TestAuxiliaryFallback:
    async def test_rewrite_uses_next_provider_when_primary_is_rate_limited(self, monkeypatch):
        primary = _make_provider(name="Groq", model_name="g")
        backup = _make_provider(name="Ollama", model_name="o")
        req = httpx.Request("POST", "https://x.example.com")

        async def fake_complete(self, messages, **kwargs):
            if self.model_name == "g":
                raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))
            return "requisitos graduación"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        gw.set_fallback_chain([(primary, "k1"), (backup, "k2")])

        assert await gw.rewrite_query("¿qué necesito para graduarme?", primary, "k1") == "requisitos graduación"

    async def test_grade_fails_open_only_when_every_provider_fails(self, monkeypatch):
        primary = _make_provider(name="Groq", model_name="g")
        backup = _make_provider(name="Ollama", model_name="o")

        async def fake_complete(self, messages, **kwargs):
            if self.model_name == "g":
                raise httpx.ConnectError("caído")
            return '{"grades": [true, false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        gw.set_fallback_chain([(primary, "k1"), (backup, "k2")])

        grades = await gw.grade_documents("p", [{"text": "a"}, {"text": "b"}], primary, "k1")
        assert grades == [True, False]

    async def test_grader_gives_up_on_slow_providers_within_its_budget(self, monkeypatch):
        import asyncio

        slow = _make_provider(name="Lento", model_name="lento")
        fast = _make_provider(name="Rápido", model_name="rapido")
        budget = 1.0

        async def fake_complete(self, messages, **kwargs):
            if self.model_name == "lento":
                await asyncio.sleep(5)
            return '{"grades": [false]}'

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        monkeypatch.setattr(gw, "_AUX_BUDGET_SECONDS", budget)
        monkeypatch.setattr(gw._complete, "__kwdefaults__", {"budget": budget})
        gw.set_fallback_chain([(slow, "k1"), (fast, "k2")])

        grades = await asyncio.wait_for(gw.grade_documents("p", [{"text": "a"}], slow, "k1"), timeout=3)

        assert grades == [True]

    async def test_open_circuit_provider_is_skipped(self, monkeypatch):
        primary = _make_provider(name="Groq", model_name="g")
        backup = _make_provider(name="Ollama", model_name="o")
        called = []

        async def fake_complete(self, messages, **kwargs):
            called.append(self.model_name)
            return "ok"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "complete", fake_complete)
        gw._breaker.force_open(str(primary.id))
        gw.set_fallback_chain([(primary, "k1"), (backup, "k2")])

        await gw.rewrite_query("pregunta", primary, "k1")
        assert called == ["o"]


class TestFirstTokenTimeout:
    async def test_silent_provider_is_skipped_for_the_next_one(self, monkeypatch):
        import asyncio

        slow = _make_provider(name="Lento", model_name="lento")
        fast = _make_provider(name="Rápido", model_name="rapido")

        async def fake_stream(self, messages, temperature, max_tokens):
            if self.model_name == "lento":
                await asyncio.sleep(5)
            yield "hola"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        monkeypatch.setattr(gw, "_FIRST_TOKEN_TIMEOUT", 0.2)
        served: dict = {}

        chunks = [c async for c in gw.stream_chat("p", [], [(slow, "k1"), (fast, "k2")], served=served)]

        assert chunks == ["hola"]
        assert served["provider_name"] == "Rápido"

    async def test_fallback_provider_gets_more_time(self, monkeypatch):
        import asyncio

        down = _make_provider(name="Caído", model_name="caido")
        slow_backup = _make_provider(name="Respaldo lento", model_name="respaldo")

        async def fake_stream(self, messages, temperature, max_tokens):
            if self.model_name == "caido":
                raise RuntimeError("sin cuota")
            await asyncio.sleep(0.4)
            yield "hola"

        monkeypatch.setattr(gw.OpenAICompatAdapter, "stream_chat", fake_stream)
        monkeypatch.setattr(gw, "_FIRST_TOKEN_TIMEOUT", 0.2)
        monkeypatch.setattr(gw, "_FALLBACK_FIRST_TOKEN_TIMEOUT", 1.0)
        served: dict = {}

        chunks = [c async for c in gw.stream_chat("p", [], [(down, "k1"), (slow_backup, "k2")], served=served)]

        assert chunks == ["hola"]
        assert served["provider_name"] == "Respaldo lento"


def test_turns_start_with_the_user_and_alternate():
    turns = gw._alternating_turns([
        {"role": "assistant", "content": "Hola, soy el asistente."},
        {"role": "user", "content": "¿Horario?"},
        {"role": "user", "content": "¿De la biblioteca?"},
        {"role": "assistant", "content": "De 7 a 17 h."},
        {"role": "user", "content": "¿Y sábados?"},
    ])

    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "¿Horario?\n\n¿De la biblioteca?"


async def test_stream_accepts_sse_lines_without_space(monkeypatch):
    def handler(request):
        body = 'data:{"choices":[{"delta":{"content":"Hola"}}]}\n\ndata:[DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    _patch_client(monkeypatch, handler)
    adapter = gw.OpenAICompatAdapter("openai", "m", "k", "https://x.test/v1")

    tokens = [t async for t in adapter.stream_chat([{"role": "user", "content": "hola"}])]

    assert tokens == ["Hola"]


@pytest.mark.parametrize("respuesta", ['{"grades": ["true", "false"]}', '[true, false]'])
async def test_grades_accept_bare_lists_and_quoted_values(monkeypatch, respuesta):
    async def _fake_complete(*args, **kwargs):
        return respuesta

    monkeypatch.setattr(gw, "_complete", _fake_complete)
    provider = SimpleNamespace(id=uuid.uuid4(), name="p")

    grades = await gw.grade_documents("¿Horario?", [{"text": "a"}, {"text": "b"}], provider, "k")

    assert grades == [True, False]
