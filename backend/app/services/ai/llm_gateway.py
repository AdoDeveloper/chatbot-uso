"""
LLM Gateway — truly provider-agnostic streaming via httpx + native APIs.

Adapter families:
  - OpenAICompatAdapter: OpenAI, Groq, OpenRouter, DeepSeek, Together,
    xAI, Ollama, Mistral, Fireworks, Perplexity, LMStudio, vLLM, Cerebras,
    SambaNova, Lepton, Anyscale, OVHCloud, Cloudflare Workers AI,
    NVIDIA NIM, ANY OpenAI-compatible endpoint
  - AzureOpenAIAdapter: Azure OpenAI (different URL scheme + api-key header)
  - AnthropicAdapter: Anthropic /messages format
  - GeminiAdapter: Google AI Studio / Vertex generateContent format
  - CohereAdapter: Cohere /v2/chat format
  - BedrockAdapter: AWS Bedrock (requires boto3, optional)

Design principle: ANY unknown provider_type that has an api_base is routed
to OpenAICompatAdapter as default — the OpenAI chat/completions format is
the de-facto standard and ~90% of providers support it. The admin only
needs to set provider_type + model_name + api_key + api_base in the panel.

No hardcoded provider list. No enum restriction. New providers work without
touching code as long as they speak OpenAI-compat (most do).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.models.llm_provider import LLMProvider

log = structlog.get_logger()

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _http_client


class CircuitBreaker:
    """Per-provider circuit breaker: 5 failures in 60s → open for 30s."""

    def __init__(self, failure_threshold: int = 5, window: int = 60, cooldown: int = 30):
        self._failure_threshold = failure_threshold
        self._window = window
        self._cooldown = cooldown
        self._failures: dict[str, list[float]] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, provider_id: str) -> bool:
        if provider_id in self._open_until:
            if time.monotonic() < self._open_until[provider_id]:
                return True
            del self._open_until[provider_id]
            self._failures.pop(provider_id, None)
        return False

    def record_failure(self, provider_id: str) -> None:
        now = time.monotonic()
        fails = self._failures.setdefault(provider_id, [])
        fails.append(now)
        cutoff = now - self._window
        self._failures[provider_id] = [t for t in fails if t > cutoff]
        if len(self._failures[provider_id]) >= self._failure_threshold:
            self._open_until[provider_id] = now + self._cooldown
            log.warning("circuit_breaker.open", provider_id=provider_id)

    def record_success(self, provider_id: str) -> None:
        self._failures.pop(provider_id, None)
        self._open_until.pop(provider_id, None)


_breaker = CircuitBreaker()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False


# The admin can ALWAYS override these via api_base in the panel.
# These are just convenience defaults so the admin only needs an API key.

def _openai_compat_bases() -> dict[str, str]:
    from app.core.config import get_settings
    s = get_settings()
    return {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "together": "https://api.together.xyz/v1",
        "xai": "https://api.x.ai/v1",
        "mistral": "https://api.mistral.ai/v1",
        "fireworks": "https://api.fireworks.ai/inference/v1",
        "perplexity": "https://api.perplexity.ai",
        "ollama": s.LLM_OLLAMA_BASE,
        "lmstudio": s.LLM_LMSTUDIO_BASE,
        "vllm": s.LLM_VLLM_BASE,
        "cerebras": "https://api.cerebras.ai/v1",
        "sambanova": "https://api.sambanova.ai/v1",
        "lepton": "https://api.lepton.ai/v1",
        "anyscale": "https://api.endpoints.anyscale.com/v1",
        "ovhcloud": "https://llama-3-1-70b-instruct.endpoints.kepler.ai.cloud.ovh.net/api/openai_compat/v1",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "cloudflare": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "hyperbolic": "https://api.hyperbolic.xyz/v1",
        "nebius": "https://api.studio.nebius.ai/v1",
        "infomaniak": "https://api.ai.infomaniak.com/v1",
        "scaleway": "https://api.scaleway.ai/v1",
    }

_ANTHROPIC_BASE = "https://api.anthropic.com"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_COHERE_BASE = "https://api.cohere.com/v2"          # chat endpoint
_COHERE_MODELS_BASE = "https://api.cohere.com/v1"   # models list endpoint (v1 only)


class LLMAdapter(ABC):
    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        self.model_name = model_name
        self.api_key = api_key
        self.api_base = api_base

    @abstractmethod
    async def stream_chat(
        self, messages: list[dict], temperature: float, max_tokens: int
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def complete(
        self, messages: list[dict], temperature: float, max_tokens: int,
        response_format: dict | None = None,
    ) -> str: ...

# This is the DEFAULT adapter. Any provider not explicitly matched by the
# factory falls here. Works with ~90% of LLM APIs on the market.

# This is the DEFAULT adapter. Any provider not explicitly matched by the
# factory falls here. Works with ~90% of LLM APIs on the market.

    async def test_connection(self) -> dict:
        t0 = time.monotonic()
        try:
            await self.complete(
                [{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=5,
            )
            latency = int((time.monotonic() - t0) * 1000)
            return {"success": True, "latency_ms": latency, "error": None}
        except Exception as exc:
            return {"success": False, "latency_ms": None, "error": str(exc)}


class OpenAICompatAdapter(LLMAdapter):
    """Universal OpenAI-compatible adapter.

    Covers: OpenAI, Groq, OpenRouter, DeepSeek, Together, xAI, Ollama,
    Mistral, Fireworks, Perplexity, LMStudio, vLLM, Cerebras, SambaNova,
    NVIDIA NIM, Cloudflare Workers AI, Lepton, Anyscale, OVHCloud,
    Scaleway, Nebius, Infomaniak, and ANY endpoint that implements
    POST /chat/completions with the OpenAI request/response schema.

    If the admin provides an api_base, it is used as-is — the adapter
    appends /chat/completions to it.
    """

    def __init__(self, provider_type: str, model_name: str, api_key: str | None, api_base: str | None):
        base = api_base or _openai_compat_bases().get(provider_type)
        if not base:
            raise ValueError(
                f"URL base desconocida para el proveedor '{provider_type}'. "
                "Configura la URL base en Configuración → Proveedores LLM."
            )
        super().__init__(model_name, api_key, base.rstrip("/"))

    def _headers(self) -> dict:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _chat_url(self) -> str:
        base = self.api_base
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        client = _get_http_client()
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with client.stream(
            "POST", self._chat_url(), headers=self._headers(),
            json=payload, timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        client = _get_http_client()
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        resp = await client.post(
            self._chat_url(), headers=self._headers(),
            json=payload, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""


class AzureOpenAIAdapter(LLMAdapter):

    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        super().__init__(model_name, api_key, (api_base or "").rstrip("/"))

    def _headers(self) -> dict:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["api-key"] = self.api_key
        return h

    def _chat_url(self) -> str:
        base = self.api_base
        if "/chat/completions" in base:
            return base
        api_version = "2026-04-21"
        return f"{base}/openai/deployments/{self.model_name}/chat/completions?api-version={api_version}"

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        client = _get_http_client()
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with client.stream(
            "POST", self._chat_url(), headers=self._headers(),
            json=payload, timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        client = _get_http_client()
        payload: dict = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        resp = await client.post(
            self._chat_url(), headers=self._headers(),
            json=payload, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""



class AnthropicAdapter(LLMAdapter):

    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        super().__init__(model_name, api_key, (api_base or _ANTHROPIC_BASE).rstrip("/"))

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }

    def _split_system(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system = None
        conv: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                conv.append({"role": m["role"], "content": m["content"]})
        if not conv:
            conv = [{"role": "user", "content": "ping"}]
        return system, conv

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        client = _get_http_client()
        system, conv = self._split_system(messages)
        payload: dict = {
            "model": self.model_name,
            "messages": conv,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system:
            payload["system"] = system
        async with client.stream(
            "POST", f"{self.api_base}/v1/messages",
            headers=self._headers(), json=payload, timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        text = event.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    continue

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        client = _get_http_client()
        system, conv = self._split_system(messages)
        payload: dict = {
            "model": self.model_name,
            "messages": conv,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system
        resp = await client.post(
            f"{self.api_base}/v1/messages",
            headers=self._headers(), json=payload, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")



class GeminiAdapter(LLMAdapter):

    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        super().__init__(model_name, api_key, (api_base or _GEMINI_BASE).rstrip("/"))

    def _headers(self) -> dict:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-goog-api-key"] = self.api_key
        return h

    def _to_gemini_contents(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system = None
        contents: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "ping"}]}]
        return system, contents

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        client = _get_http_client()
        system, contents = self._to_gemini_contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}
        url = f"{self.api_base}/models/{self.model_name}:streamGenerateContent?alt=sse"
        async with client.stream(
            "POST", url, headers=self._headers(), json=payload, timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                    for candidate in chunk.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            text = part.get("text", "")
                            if text:
                                yield text
                except (json.JSONDecodeError, KeyError):
                    continue

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        client = _get_http_client()
        system, contents = self._to_gemini_contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}
        if response_format and response_format.get("type") == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = f"{self.api_base}/models/{self.model_name}:generateContent"
        resp = await client.post(
            url, headers=self._headers(), json=payload, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


# Cohere v2 /chat has its own request/response format.


class CohereAdapter(LLMAdapter):

    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        super().__init__(model_name, api_key, (api_base or _COHERE_BASE).rstrip("/"))

    def _headers(self, streaming: bool = False) -> dict:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if streaming:
            h["Accept"] = "text/event-stream"
        else:
            h["Accept"] = "application/json"
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _to_cohere_messages(self, messages: list[dict]) -> list[dict]:
        cohere_msgs: list[dict] = []
        for m in messages:
            role = m["role"]
            if role not in ("system", "user", "assistant"):
                role = "user"
            cohere_msgs.append({"role": role, "content": m["content"]})
        if not cohere_msgs:
            cohere_msgs = [{"role": "user", "content": "ping"}]
        return cohere_msgs

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        client = _get_http_client()
        cohere_msgs = self._to_cohere_messages(messages)
        payload: dict = {
            "model": self.model_name,
            "messages": cohere_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with client.stream(
            "POST", f"{self.api_base}/chat",
            headers=self._headers(streaming=True), json=payload, timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content-delta":
                        text = (
                            event.get("delta", {})
                            .get("message", {})
                            .get("content", {})
                            .get("text", "")
                        )
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    continue

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30, jitter=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        client = _get_http_client()
        cohere_msgs = self._to_cohere_messages(messages)
        payload: dict = {
            "model": self.model_name,
            "messages": cohere_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format and response_format.get("type") == "json_object":
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post(
            f"{self.api_base}/chat",
            headers=self._headers(), json=payload, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("message", {}).get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


# Requires boto3 (optional). Admin sets provider_type="bedrock",
# model_name = Bedrock model ID (e.g. "anthropic.claude-3-sonnet-20240229-v1:0").
# api_key and api_base are ignored — uses AWS credentials from environment.


class BedrockAdapter(LLMAdapter):

    def __init__(self, model_name: str, api_key: str | None, api_base: str | None):
        super().__init__(model_name, api_key, api_base)
        self._client = None

    def _get_bedrock_client(self):
        if self._client is None:
            import boto3
            region = self.api_base or "us-east-1"
            self._client = boto3.client("bedrock-runtime", region_name=region)
        return self._client

    async def stream_chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024
    ) -> AsyncGenerator[str, None]:
        import asyncio
        loop = asyncio.get_running_loop()

        def _invoke():
            client = self._get_bedrock_client()
            system_parts = []
            conv = []
            for m in messages:
                if m["role"] == "system":
                    system_parts.append({"text": m["content"]})
                else:
                    conv.append({"role": m["role"], "content": [{"text": m["content"]}]})
            if not conv:
                conv = [{"role": "user", "content": [{"text": "ping"}]}]
            kwargs: dict = {
                "modelId": self.model_name,
                "messages": conv,
                "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
            }
            if system_parts:
                kwargs["system"] = system_parts
            resp = client.converse_stream(**kwargs)
            tokens = []
            for event in resp.get("stream", []):
                if "contentBlockDelta" in event:
                    text = event["contentBlockDelta"].get("delta", {}).get("text", "")
                    if text:
                        tokens.append(text)
            return tokens

        tokens = await loop.run_in_executor(None, _invoke)
        for t in tokens:
            yield t

    async def complete(
        self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 256,
        response_format: dict | None = None,
    ) -> str:
        import asyncio
        loop = asyncio.get_running_loop()

        def _invoke():
            client = self._get_bedrock_client()
            system_parts = []
            conv = []
            for m in messages:
                if m["role"] == "system":
                    system_parts.append({"text": m["content"]})
                else:
                    conv.append({"role": m["role"], "content": [{"text": m["content"]}]})
            if not conv:
                conv = [{"role": "user", "content": [{"text": "ping"}]}]
            kwargs: dict = {
                "modelId": self.model_name,
                "messages": conv,
                "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
            }
            if system_parts:
                kwargs["system"] = system_parts
            resp = client.converse(**kwargs)
            blocks = resp.get("output", {}).get("message", {}).get("content", [])
            return "".join(b.get("text", "") for b in blocks)

        return await loop.run_in_executor(None, _invoke)


_ADAPTER_MAP: dict[str, type] = {
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "google": GeminiAdapter,
    "cohere": CohereAdapter,
    "azure": AzureOpenAIAdapter,
    "azure_openai": AzureOpenAIAdapter,
    "bedrock": BedrockAdapter,
    "aws_bedrock": BedrockAdapter,
}


def _get_adapter(
    provider_name: str,
    provider_type: str,
    model_name: str,
    api_base: str | None,
    api_key: str | None,
) -> LLMAdapter:
    pt = provider_type.lower().strip()

    adapter_cls = _ADAPTER_MAP.get(pt)
    if adapter_cls:
        if adapter_cls in (AnthropicAdapter, GeminiAdapter, CohereAdapter,
                           AzureOpenAIAdapter, BedrockAdapter):
            if not api_key:
                raise RuntimeError(
                    f"El proveedor '{provider_name}' ({pt}) requiere una API key configurada."
                )
            log.debug("llm.adapter_selected", provider_type=pt, adapter=adapter_cls.__name__)
            return adapter_cls(model_name, api_key, api_base)

    log.debug("llm.adapter_selected", provider_type=pt, adapter="OpenAICompatAdapter")
    return OpenAICompatAdapter(pt, model_name, api_key, api_base)


_SYSTEM_TEMPLATE = (
    "Eres el asistente virtual de la Universidad de Sonsonate. "
    "Tu única fuente de información es el CONTEXTO que se te proporciona a continuación.\n\n"
    "Reglas estrictas — sin excepciones:\n"
    "- PROHIBIDO usar conocimiento propio o preentrenado. Si la respuesta no está "
    "literalmente en el contexto, NO la des aunque la conozcas.\n"
    "- Responde solo lo que el usuario preguntó. Ignora la información del contexto "
    "que no sea relevante para la pregunta.\n"
    "- Usa solo datos que aparezcan en el contexto: URLs, teléfonos, fechas, nombres, "
    "pasos, requisitos. No los completes, estimes ni supongas.\n"
    "- Si la información pedida no está en el contexto, responde: "
    "'No tengo esa información en mis documentos.' y sugiere a quién contactar "
    "(coordinador, secretaría, etc.) si aplica.\n"
    "- Sé directo y conciso. No repitas la misma idea como título y como detalle.\n"
    "- Para pasos o listas, usa viñetas simples sin encabezados redundantes.\n"
    "- Responde en español y tutea al usuario.\n"
    "- Nunca hagas referencia a secciones, tablas, anexos, páginas u otras partes del documento fuente. "
    "Da la información directamente sin remitir al usuario a consultar el documento.\n"
    "- Si el contexto contiene frases como \"ver tabla/lista/anexo al final del documento\", IGNÓRALAS "
    "por completo: nunca las repitas. Usa en su lugar cualquier dato concreto (nombre, cargo, teléfono, "
    "correo, oficina) que sí aparezca en el contexto. Si no hay ningún dato concreto disponible, di que "
    "no tienes ese contacto específico y sugiere contactar a Secretaría o Coordinación Académica.\n"
    "- Si el contexto incluye una URL que termina en .png, .jpg, .jpeg, .gif o .webp, "
    "muéstrala como imagen usando sintaxis Markdown ![descripción](URL) en vez de solo pegar el enlace: "
    "esto sí cuenta como dar la información directamente, no como remitir al documento.\n"
    "- Si el contexto incluye una URL que termina en .pdf, preséntala como enlace Markdown "
    "[nombre descriptivo del documento](URL), por ejemplo [Ver tabla de aranceles (PDF)](URL).\n\n"
    "CONTEXTO:\n{context}"
)


async def stream_chat(
    question: str,
    context_chunks: list[dict],
    chain: list[tuple[LLMProvider, str | None]],
    system_prompt: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    if not chain:
        raise RuntimeError("No hay proveedores LLM activos en la cadena.")

    context_text = "\n\n---\n\n".join(c["text"] for c in context_chunks) if context_chunks else "[SIN DOCUMENTOS RELEVANTES — no hay información disponible para responder esta pregunta]"
    prompt = (system_prompt or _SYSTEM_TEMPLATE).replace("{context}", context_text)

    messages: list[dict] = [{"role": "system", "content": prompt}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    plain_chain = [
        (str(provider.id), provider.name, provider.model_name, provider.provider_type,
         provider.api_base, api_key)
        for provider, api_key in chain
    ]

    last_error: Exception | None = None
    for pid, provider_name, model_name, provider_type, api_base, api_key in plain_chain:
        if _breaker.is_open(pid):
            log.info("llm.circuit_open_skip", provider=provider_name)
            continue
        adapter = _get_adapter(provider_name, provider_type, model_name, api_base, api_key)
        log.info("llm.request", provider=provider_name, model=model_name,
                 adapter=type(adapter).__name__)
        tokens_yielded = 0
        try:
            async for token in adapter.stream_chat(messages, temperature, max_tokens):
                tokens_yielded += 1
                yield token
            _breaker.record_success(pid)
            return
        except Exception as exc:
            _breaker.record_failure(pid)
            last_error = exc
            log.warning("llm.provider_failed", provider=provider_name, error=str(exc),
                        tokens_yielded=tokens_yielded)
            if tokens_yielded > 0:
                raise RuntimeError(
                    "La respuesta del servicio de IA se interrumpió. Intenta de nuevo."
                ) from exc
            continue

    log.error("llm.all_providers_failed", error=str(last_error))
    raise RuntimeError("El servicio de IA no está disponible en este momento. Intenta de nuevo en unos minutos.")


async def fetch_models(
    provider_type: str,
    api_key: str | None = None,
    api_base: str | None = None,
) -> list[dict]:
    """Devuelve los modelos disponibles del proveedor consultando su API.

    Retorna lista de {"id": str, "name": str} ordenada por id.
    Lanza ValueError con mensaje legible si el proveedor no responde.
    """
    client = _get_http_client()
    headers: dict[str, str] = {}

    try:
        if provider_type == "anthropic":
            base = (api_base or _ANTHROPIC_BASE).rstrip("/")
            url = f"{base}/v1/models"
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            r = await client.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            items = r.json().get("data", [])
            models = [{"id": m["id"], "name": m.get("display_name", m["id"])} for m in items]

        elif provider_type == "gemini":
            base = (api_base or _GEMINI_BASE).rstrip("/")
            url = f"{base}/models"
            params: dict = {}
            if api_key:
                params["key"] = api_key
            r = await client.get(url, params=params, timeout=15)
            r.raise_for_status()
            items = r.json().get("models", [])
            models = []
            for m in items:
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                mid = m["name"].removeprefix("models/")
                models.append({"id": mid, "name": m.get("displayName", mid)})

        elif provider_type == "cohere":
            base = (api_base or _COHERE_MODELS_BASE).rstrip("/")
            url = f"{base}/models"
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = await client.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            items = r.json().get("models", [])
            models = [{"id": m.get("name", ""), "name": m.get("name", "")} for m in items if m.get("name")]

        else:
            # OpenAI-compat: openai, groq, openrouter, deepseek, mistral, together, ollama…
            base = api_base or _openai_compat_bases().get(provider_type)
            if not base:
                raise ValueError(
                    f"URL base desconocida para '{provider_type}'. "
                    "Configura 'URL base' en el proveedor."
                )
            url = f"{base.rstrip('/')}/models"
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = await client.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            raw = r.json().get("data", [])

            # Para OpenAI filtramos solo modelos de chat/razonamiento
            if provider_type == "openai":
                _CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt")
                _EXCLUDE = ("audio", "realtime", "embedding", "whisper", "dall", "tts", "moderation")
                raw = [
                    m for m in raw
                    if any(m.get("id", "").startswith(p) for p in _CHAT_PREFIXES)
                    and not any(x in m.get("id", "") for x in _EXCLUDE)
                ]

            models = [{"id": m.get("id", ""), "name": m.get("id", "")} for m in raw if m.get("id")]

    except ValueError:
        raise
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"El proveedor respondió con error {exc.response.status_code}. "
            "Verifica que la API key sea válida."
        ) from exc
    except Exception as exc:
        raise ValueError(f"No se pudo conectar al proveedor: {exc}") from exc

    return sorted(models, key=lambda m: m["id"])


async def test_connection(
    provider_type: str,
    model_name: str,
    api_key: str | None = None,
    api_base: str | None = None,
) -> dict:
    try:
        adapter = _get_adapter("test", provider_type, model_name, api_base, api_key)
    except Exception as exc:
        log.info("llm.test", provider_type=provider_type, model=model_name, success=False)
        return {"success": False, "latency_ms": None, "error": str(exc)}
    result = await adapter.test_connection()
    log.info("llm.test", provider_type=provider_type, model=model_name,
             adapter=type(adapter).__name__, success=result["success"])
    return result


async def grade_documents(
    question: str,
    documents: list[dict],
    provider: LLMProvider,
    api_key: str | None,
) -> list[bool]:
    if not documents:
        return []

    doc_list = "\n".join(f"[{i}] {d['text'][:1000]}" for i, d in enumerate(documents))
    prompt = (
        "Eres un evaluador de relevancia estricto. Para cada documento numerado, indica true SOLO si "
        "el documento contiene información que responde DIRECTAMENTE la pregunta. "
        "Indica false si el documento es irrelevante o solo está relacionado temáticamente pero "
        "no aporta la respuesta específica que se pide. "
        "Ante la duda, marca false. "
        'Responde SOLO con JSON: {"grades": [true, false, ...]}'
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Pregunta: {question}\n\nDocumentos:\n{doc_list}"},
    ]
    adapter = _get_adapter(provider.name, provider.provider_type, provider.model_name, provider.api_base, api_key)
    try:
        text = await adapter.complete(
            messages, temperature=0.0, max_tokens=256,
            response_format={"type": "json_object"},
        )
        data = json.loads(text)
        grades = data.get("grades", [])
        while len(grades) < len(documents):
            grades.append(True)
        return [bool(g) for g in grades[:len(documents)]]
    except Exception as exc:
        log.warning("llm.grade_failed", error=str(exc))
        return [True] * len(documents)


async def rewrite_query(
    question: str,
    provider: LLMProvider,
    api_key: str | None,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Convierte la pregunta en términos de búsqueda concretos para una base de conocimiento universitaria "
                "(trámites, procesos, requisitos, fechas, documentos, normativas). "
                "Extrae sustantivos y términos clave. "
                "Responde con UNA SOLA LÍNEA de texto plano. "
                "Sin viñetas, sin numeración, sin explicaciones, sin formato."
            ),
        },
        {"role": "user", "content": question},
    ]
    adapter = _get_adapter(provider.name, provider.provider_type, provider.model_name, provider.api_base, api_key)
    try:
        raw = (await adapter.complete(messages, temperature=0.0, max_tokens=128)).strip()
        rewritten = _clean_rewrite(raw) or question
        log.info("llm.rewrite", original=question[:80], rewritten=rewritten[:80])
        return rewritten
    except Exception as exc:
        log.warning("llm.rewrite_failed", error=str(exc))
        return question


def _clean_rewrite(text: str) -> str:
    """Normalize LLM rewrite output to a single plain-text search query."""
    import re as _re
    lines = []
    for line in text.splitlines():
        line = _re.sub(r"^[\s\-\*\•\d\.\)]+", "", line).strip()
        if line:
            lines.append(line)
    if not lines:
        return text.strip()
    return lines[0]
