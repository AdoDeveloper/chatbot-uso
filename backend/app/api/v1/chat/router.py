from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import PANEL_AUTHENTICATED_BROWSERS
from app.core.deps import get_client_ip, resolve_user_from_access_token
from app.core.versioning import _background_tasks
from app.db import session as db_session
from app.db.session import get_db
from app.schemas.settings import NO_CONTEXT_MESSAGE
from app.services.ai.llm_gateway import set_fallback_chain, stream_chat
from app.services.chat import pipeline
from app.services.rag.quality import is_no_answer_reply
from app.services.system.rbac import has_permission

log = structlog.get_logger()

router = APIRouter(prefix="/chat", tags=["chat"])

_llm_semaphore = asyncio.Semaphore(get_settings().LLM_MAX_CONCURRENCY)
_LLM_QUEUE_TIMEOUT = get_settings().LLM_QUEUE_TIMEOUT_SECONDS
_TURN_BUDGET_SECONDS = 40.0
_MIN_LLM_SECONDS = 10.0

class ChatMessage(BaseModel):
    role: str = Field(..., max_length=32)
    content: str = Field(..., max_length=4000)

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    source_ids: list[str] | None = None
    messages: list[ChatMessage] | None = Field(default=None, max_length=20)
    session_id: str | None = Field(default=None, max_length=128)
    browser: str | None = Field(default=None, max_length=64)
    source_scope: str | None = None

class ChatResponse(BaseModel):
    """Respuesta completa del chat."""
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

async def _persist_and_respond(
    request: ChatRequest,
    *,
    client_ip: str,
    origin_url: str | None,
    is_playground: bool,
    final_text: str,
    sources: list[dict],
    latency_ms: int,
    history: list[dict],
    response_kwargs: dict,
    context_relevance_ratio: float | None = None,
) -> ChatResponse:
    """Persiste el turno en una sesión de BD nueva y arma el ChatResponse."""
    async with db_session.AsyncSessionLocal() as fresh_db:
        message_id, conversation_id, escalation_prompt = await pipeline.persist_turn(
            fresh_db,
            session_id=request.session_id or client_ip,
            browser=request.browser,
            origin_url=origin_url,
            question=request.question,
            final_text=final_text,
            sources=sources,
            latency_ms=latency_ms,
            is_playground=is_playground,
            history=history,
            context_relevance_ratio=context_relevance_ratio,
            rag_route=response_kwargs.get("rag_route"),
        )
    return ChatResponse(
        sources=sources,
        content=final_text,
        latency_ms=latency_ms,
        message_id=message_id,
        conversation_id=conversation_id,
        escalation_prompt=bool(escalation_prompt),
        **response_kwargs,
    )


