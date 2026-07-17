from __future__ import annotations



import asyncio
import json
import time
from typing import AsyncGenerator

import jwt as pyjwt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import PLAYGROUND_BROWSERS
from app.core.deps import get_client_ip
from app.db.session import AsyncSessionLocal, get_db
from app.services.ai.llm_gateway import stream_chat
from app.services.chat import pipeline

log = structlog.get_logger()

router = APIRouter(prefix="/chat", tags=["chat"])

# Limita cuántas conversaciones usan un proveedor LLM (RAG + streaming) al
# mismo tiempo. Las que exceden el límite ESPERAN en cola (asyncio.Semaphore
# encola por diseño: https://docs.python.org/3/library/asyncio-sync.html)
# en vez de recibir un error — el usuario percibe una respuesta más lenta en
# horas pico, nunca un rechazo. El timeout de espera evita que una petición
# quede colgada para siempre si la cola no se libera. Ajustable por .env
# según la cuota real del proveedor contratado (ver docs/DEPLOYMENT.md §0.1).
_llm_semaphore = asyncio.Semaphore(get_settings().LLM_MAX_CONCURRENCY)
_LLM_QUEUE_TIMEOUT = get_settings().LLM_QUEUE_TIMEOUT_SECONDS


class ChatMessage(BaseModel):
    role: str = Field(..., max_length=32)
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    source_ids: list[str] | None = None
    messages: list[ChatMessage] | None = Field(default=None, max_length=20)
    session_id: str | None = Field(default=None, max_length=128)
    device: str | None = Field(default=None, max_length=64)
    browser: str | None = Field(default=None, max_length=64)
    source_scope: str | None = None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_stream(
    request: ChatRequest,
    db: AsyncSession,
    client_ip: str,
    origin_url: str | None = None,
) -> AsyncGenerator[str, None]:
    # PRECONDICIÓN: quien llama a este generador ya adquirió _llm_semaphore
    # (ver chat() más abajo) — la validación de acceso y todo lo que necesita
    # HTTPException real (403, no un evento SSE con 200) debe resolverse
    # ANTES de crear el StreamingResponse, porque una vez que el streaming
    # empieza el código de estado HTTP queda fijo en 200 sin importar qué se
    # yield dentro. Este generador solo libera el semáforo al terminar.
    settings = get_settings()
    t_start = time.monotonic()
    try:
        async for evt in _event_stream_inner(request, db, client_ip, origin_url, settings, t_start):
            yield evt
    finally:
        _llm_semaphore.release()


