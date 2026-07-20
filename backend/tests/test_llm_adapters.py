"""Tests del parsing real de cada LLMAdapter contra respuestas HTTP simuladas.

Ningún test previo ejercitaba el parsing SSE/JSON real de los adaptadores —
todos mockeaban `stream_chat` completo (ver test_chat_smoke.py), saltando el
código que realmente interpreta la respuesta de cada proveedor. Un modelo
"custom" (cualquier provider_type sin adaptador dedicado) siempre cae en
OpenAICompatAdapter (ver docstring de llm_gateway.py) — estos tests
verifican que ese adaptador parsea correctamente el formato estándar y
tolera variaciones/ruido sin romperse silenciosamente.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.ai import llm_gateway as gw


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _reset_http_client(monkeypatch):
    """Evita que un cliente real quede cacheado entre tests."""
    monkeypatch.setattr(gw, "_http_client", None)
    yield
    monkeypatch.setattr(gw, "_http_client", None)


def _patch_client(monkeypatch, handler) -> None:
    client = _mock_client(handler)
    monkeypatch.setattr(gw, "_get_http_client", lambda: client)


class TestOpenAICompatAdapterStreaming:
    """OpenAICompatAdapter es el que usa CUALQUIER modelo custom."""

    async def test_parses_standard_sse_stream(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"choices":[{"delta":{"content":"Hola"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":" mundo"}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("custom", "my-model", "key", "https://custom.example.com/v1")

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola", " mundo"]

    async def test_ignores_malformed_json_lines_without_crashing(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                'data: {esto no es json valido\n\n'
                'data: {"choices":[]}\n\n'
                'data: {"choices":[{"delta":{}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("custom", "my-model", "key", "https://custom.example.com/v1")

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["ok"]

    async def test_ignores_non_data_lines(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                ": comentario de keep-alive\n\n"
                'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("custom", "my-model", "key", "https://custom.example.com/v1")

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["x"]

    async def test_complete_non_streaming(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "respuesta completa"}}]
            })

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("custom", "my-model", "key", "https://custom.example.com/v1")

        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result == "respuesta completa"

    async def test_complete_raises_on_http_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        _patch_client(monkeypatch, handler)
        adapter = gw.OpenAICompatAdapter("custom", "my-model", "key", "https://custom.example.com/v1")

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.complete([{"role": "user", "content": "hi"}])

    def test_missing_api_base_raises_clear_error(self):
        with pytest.raises(ValueError, match="URL base desconocida"):
            gw.OpenAICompatAdapter("un-provider-inventado", "model", "key", None)

    def test_appends_chat_completions_path(self):
        adapter = gw.OpenAICompatAdapter("custom", "model", "key", "https://custom.example.com/v1")
        assert adapter._chat_url() == "https://custom.example.com/v1/chat/completions"

    def test_does_not_duplicate_chat_completions_path(self):
        adapter = gw.OpenAICompatAdapter(
            "custom", "model", "key", "https://custom.example.com/v1/chat/completions"
        )
        assert adapter._chat_url() == "https://custom.example.com/v1/chat/completions"


class TestAnthropicAdapter:
    async def test_parses_content_block_delta_events(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"type":"message_start"}\n\n'
                'data: {"type":"content_block_delta","delta":{"text":"Hola"}}\n\n'
                'data: {"type":"content_block_delta","delta":{"text":" mundo"}}\n\n'
                'data: {"type":"message_stop"}\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.AnthropicAdapter("claude-3", "key", None)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola", " mundo"]

    def test_splits_system_message_from_conversation(self):
        adapter = gw.AnthropicAdapter("claude-3", "key", None)
        system, conv = adapter._split_system([
            {"role": "system", "content": "Eres un bot"},
            {"role": "user", "content": "hola"},
        ])
        assert system == "Eres un bot"
        assert conv == [{"role": "user", "content": "hola"}]

    def test_empty_conversation_falls_back_to_ping(self):
        adapter = gw.AnthropicAdapter("claude-3", "key", None)
        _, conv = adapter._split_system([{"role": "system", "content": "Eres un bot"}])
        assert conv == [{"role": "user", "content": "ping"}]


class TestGeminiAdapter:
    async def test_parses_streaming_sse_candidates(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"candidates":[{"content":{"parts":[{"text":"Hola"}]}}]}\n\n'
                'data: {"candidates":[{"content":{"parts":[{"text":" mundo"}]}}]}\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola", " mundo"]

    async def test_ignores_malformed_json_and_empty_candidates(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n\n'
                'data: {esto no es json\n\n'
                'data: {"candidates":[]}\n\n'
                'data: {"candidates":[{"content":{"parts":[]}}]}\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["ok"]

    async def test_complete_joins_text_parts(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "candidates": [
                    {"content": {"parts": [{"text": "respuesta "}, {"text": "completa"}]}}
                ]
            })

        _patch_client(monkeypatch, handler)
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)

        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result == "respuesta completa"

    async def test_complete_raises_on_http_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        _patch_client(monkeypatch, handler)
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.complete([{"role": "user", "content": "hi"}])

    def test_splits_system_instruction_from_contents(self):
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)
        system, contents = adapter._to_gemini_contents([
            {"role": "system", "content": "Eres un bot"},
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "hola de vuelta"},
        ])
        assert system == "Eres un bot"
        assert contents == [
            {"role": "user", "parts": [{"text": "hola"}]},
            {"role": "model", "parts": [{"text": "hola de vuelta"}]},
        ]

    def test_empty_contents_falls_back_to_ping(self):
        adapter = gw.GeminiAdapter("gemini-1.5-flash", "key", None)
        _, contents = adapter._to_gemini_contents([{"role": "system", "content": "Eres un bot"}])
        assert contents == [{"role": "user", "parts": [{"text": "ping"}]}]


class TestCohereAdapter:
    async def test_parses_content_delta_events(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"type":"message-start"}\n\n'
                'data: {"type":"content-delta","delta":{"message":{"content":{"text":"Hola"}}}}\n\n'
                'data: {"type":"content-delta","delta":{"message":{"content":{"text":" mundo"}}}}\n\n'
                'data: {"type":"message-end"}\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.CohereAdapter("command-r", "key", None)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola", " mundo"]

    async def test_ignores_malformed_json_lines(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'data: {"type":"content-delta","delta":{"message":{"content":{"text":"ok"}}}}\n\n'
                'data: {esto no es json valido\n\n'
                'data: {"type":"content-delta","delta":{}}\n\n'
            )
            return httpx.Response(200, text=body)

        _patch_client(monkeypatch, handler)
        adapter = gw.CohereAdapter("command-r", "key", None)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["ok"]

    async def test_complete_joins_text_blocks(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "message": {
                    "content": [
                        {"type": "text", "text": "respuesta "},
                        {"type": "text", "text": "completa"},
                    ]
                }
            })

        _patch_client(monkeypatch, handler)
        adapter = gw.CohereAdapter("command-r", "key", None)

        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result == "respuesta completa"

    async def test_complete_raises_on_http_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        _patch_client(monkeypatch, handler)
        adapter = gw.CohereAdapter("command-r", "key", None)

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.complete([{"role": "user", "content": "hi"}])

    def test_normalizes_unknown_roles_to_user(self):
        adapter = gw.CohereAdapter("command-r", "key", None)
        msgs = adapter._to_cohere_messages([
            {"role": "system", "content": "Eres un bot"},
            {"role": "tool", "content": "resultado raro"},
        ])
        assert msgs == [
            {"role": "system", "content": "Eres un bot"},
            {"role": "user", "content": "resultado raro"},
        ]

    def test_empty_messages_falls_back_to_ping(self):
        adapter = gw.CohereAdapter("command-r", "key", None)
        msgs = adapter._to_cohere_messages([])
        assert msgs == [{"role": "user", "content": "ping"}]


class TestBedrockAdapter:
    """BedrockAdapter usa boto3 (sync) en un executor — se mockea el cliente boto3."""

    class _FakeBotoClient:
        def __init__(self, stream_events=None, converse_response=None):
            self._stream_events = stream_events or []
            self._converse_response = converse_response or {}
            self.last_converse_kwargs = None
            self.last_stream_kwargs = None

        def converse_stream(self, **kwargs):
            self.last_stream_kwargs = kwargs
            return {"stream": self._stream_events}

        def converse(self, **kwargs):
            self.last_converse_kwargs = kwargs
            return self._converse_response

    async def test_stream_chat_yields_text_deltas(self, monkeypatch):
        fake_client = self._FakeBotoClient(stream_events=[
            {"contentBlockDelta": {"delta": {"text": "Hola"}}},
            {"contentBlockDelta": {"delta": {"text": " mundo"}}},
            {"messageStop": {}},
        ])
        adapter = gw.BedrockAdapter("anthropic.claude-3-sonnet-20240229-v1:0", None, "us-east-1")
        monkeypatch.setattr(adapter, "_get_bedrock_client", lambda: fake_client)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["Hola", " mundo"]

    async def test_stream_chat_skips_events_without_text(self, monkeypatch):
        fake_client = self._FakeBotoClient(stream_events=[
            {"contentBlockDelta": {"delta": {"text": "ok"}}},
            {"contentBlockDelta": {"delta": {}}},
            {"metadata": {"usage": {"inputTokens": 10}}},
        ])
        adapter = gw.BedrockAdapter("anthropic.claude-3-sonnet-20240229-v1:0", None, "us-east-1")
        monkeypatch.setattr(adapter, "_get_bedrock_client", lambda: fake_client)

        chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
        assert chunks == ["ok"]

    async def test_complete_joins_output_text_blocks(self, monkeypatch):
        fake_client = self._FakeBotoClient(converse_response={
            "output": {"message": {"content": [{"text": "respuesta "}, {"text": "completa"}]}}
        })
        adapter = gw.BedrockAdapter("anthropic.claude-3-sonnet-20240229-v1:0", None, "us-east-1")
        monkeypatch.setattr(adapter, "_get_bedrock_client", lambda: fake_client)

        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result == "respuesta completa"

    async def test_complete_splits_system_messages(self, monkeypatch):
        fake_client = self._FakeBotoClient(converse_response={
            "output": {"message": {"content": [{"text": "ok"}]}}
        })
        adapter = gw.BedrockAdapter("anthropic.claude-3-sonnet-20240229-v1:0", None, "us-east-1")
        monkeypatch.setattr(adapter, "_get_bedrock_client", lambda: fake_client)

        await adapter.complete([
            {"role": "system", "content": "Eres un bot"},
            {"role": "user", "content": "hola"},
        ])
        assert fake_client.last_converse_kwargs["system"] == [{"text": "Eres un bot"}]
        assert fake_client.last_converse_kwargs["messages"] == [
            {"role": "user", "content": [{"text": "hola"}]}
        ]

    async def test_complete_empty_conversation_falls_back_to_ping(self, monkeypatch):
        fake_client = self._FakeBotoClient(converse_response={
            "output": {"message": {"content": [{"text": "pong"}]}}
        })
        adapter = gw.BedrockAdapter("anthropic.claude-3-sonnet-20240229-v1:0", None, "us-east-1")
        monkeypatch.setattr(adapter, "_get_bedrock_client", lambda: fake_client)

        await adapter.complete([{"role": "system", "content": "Eres un bot"}])
        assert fake_client.last_converse_kwargs["messages"] == [
            {"role": "user", "content": [{"text": "ping"}]}
        ]


class TestAdapterFactory:
    def test_unknown_provider_type_uses_openai_compat(self):
        adapter = gw._get_adapter("mi-servidor-custom", "mi-servidor-custom", "model", "https://x.example.com", "key")
        assert isinstance(adapter, gw.OpenAICompatAdapter)

    def test_known_cloud_provider_without_key_raises(self):
        with pytest.raises(RuntimeError, match="requiere una API key"):
            gw._get_adapter("Anthropic", "anthropic", "claude-3", None, None)

    def test_ollama_style_local_provider_without_key_is_allowed(self):
        adapter = gw._get_adapter("ollama", "ollama", "llama3", "http://localhost:11434/v1", None)
        assert isinstance(adapter, gw.OpenAICompatAdapter)
