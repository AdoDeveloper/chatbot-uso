from __future__ import annotations



import asyncio
import time

import jwt as pyjwt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
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

# Limita cuántas conversaciones usan un proveedor LLM (RAG + generación) al
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


class ChatResponse(BaseModel):
    """Respuesta completa del chat — sin streaming: el cliente muestra un
    indicador de "escribiendo..." mientras espera esta respuesta única."""
    type: str = "message"  # "message" | "error"
    message: str | None = None  # solo en type == "error"
    sources: list[dict] = []
    content: str = ""
    latency_ms: int | None = None
    message_id: str | None = None
    conversation_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    rag_route: str | None = None
    context_truncated: bool = False
    escalation_prompt: bool = False


async def run_chat(
    request: ChatRequest,
    db: AsyncSession,
    client_ip: str,
    origin_url: str | None = None,
) -> ChatResponse:
    # PRECONDICIÓN: quien llama a esta función ya adquirió _llm_semaphore
    # (ver chat() más abajo) — la validación de acceso y todo lo que necesita
    # HTTPException real (403) debe resolverse ANTES de invocar run_chat.
    # Esta función solo libera el semáforo al terminar.
    settings = get_settings()
    t_start = time.monotonic()
    try:
        return await _run_chat_inner(request, db, client_ip, origin_url, settings, t_start)
    finally:
        _llm_semaphore.release()


async def _run_chat_inner(
    request: ChatRequest,
    db: AsyncSession,
    client_ip: str,
    origin_url: str | None,
    settings,
    t_start: float,
) -> ChatResponse:
    is_playground = (request.browser or "").lower() in PLAYGROUND_BROWSERS
    use_draft = is_playground and (request.source_scope != "production")
    cfg = await pipeline.load_chat_config(db, use_draft)

    if settings.GUARDRAILS_ENABLED:
        guard_error, request.question = await pipeline.run_input_guardrails(
            db, request.question, client_ip, cfg
        )
        if guard_error:
            return ChatResponse(type="error", message=guard_error)

    limit_error = await pipeline.check_limits(db, client_ip, request.session_id, settings)
    if limit_error:
        return ChatResponse(type="error", message=limit_error)

    use_cache = not request.messages
    if use_cache:
        cached = await pipeline.lookup_cache(db, request.question, request.source_ids, settings, use_draft)
        if cached:
            return ChatResponse(sources=cached["sources"], content=cached["content"])

    chain = await pipeline.load_provider_chain(db, use_draft)
    if not chain:
        return ChatResponse(type="error", message=cfg.no_providers_message)

    primary_provider, primary_key = chain[0]
    provider_name = primary_provider.name
    model_name = primary_provider.model_name

    use_all_sources = is_playground and (request.source_scope != "production")
    effective_source_ids = await pipeline.resolve_source_ids(
        db, request.source_ids, use_all_sources
    )

    if isinstance(effective_source_ids, list) and len(effective_source_ids) == 0:
        return ChatResponse(
            sources=[],
            content="No tengo información disponible para responder esa pregunta en este momento.",
        )

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
        return ChatResponse(type="error", message="La consulta tardó demasiado en procesarse. Por favor, intenta de nuevo.")
    except Exception as exc:
        log.error("chat.rag_failed", session_id=request.session_id, error=str(exc))
        return ChatResponse(type="error", message=cfg.no_providers_message)

    _detected_route = "greeting" if isinstance(rag_result, str) else ("complex" if cfg.use_corrective_rag else "factual")

    if isinstance(rag_result, str):
        return ChatResponse(
            sources=[],
            content=rag_result,
            rag_route="greeting",
            provider_name=provider_name,
            model_name=model_name,
        )

    context_chunks = rag_result

    sources = pipeline.format_sources(context_chunks)

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

    # La conexión a MySQL no se usa durante la generación del LLM (10-70s), el
    # tramo más largo del request. Se libera aquí y se abre una sesión nueva
    # y corta al final solo para persist_turn — evita retener una conexión
    # ociosa del pool durante todo ese tiempo bajo alta concurrencia.
    await db.close()

    timed_out = False
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
                full_content.append(" [respuesta incompleta por timeout]")
                timed_out = True
                break
            full_content.append(token)
    except RuntimeError as exc:
        log.error("chat.llm_stream_failed", session_id=request.session_id, error=str(exc))
        return ChatResponse(type="error", message=cfg.no_providers_message)

    final_text = "".join(full_content)
    if not timed_out and settings.GUARDRAILS_ENABLED:
        final_text = pipeline.apply_output_guardrails(final_text)

    latency_ms = int((time.monotonic() - t_start) * 1000)

    # Sesión nueva y corta: la que traía el request se cerró antes de la
    # generación (ver comentario más arriba) para no retener la conexión
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

        if use_cache and full_content and not timed_out:
            await pipeline.store_cache(
                fresh_db, request.question, request.source_ids, sources, final_text, settings, use_draft
            )

        return ChatResponse(
            sources=sources,
            content=final_text,
            latency_ms=latency_ms,
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            provider_name=provider_name,
            model_name=model_name,
            rag_route=_detected_route,
            context_truncated=bool(ctx_budget["truncated"]),
            escalation_prompt=bool(escalation_prompt),
        )


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Endpoint del chatbot. Responde con el mensaje completo (sin streaming);
    el cliente debe mostrar un indicador de "escribiendo..." mientras espera."""
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

    # El semáforo se adquiere aquí, antes de correr el pipeline, para poder
    # devolver un 403 real (HTTPException) si la widget key/dominio no son
    # válidos. Si la validación falla, se libera inmediatamente; si pasa,
    # run_chat hereda la responsabilidad de liberarlo al terminar (éxito,
    # timeout o error de RAG/LLM).
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

    return await run_chat(request, db, client_ip, origin_url=origin_url)