async def _event_stream_inner(
    request: ChatRequest,
    db: AsyncSession,
    client_ip: str,
    origin_url: str | None,
    settings,
    t_start: float,
) -> AsyncGenerator[str, None]:
    is_playground = (request.browser or "").lower() in PLAYGROUND_BROWSERS
    use_draft = is_playground and (request.source_scope != "production")
    cfg = await pipeline.load_chat_config(db, use_draft)

    if settings.GUARDRAILS_ENABLED:
        guard_error, request.question = await pipeline.run_input_guardrails(
            db, request.question, client_ip, cfg
        )
        if guard_error:
            yield _sse({"type": "error", "message": guard_error})
            yield _sse({"type": "done"})
            return

    limit_error = await pipeline.check_limits(db, client_ip, request.session_id, settings)
    if limit_error:
        yield _sse({"type": "error", "message": limit_error})
        yield _sse({"type": "done"})
        return

    use_cache = not request.messages
    if use_cache:
        cached = await pipeline.lookup_cache(db, request.question, request.source_ids, settings, use_draft)
        if cached:
            yield _sse({"type": "sources", "sources": cached["sources"]})
            yield _sse({"type": "token", "content": cached["content"]})
            yield _sse({"type": "done"})
            return

    chain = await pipeline.load_provider_chain(db, use_draft)
    if not chain:
        yield _sse({"type": "error", "message": cfg.no_providers_message})
        yield _sse({"type": "done"})
        return

    primary_provider, primary_key = chain[0]
    provider_name = primary_provider.name
    model_name = primary_provider.model_name

    use_all_sources = is_playground and (request.source_scope != "production")
    effective_source_ids = await pipeline.resolve_source_ids(
        db, request.source_ids, use_all_sources
    )

    if isinstance(effective_source_ids, list) and len(effective_source_ids) == 0:
        yield _sse({"type": "sources", "sources": []})
        yield _sse({"type": "token", "content": "No tengo información disponible para responder esa pregunta en este momento."})
        yield _sse({"type": "done"})
        return

    history = [m.model_dump() for m in request.messages] if request.messages else []
    rag_question = pipeline.build_rag_question(request.question, history)

    try:
        rag_result = await asyncio.wait_for(
            pipeline.retrieve_context(
                rag_question, primary_provider, primary_key, effective_source_ids, cfg
            ),
            timeout=35.0,
        )
    except asyncio.TimeoutError:
        log.warning("chat.rag_timeout", session_id=request.session_id)
        yield _sse({"type": "error", "message": "La consulta tardó demasiado en procesarse. Por favor, intenta de nuevo."})
        yield _sse({"type": "done"})
        return
    except Exception as exc:
        log.error("chat.rag_failed", session_id=request.session_id, error=str(exc))
        yield _sse({"type": "error", "message": cfg.no_providers_message})
        yield _sse({"type": "done"})
        return

    _detected_route = "greeting" if isinstance(rag_result, str) else ("complex" if cfg.use_corrective_rag else "factual")

    if isinstance(rag_result, str):
        yield _sse({"type": "sources", "sources": []})
        yield _sse({"type": "token", "content": rag_result})
        yield _sse({"type": "done", "rag_route": "greeting", "provider_name": provider_name, "model_name": model_name})
        return

    context_chunks = rag_result

    sources = pipeline.format_sources(context_chunks)
    yield _sse({"type": "sources", "sources": sources})

    llm_chunks = pipeline.context_for_llm(context_chunks)
    llm_chunks, ctx_budget = pipeline.budget_context(
        llm_chunks,
        provider=primary_provider,
        system_prompt=cfg.system_prompt,
        history=history,
        max_output_tokens=min(cfg.max_tokens, settings.MAX_OUTPUT_TOKENS),
    )
    full_content: list[str] = []
    deadline = asyncio.get_running_loop().time() + 70.0

    # La conexión a MySQL no se usa durante el streaming del LLM (10-70s), el
    # tramo más largo del request. Se libera aquí y se abre una sesión nueva
    # y corta al final solo para persist_turn — evita retener una conexión
    # ociosa del pool durante todo ese tiempo bajo alta concurrencia.
    await db.close()

    try:
        async for token in stream_chat(
            question=request.question,
            context_chunks=llm_chunks,
            chain=chain,
            system_prompt=cfg.system_prompt,
            temperature=cfg.temperature,
            max_tokens=min(cfg.max_tokens, settings.MAX_OUTPUT_TOKENS),
            history=history or None,
        ):
            if asyncio.get_running_loop().time() > deadline:
                log.warning("chat.llm_stream_timeout", session_id=request.session_id)
                yield _sse({"type": "token", "content": " [respuesta incompleta por timeout]"})
                yield _sse({"type": "done"})
                return
            full_content.append(token)
            yield _sse({"type": "token", "content": token})
    except RuntimeError as exc:
        log.error("chat.llm_stream_failed", session_id=request.session_id, error=str(exc))
        yield _sse({"type": "error", "message": cfg.no_providers_message})
        yield _sse({"type": "done"})
        return

    final_text = "".join(full_content)
    if settings.GUARDRAILS_ENABLED:
        final_text = pipeline.apply_output_guardrails(final_text)

    latency_ms = int((time.monotonic() - t_start) * 1000)

    # Sesión nueva y corta: la que traía el request se cerró antes del
    # streaming (ver comentario más arriba) para no retener la conexión
    # ociosa durante la espera al LLM.
    async with AsyncSessionLocal() as fresh_db:
        assistant_message_id, conversation_id, escalation_prompt = await pipeline.persist_turn(
            fresh_db,
            session_id=request.session_id or client_ip,
            device=request.device,
            browser=request.browser,
            origin_url=origin_url,
            question=request.question,
            final_text=final_text,
            sources=sources,
            latency_ms=latency_ms,
            is_playground=is_playground,
            history=history,
            context_chunks=context_chunks,
        )

        done_payload: dict = {
            "type": "done",
            "latency_ms": latency_ms,
            "message_id": assistant_message_id,
            "conversation_id": conversation_id,
            "provider_name": provider_name,
            "model_name": model_name,
            "rag_route": _detected_route,
        }
        if ctx_budget["truncated"]:
            done_payload["context_truncated"] = True
        if escalation_prompt:
            done_payload["escalation_prompt"] = True
        yield _sse(done_payload)

        if use_cache and full_content:
            await pipeline.store_cache(
                fresh_db, request.question, request.source_ids, sources, final_text, settings, use_draft
            )


@router.post("")
async def chat(
    request: ChatRequest,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Endpoint SSE streaming del chatbot."""
    is_authenticated_playground = False
    if (request.browser or "").lower() in PLAYGROUND_BROWSERS:
        from app.core.security import decode_token
        auth_header = req.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        payload = None
        if token:
            try:
                payload = decode_token(token)
            except pyjwt.PyJWTError:
                payload = None
        if not payload or payload.get("type") != "access":
            request.browser = None
            request.source_scope = None
        else:
            is_authenticated_playground = True

    client_ip = get_client_ip(req)
    origin_url = req.headers.get("Referer") or req.headers.get("Origin")

    # El semáforo se adquiere aquí, antes de crear el StreamingResponse, para
    # poder devolver un 403 real (HTTPException) si la widget key/dominio no
    # son válidos — una vez que el streaming empieza el código de estado
    # queda fijo en 200 sin importar el contenido del stream (ver
    # _event_stream). Si la validación falla, se libera inmediatamente;
    # si pasa, _event_stream hereda la responsabilidad de liberarlo al
    # terminar el generador (éxito, timeout o error de RAG/LLM).
    try:
        await asyncio.wait_for(_llm_semaphore.acquire(), timeout=_LLM_QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("chat.llm_queue_timeout", session_id=request.session_id)
        raise HTTPException(
            status_code=503,
            detail="El asistente está muy solicitado en este momento. Inténtalo de nuevo en unos segundos.",
        )

    if not is_authenticated_playground:
        from app.core.widget_auth import verify_widget_access
        try:
            await verify_widget_access(req, db)
        except Exception:
            _llm_semaphore.release()
            raise

    return StreamingResponse(
        _event_stream(request, db, client_ip, origin_url=origin_url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