async def run_chat(
    request: ChatRequest,
    db: AsyncSession,
    client_ip: str,
    origin_url: str | None = None,
) -> ChatResponse:
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
    is_playground = (request.browser or "").lower() in PANEL_AUTHENTICATED_BROWSERS
    use_draft = is_playground and (request.source_scope != "production")
    cfg = await pipeline.load_chat_config(db, use_draft)

    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)

    guard_error, request.question = await pipeline.run_input_guardrails(
        db, request.question, client_ip, cfg
    )
    if guard_error:
        return ChatResponse(type="error", message=guard_error)

    limit_error = await pipeline.check_limits(db, client_ip, request.session_id, settings)
    if limit_error:
        return ChatResponse(type="error", message=limit_error)

    if not is_playground:
        human_reply = await pipeline.human_request_reply(db, request.question)
        if human_reply:
            return await _persist_and_respond(
                request,
                client_ip=client_ip,
                origin_url=origin_url,
                is_playground=is_playground,
                final_text=human_reply,
                sources=[],
                latency_ms=int((time.monotonic() - t_start) * 1000),
                history=[],
                response_kwargs={"rag_route": "escalation"},
            )

    use_cache = not request.messages
    if use_cache:
        cached = await pipeline.lookup_cache(db, request.question, request.source_ids, settings, use_draft)
        if cached:
            cache_latency_ms = int((time.monotonic() - t_start) * 1000)
            return await _persist_and_respond(
                request,
                client_ip=client_ip,
                origin_url=origin_url,
                is_playground=is_playground,
                final_text=cached["content"],
                sources=cached["sources"],
                latency_ms=cache_latency_ms,
                history=[],
                response_kwargs={"rag_route": "cache"},
            )

    history = pipeline.sanitize_history(
        [m.model_dump() for m in request.messages] if request.messages else [],
        guardrails_enabled=overrides["guardrails_enabled"],
        max_input_chars=overrides["max_input_chars"],
        pii_entities=overrides["pii_entities"],
    )

    from app.services.ai.semantic_cache import get_cache_generation
    cache_generation_at_start = await get_cache_generation()

    chain = await pipeline.load_provider_chain(db, use_draft)
    if not chain:
        no_chain_latency_ms = int((time.monotonic() - t_start) * 1000)
        return await _persist_and_respond(
            request,
            client_ip=client_ip,
            origin_url=origin_url,
            is_playground=is_playground,
            final_text=cfg.no_providers_message,
            sources=[],
            latency_ms=no_chain_latency_ms,
            history=history,
            response_kwargs={"type": "error", "message": cfg.no_providers_message},
        )

    set_fallback_chain(chain)
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
            content=NO_CONTEXT_MESSAGE,
        )

    rag_question = pipeline.build_rag_question(request.question, history)

    t_rag_start = time.monotonic()
    try:
        rag_result = await asyncio.wait_for(
            pipeline.retrieve_context(
                rag_question, primary_provider, primary_key, effective_source_ids, cfg,
                original_question=request.question,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        log.warning("chat.rag_timeout", session_id=request.session_id)
        return ChatResponse(type="error", message="La consulta tardó demasiado en procesarse. Por favor, inténtelo de nuevo.")
    except Exception as exc:
        log.error("chat.rag_failed", session_id=request.session_id, error=str(exc))
        return ChatResponse(type="error", message=cfg.no_providers_message)
    rag_latency_ms = int((time.monotonic() - t_rag_start) * 1000)

    if isinstance(rag_result, str):
        _detected_route = "greeting"
    else:
        from app.services.rag.router import classify_query
        _detected_route = classify_query(rag_question) if cfg.use_corrective_rag else "factual"

    if isinstance(rag_result, str):
        greeting_latency_ms = int((time.monotonic() - t_start) * 1000)
        return await _persist_and_respond(
            request,
            client_ip=client_ip,
            origin_url=origin_url,
            is_playground=is_playground,
            final_text=rag_result,
            sources=[],
            latency_ms=greeting_latency_ms,
            history=history,
            response_kwargs={
                "rag_route": "greeting",
                "provider_name": provider_name,
                "model_name": model_name,
            },
        )

    context_chunks, context_relevance_ratio = rag_result

    if not context_chunks:
        no_context_latency_ms = int((time.monotonic() - t_start) * 1000)
        return await _persist_and_respond(
            request,
            client_ip=client_ip,
            origin_url=origin_url,
            is_playground=is_playground,
            final_text=NO_CONTEXT_MESSAGE,
            sources=[],
            latency_ms=no_context_latency_ms,
            history=history,
            context_relevance_ratio=context_relevance_ratio,
            response_kwargs={
                "rag_route": _detected_route,
                "provider_name": provider_name,
                "model_name": model_name,
            },
        )

    llm_chunks = pipeline.context_for_llm(context_chunks)
    llm_chunks, ctx_budget = pipeline.budget_context(
        llm_chunks,
        provider=primary_provider,
        system_prompt=cfg.system_prompt,
        history=history,
        max_output_tokens=min(cfg.max_tokens, overrides['max_output_tokens']),
    )

    sources = pipeline.format_sources(llm_chunks)
    full_content: list[str] = []
    budget = max(_MIN_LLM_SECONDS, _TURN_BUDGET_SECONDS - (time.monotonic() - t_start))
    deadline = asyncio.get_running_loop().time() + budget

    await db.close()

    timed_out = False
    t_llm_start = time.monotonic()
    served: dict = {}
    llm_gen = stream_chat(
        question=request.question,
        context_chunks=llm_chunks,
        chain=chain,
        system_prompt=cfg.system_prompt,
        temperature=cfg.temperature,
        max_tokens=min(cfg.max_tokens, overrides['max_output_tokens']),
        history=history or None,
        served=served,
    )
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            try:
                token = await asyncio.wait_for(llm_gen.__anext__(), timeout=max(remaining, 0.01))
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                log.warning("chat.llm_stream_timeout", session_id=request.session_id)
                if full_content:
                    full_content.append(" [respuesta incompleta por timeout]")
                timed_out = True
                break
            full_content.append(token)
    except RuntimeError as exc:
        log.error("chat.llm_stream_failed", session_id=request.session_id, error=str(exc))
        from app.services.monitoring.alerts import notify_provider_down
        provider_names = [p.name for p, _key in chain]
        task = asyncio.create_task(notify_provider_down(str(exc), providers=provider_names))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        fail_latency_ms = int((time.monotonic() - t_start) * 1000)
        return await _persist_and_respond(
            request,
            client_ip=client_ip,
            origin_url=origin_url,
            is_playground=is_playground,
            final_text=cfg.no_providers_message,
            sources=[],
            latency_ms=fail_latency_ms,
            history=history,
            response_kwargs={"type": "error", "message": cfg.no_providers_message},
        )
    finally:
        await llm_gen.aclose()

    provider_name = served.get("provider_name", provider_name)
    model_name = served.get("model_name", model_name)
    final_text = "".join(full_content)
    if not final_text.strip():
        log.warning(
            "chat.empty_response", session_id=request.session_id,
            provider=provider_name, llm_ms=int((time.monotonic() - t_llm_start) * 1000),
        )
        final_text = cfg.no_providers_message
    if not timed_out and overrides["guardrails_enabled"]:
        final_text = pipeline.apply_output_guardrails(
            final_text, pii_entities=overrides["pii_entities"], context_chunks=llm_chunks,
        )

    llm_latency_ms = int((time.monotonic() - t_llm_start) * 1000)
    latency_ms = int((time.monotonic() - t_start) * 1000)
    if latency_ms > 15000:
        log.warning(
            "chat.slow_response", session_id=request.session_id,
            total_ms=latency_ms, rag_ms=rag_latency_ms, llm_ms=llm_latency_ms,
            rag_route=_detected_route, provider=provider_name,
        )

    async with db_session.AsyncSessionLocal() as fresh_db:
        assistant_message_id, conversation_id, escalation_prompt = await pipeline.persist_turn(
            fresh_db,
            session_id=request.session_id or client_ip,
            browser=request.browser,
            origin_url=origin_url,
            question=request.question,
            final_text=final_text,
            sources=sources,
            latency_ms=latency_ms,
            is_playground=is_playground,
            history=history,
            context_relevance_ratio=context_relevance_ratio,
            rag_route=_detected_route,
        )

        if not is_playground and context_relevance_ratio != 0 and is_no_answer_reply(final_text):
            from app.services.rag.corrective import _maybe_flag_unanswered
            task = asyncio.create_task(_maybe_flag_unanswered(
                request.question, conversation_id, provider=primary_provider, api_key=primary_key,
            ))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        if assistant_message_id and not use_draft:
            task = asyncio.create_task(pipeline.evaluate_response_quality(
                assistant_message_id, request.question, final_text, llm_chunks,
                primary_provider, primary_key,
            ))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        if use_cache and full_content and not timed_out and not is_no_answer_reply(final_text):
            await pipeline.store_cache(
                fresh_db, request.question, request.source_ids, sources, final_text, settings, use_draft,
                min_generation=cache_generation_at_start,
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
    """Endpoint del chatbot."""
    is_authenticated_playground = False
    if (request.browser or "").lower() in PANEL_AUTHENTICATED_BROWSERS:
        auth_header = req.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        user = None
        if token:
            try:
                user = await resolve_user_from_access_token(token, db)
            except HTTPException:
                user = None
        if not user or not await has_permission(db, user.role, "bot_settings", "read"):
            request.browser = None
            request.source_scope = None
        else:
            is_authenticated_playground = True

    client_ip = get_client_ip(req)
    origin_url = req.headers.get("Referer") or req.headers.get("Origin")

    try:
        await asyncio.wait_for(_llm_semaphore.acquire(), timeout=_LLM_QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("chat.llm_queue_timeout", session_id=request.session_id)
        raise HTTPException(
            status_code=503,
            detail="El asistente está muy solicitado en este momento. Inténtelo de nuevo en unos segundos.",
        )

    if not is_authenticated_playground:
        from app.core.widget_auth import verify_widget_access
        try:
            await verify_widget_access(req, db)
        except Exception:
            _llm_semaphore.release()
            raise

    return await run_chat(request, db, client_ip, origin_url=origin_url)
