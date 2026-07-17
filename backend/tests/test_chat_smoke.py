"""Smoke tests del pipeline de chat — antes sin cobertura (C-5).

No prueban el LLM real: mockean las fases del pipeline (proveedores,
recuperación de contexto, generación) para verificar la ORQUESTACIÓN del
endpoint de chat: rutas greeting/factual, guardrails de entrada, caso sin
proveedores, y la protección del endpoint público vía widget key (C-4).

El endpoint responde con un único JSON completo (sin streaming): el
cliente muestra un indicador de "escribiendo..." mientras espera.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.services.chat import pipeline
from app.api.v1.chat import router as chat_router


def _fake_cfg():
    """Config mínima del chatbot que el pipeline espera (atributos accedidos)."""
    return SimpleNamespace(
        use_corrective_rag=False,
        system_prompt="Eres un asistente.",
        temperature=0.2,
        max_tokens=512,
        no_providers_message="No hay proveedores configurados.",
        guardrail_blocked_message="Mensaje bloqueado.",
    )


def _fake_provider():
    return SimpleNamespace(name="TestProvider", model_name="test-model")


@pytest.fixture
def mock_pipeline(monkeypatch):
    """Mockea las fases comunes del pipeline para aislar la orquestación."""
    provider = _fake_provider()

    async def _load_chat_config(db, use_draft):
        return _fake_cfg()

    async def _load_provider_chain(db, use_draft):
        return [(provider, "fake-key")]

    async def _run_input_guardrails(db, question, client_ip, cfg):
        return None, question  # passes

    async def _check_limits(db, client_ip, session_id, settings):
        return None  # no limit

    async def _lookup_cache(*a, **k):
        return None  # cache miss

    async def _resolve_source_ids(db, source_ids, use_all):
        return None  # None = sin filtro de fuentes (no early-return)

    async def _persist_turn(*a, **k):
        return (str(uuid.uuid4()), str(uuid.uuid4()), False)

    async def _store_cache(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "load_chat_config", _load_chat_config)
    monkeypatch.setattr(pipeline, "load_provider_chain", _load_provider_chain)
    monkeypatch.setattr(pipeline, "run_input_guardrails", _run_input_guardrails)
    monkeypatch.setattr(pipeline, "check_limits", _check_limits)
    monkeypatch.setattr(pipeline, "lookup_cache", _lookup_cache)
    monkeypatch.setattr(pipeline, "resolve_source_ids", _resolve_source_ids)
    monkeypatch.setattr(pipeline, "persist_turn", _persist_turn)
    monkeypatch.setattr(pipeline, "store_cache", _store_cache)
    return provider


async def _post_playground_chat(client, body, headers) -> dict:
    """Llama al endpoint de chat en modo playground autenticado y devuelve el JSON."""
    resp = await client.post(
        "/api/v1/chat", json={**body, "browser": "playground"}, headers=headers
    )
    assert resp.status_code == 200
    return resp.json()


async def test_factual_route_streams_tokens(client, admin_user, auth_headers, mock_pipeline, monkeypatch):
    """Ruta factual: responde con sources + content completo."""
    async def _retrieve_context(*a, **k):
        return [{"text": "Sonsonate es una ciudad.", "source_name": "doc.pdf", "score": 0.9,
                 "parent_text": "Sonsonate es una ciudad de El Salvador."}]

    async def _fake_stream_chat(**kwargs):
        for tok in ["Sonsonate", " es", " una", " ciudad."]:
            yield tok

    monkeypatch.setattr(pipeline, "retrieve_context", _retrieve_context)
    monkeypatch.setattr(chat_router, "stream_chat", _fake_stream_chat)

    body = await _post_playground_chat(
        client, {"question": "¿Qué es Sonsonate?"}, auth_headers(admin_user)
    )
    assert body["type"] == "message"
    assert isinstance(body["sources"], list) and len(body["sources"]) > 0
    assert "Sonsonate" in body["content"]


async def test_greeting_route_returns_message(client, admin_user, auth_headers, mock_pipeline, monkeypatch):
    """Ruta greeting: retrieve_context devuelve un string directo (sin LLM)."""
    async def _retrieve_context(*a, **k):
        return "¡Hola! ¿En qué puedo ayudarte?"

    monkeypatch.setattr(pipeline, "retrieve_context", _retrieve_context)

    body = await _post_playground_chat(client, {"question": "hola"}, auth_headers(admin_user))
    assert body["rag_route"] == "greeting"
    assert "Hola" in body["content"]


async def test_input_guardrail_blocks(client, admin_user, auth_headers, mock_pipeline, monkeypatch):
    """Si los guardrails de entrada rechazan, se responde con type=error y no se llama al LLM."""
    async def _blocking_guardrails(db, question, client_ip, cfg):
        return "Mensaje bloqueado.", question

    monkeypatch.setattr(pipeline, "run_input_guardrails", _blocking_guardrails)

    body = await _post_playground_chat(client, {"question": "algo prohibido"}, auth_headers(admin_user))
    assert body["type"] == "error"
    assert "bloqueado" in body["message"].lower()


async def test_no_providers_returns_message(client, admin_user, auth_headers, mock_pipeline, monkeypatch):
    """Sin proveedores activos, el endpoint devuelve el mensaje configurado."""
    async def _empty_chain(db, use_draft):
        return []

    monkeypatch.setattr(pipeline, "load_provider_chain", _empty_chain)

    body = await _post_playground_chat(client, {"question": "hola"}, auth_headers(admin_user))
    assert body["type"] == "error"
    assert "proveedores" in body["message"].lower()



async def test_public_chat_requires_widget_key(client):
    """Sin JWT de playground ni widget key válida, /api/v1/chat es 403."""
    resp = await client.post("/api/v1/chat", json={"question": "hola"})
    assert resp.status_code == 403


async def test_playground_without_jwt_is_rejected(client):
    """browser=playground sin JWT no degrada a chat libre: exige widget key → 403."""
    resp = await client.post(
        "/api/v1/chat", json={"question": "hola", "browser": "playground"}
    )
    assert resp.status_code == 403


def test_fastapi_version_supports_streaming_yield_dependencies():
    """Compatibilidad de versión — pin mínimo de FastAPI.

    Antes de la 0.118.0, las dependencias con `yield` (como `get_db`) cierran
    su bloque `finally` en cuanto se retorna la respuesta, no cuando termina
    de procesarse (bug documentado por el mantenedor de FastAPI, GitHub
    Discussions #11444). Bajo carga concurrente esto cerraba la sesión de BD
    a medio turno y producía MissingGreenlet. Este test falla explícitamente
    si alguien reintroduce una versión vieja de fastapi en requirements.txt.
    """
    import fastapi

    installed = tuple(int(p) for p in fastapi.__version__.split(".")[:3])
    assert installed >= (0, 118, 0), (
        f"fastapi {fastapi.__version__} < 0.118.0: reintroduce el bug de cierre "
        "prematuro de dependencias yield (ver "
        "GitHub fastapi/fastapi discussions #11444)."
    )


async def test_concurrent_chats_persist_without_missing_greenlet(
    client, admin_user, auth_headers, monkeypatch, db_session
):
    """Regresión — condición de carrera bajo chats concurrentes.

    Reproduce el escenario real que causó una pérdida silenciosa de
    conversaciones: múltiples chats concurrentes, cada uno con su propia
    sesión de BD (igual que en producción, ver fixture `client`), ejecutando
    persist_turn() de verdad (sin mockear) para ejercitar el commit real y el
    acceso posterior a provider_name/model_name — el punto exacto donde el
    ORM expiraba el objeto proveedor tras el commit y disparaba un lazy-load
    en un momento en que la sesión ya no podía hacer IO async
    (sqlalchemy.exc.MissingGreenlet).
    """
    provider = _fake_provider()

    async def _load_chat_config(db, use_draft):
        return _fake_cfg()

    async def _load_provider_chain(db, use_draft):
        return [(provider, "fake-key")]

    async def _run_input_guardrails(db, question, client_ip, cfg):
        return None, question

    async def _check_limits(db, client_ip, session_id, settings):
        return None

    async def _lookup_cache(*a, **k):
        return None

    async def _resolve_source_ids(db, source_ids, use_all):
        return None

    async def _retrieve_context(*a, **k):
        return [{"text": "Contenido de prueba.", "source_name": "doc.pdf", "score": 0.9,
                 "parent_text": "Contenido de prueba completo."}]

    async def _fake_stream_chat(**kwargs):
        for tok in ["Respuesta", " de", " prueba."]:
            yield tok

    async def _store_cache(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "load_chat_config", _load_chat_config)
    monkeypatch.setattr(pipeline, "load_provider_chain", _load_provider_chain)
    monkeypatch.setattr(pipeline, "run_input_guardrails", _run_input_guardrails)
    monkeypatch.setattr(pipeline, "check_limits", _check_limits)
    monkeypatch.setattr(pipeline, "lookup_cache", _lookup_cache)
    monkeypatch.setattr(pipeline, "resolve_source_ids", _resolve_source_ids)
    monkeypatch.setattr(pipeline, "retrieve_context", _retrieve_context)
    monkeypatch.setattr(pipeline, "store_cache", _store_cache)
    monkeypatch.setattr(chat_router, "stream_chat", _fake_stream_chat)
    # persist_turn() NO se mockea: debe ejecutar el commit real + el acceso
    # real a provider_name/model_name que causó el bug original.

    headers = auth_headers(admin_user)
    session_ids = [f"concurrency-test-{uuid.uuid4().hex[:8]}" for _ in range(5)]

    async def _run(session_id: str) -> dict:
        resp = await client.post(
            "/api/v1/chat",
            json={"question": f"Pregunta {session_id}", "browser": "playground",
                  "session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 200
        return resp.json()

    results = await asyncio.gather(*[_run(sid) for sid in session_ids])

    for sid, body in zip(session_ids, results):
        assert body["type"] != "error", f"{sid}: respuesta de error inesperada: {body}"
        assert body.get("conversation_id"), f"{sid}: falta conversation_id — el turno no se persistió"
        assert body.get("provider_name") == "TestProvider"
        assert body.get("model_name") == "test-model"

    # Cada conversación debe haberse persistido de verdad en BD (no solo en
    # el payload de respuesta), confirmando que el commit real de
    # persist_turn() llegó a completarse en las 5 corrutinas concurrentes.
    from sqlalchemy import select
    from app.models.chat_conversation import ChatConversation

    for sid in session_ids:
        result = await db_session.execute(
            select(ChatConversation).where(ChatConversation.session_id == sid)
        )
        assert result.scalars().first() is not None, f"{sid}: conversación no encontrada en BD"
