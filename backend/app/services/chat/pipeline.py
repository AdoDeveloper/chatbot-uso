"""
Fases del pipeline de chat extraídas del router SSE.

Cada función implementa una fase cohesiva (guardrails, límites, caché,
fuentes, RAG, persistencia, escalación) y devuelve datos puros; el router
decide qué eventos SSE emitir con ellos. Este módulo NO debe importar el
router para evitar imports circulares.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import (
    RateLimitExceeded,
    check_chat_limits,
    record_throttle_event,
)
from app.core.redis import get_redis
from app.models.enums import MessageRole, ReviewStatus, SourceStatus
from app.models.escalation_rule import EscalationRule
from app.models.source import Source
from app.models.widget_config import WidgetConfig
from app.services.ai.context_budget import get_context_window, truncate_context_chunks
from app.services.ai.guardrails import (
    check_system_prompt_leak,
    scan_output,
    validate_input,
)
from app.services.ai.semantic_cache import get_cached_response, store_cached_response
from app.models.audit_log import AuditLog
from app.services.chat import history as history_svc
from app.services.escalation.engine import evaluate_rule
from app.services.rag.corrective import run_adaptive_rag
from app.services.system import settings as settings_service

log = structlog.get_logger()

EXACT_CACHE_TTL = 3600


def exact_cache_key(question: str, source_ids: list[str] | None, use_draft: bool = False) -> str:
    """Genera la clave determinista del caché exacto en Redis."""
    q = question.lower().strip()
    sids = json.dumps(sorted(source_ids or []))
    scope = "draft" if use_draft else "prod"
    h = hashlib.sha256(f"{q}|{sids}|{scope}".encode()).hexdigest()
    return f"chat:v1:{h}"


async def load_chat_config(db: AsyncSession, use_draft: bool):
    """Carga la configuración del chatbot (borrador o desplegada) desde la BD."""
    if use_draft:
        return await settings_service.get_settings(db)
    return await settings_service.get_deployed_settings(db)


async def load_provider_chain(db: AsyncSession, use_draft: bool):
    """Carga la cadena de proveedores LLM activa (borrador) o la desplegada."""
    if use_draft:
        return await settings_service.get_active_chain(db)
    return await settings_service.get_deployed_chain(db)


async def run_input_guardrails(
    db: AsyncSession, question: str, client_ip: str, cfg
) -> tuple[str | None, str]:
    """Valida la entrada con guardrails, audita inyecciones y devuelve (error, pregunta saneada)."""
    guard = validate_input(question)
    if guard.passed:
        return None, (guard.sanitized_text or question)

    # Persist injection detection to AuditLog for admin review
    try:
        db.add(AuditLog(
            action="guardrails.injection_detected",
            resource_type="chat",
            ip=client_ip,
            meta_json={
                "reason": guard.reason,
                "pattern": guard.matched_pattern,
                "matched_label": guard.matched_label,
                "matched_category": guard.matched_category,
                "question_preview": question[:120],
            },
        ))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("chat.guardrail_audit_failed", error=str(exc))

    user_message = guard.reason
    if guard.matched_pattern and guard.matched_pattern != "__suspicious_chars__":
        user_message = cfg.guardrail_blocked_message
    return user_message, question


async def check_limits(db: AsyncSession, client_ip: str, session_id: str | None, settings) -> str | None:
    """Aplica rate limiting multidimensional; devuelve el mensaje de error si se excede.

    Los límites por minuto y hora se leen de GlobalSetting.
    """
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    per_min = overrides["rate_limit_chat_per_min"]
    try:
        await check_chat_limits(
            client_ip, {
                "per_min": per_min,
                "per_hour": overrides["rate_limit_chat_per_hour"],
                "per_session_min": getattr(settings, "RATE_LIMIT_CHAT_PER_SESSION_MIN", 20),
            },
            session_id=session_id,
        )
    except RateLimitExceeded as exc:
        # Persistir el evento de throttle para historial — best-effort
        await record_throttle_event(
            dimension="chat", identifier=client_ip, identifier_type="ip",
            limit_value=per_min,
            retry_after_seconds=exc.retry_after,
        )
        return f"Demasiadas peticiones. Espera {exc.retry_after}s e intenta de nuevo."
    return None


async def lookup_cache(
    db: AsyncSession, question: str, source_ids: list[str] | None, settings, use_draft: bool = False
) -> dict | None:
    """Busca la respuesta primero en el caché exacto (Redis GET, O(1)) y luego
    en el caché semántico (embedding + SCAN, costoso)."""
    key = exact_cache_key(question, source_ids, use_draft)
    try:
        exact_cached = await get_redis().get(key)
        if exact_cached:
            data = json.loads(exact_cached)
            log.info("chat.exact_cache_hit", key=key[:16])
            return {"sources": data["sources"], "content": data["content"]}
    except Exception as exc:
        log.warning("chat.exact_cache_read_failed", key=key[:16], error=str(exc))

    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    if overrides["semantic_cache_enabled"]:
        cached = await get_cached_response(
            question, source_ids, use_draft=use_draft,
            threshold=overrides["semantic_cache_threshold"],
        )
        if cached:
            log.info("chat.semantic_cache_hit")
            return {"sources": cached["sources"], "content": cached["content"]}

    return None


async def store_cache(
    db: AsyncSession,
    question: str,
    source_ids: list[str] | None,
    sources: list[dict],
    final_text: str,
    settings,
    use_draft: bool = False,
) -> None:
    """Guarda la respuesta en el caché exacto y semántico (best-effort)."""
    try:
        await get_redis().setex(
            exact_cache_key(question, source_ids, use_draft),
            EXACT_CACHE_TTL,
            json.dumps({"sources": sources, "content": final_text}, ensure_ascii=False),
        )
    except Exception as exc:
        log.warning("chat.exact_cache_write_failed", error=str(exc))

    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    if overrides["semantic_cache_enabled"]:
        try:
            await store_cached_response(
                question, source_ids, sources, final_text,
                ttl=overrides["semantic_cache_ttl"],
                use_draft=use_draft,
            )
        except Exception as exc:
            log.warning("chat.semantic_cache_write_failed", error=str(exc))


async def resolve_source_ids(
    db: AsyncSession, requested_ids: list[str] | None, use_all_sources: bool
) -> list[str] | None:
    """Resuelve los IDs de fuentes efectivos según el alcance (borrador o producción)."""
    query = select(Source.id).where(
        Source.status == SourceStatus.ready,
        Source.deleted_at.is_(None),
    )
    if not use_all_sources:
        query = query.where(Source.review_status == ReviewStatus.aprobada)
    if requested_ids:
        query = query.where(Source.id.in_(requested_ids))

    src_q = await db.execute(query)
    ids = [str(r[0]) for r in src_q.all()]
    if not use_all_sources:
        return ids  # puede ser [] → sin resultados, no sin filtro
    return ids or None


def build_rag_question(question: str, history: list[dict]) -> str:
    """Expande preguntas cortas con el último mensaje del usuario del historial."""
    if len(question.split()) <= 8 and history:
        last_user = next(
            (m["content"] for m in reversed(history) if m["role"] == "user"), None
        )
        if last_user:
            return f"{last_user} {question}"
    return question


async def retrieve_context(
    question: str, provider, api_key: str, source_ids: list[str] | None, cfg
) -> str | list[dict]:
    """Ejecuta Adaptive RAG: devuelve un saludo (str) o los chunks de contexto."""
    return await run_adaptive_rag(
        question=question,
        provider=provider,
        api_key=api_key,
        source_ids=source_ids,
        top_k=cfg.top_k,
        score_threshold=cfg.score_threshold,
        use_reranker=cfg.use_reranker,
        use_corrective_rag=cfg.use_corrective_rag,
        greeting_response=cfg.greeting_response,
    )


def format_sources(context_chunks: list[dict]) -> list[dict]:
    """Formatea los chunks recuperados para el evento SSE `sources`, sin duplicados por fuente."""
    seen: set[str] = set()
    result = []
    for c in context_chunks:
        key = c.get("source_id") or c.get("source_name", "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append({
            "text": c["text"][:300],
            "source_id": c.get("source_id", ""),
            "source_name": c.get("source_name", ""),
            "score": round(c.get("score", 0), 3),
        })
    return result


def context_for_llm(chunks: list[dict]) -> list[dict]:
    """Sustituye el texto hijo por parent_text cuando existe (Parent-Child retrieval)."""
    result = []
    for c in chunks:
        enriched = c.copy()
        if "parent_text" in c and c["parent_text"]:
            enriched["text"] = c["parent_text"]
        result.append(enriched)
    return result


def budget_context(
    chunks: list[dict],
    *,
    provider,
    system_prompt: str = "",
    history: list[dict] | None = None,
    max_output_tokens: int = 0,
) -> tuple[list[dict], dict]:
    """Recorta el contexto recuperado para no exceder la ventana del modelo."""
    context_window = get_context_window(provider)
    return truncate_context_chunks(
        chunks,
        context_window=context_window,
        system_prompt=system_prompt,
        history=history,
        reserve_output_tokens=max_output_tokens,
    )


def apply_output_guardrails(text: str) -> str:
    """Escanea la salida en busca de PII y detecta fugas del system prompt."""
    text = scan_output(text)
    if check_system_prompt_leak(text):
        log.warning("guardrails.system_prompt_leak_detected")
    return text


async def _feedback_negative_ratio(db: AsyncSession, conversation_id) -> float | None:
    """Proporción de mensajes del asistente con feedback negativo sobre el
    total de mensajes con feedback registrado en la conversación. None si
    aún no hay ninguna valoración (evita falsos positivos con 0/0)."""
    from app.models.chat_message import ChatMessage

    from app.models.enums import MessageFeedback, MessageRole
    from sqlalchemy import func as sa_func

    result = await db.execute(
        select(ChatMessage.feedback, sa_func.count())
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.feedback.is_not(None))
        .group_by(ChatMessage.feedback)
    )
    counts = {feedback: count for feedback, count in result.all()}
    total = sum(counts.values())
    if total == 0:
        return None
    negative = counts.get(MessageFeedback.negative, 0)
    return negative / total


async def detect_escalation(
    db: AsyncSession,
    conv,
    *,
    question: str,
    history: list[dict],
    final_text: str,
    context_chunks: list[dict],
    latency_ms: int | None = None,
) -> bool:
    """Evalúa las reglas de escalación activas y marca la conversación si alguna dispara."""
    try:
        wc_result = await db.execute(select(WidgetConfig).limit(1))
        widget_cfg = wc_result.scalar_one_or_none()
        if widget_cfg is not None and not widget_cfg.enable_escalation:
            return False

        rules_result = await db.execute(
            select(EscalationRule).where(EscalationRule.enabled.is_(True))
        )
        active_rules = rules_result.scalars().all()

        if active_rules:
            bot_answers_ctx = [
                m["content"] for m in history if m.get("role") == "assistant"
            ] + [final_text]
            rag_scores_ctx = [c.get("score", 0.0) for c in context_chunks]

            escalation_ctx = {
                "user_message": question,
                "bot_answers": bot_answers_ctx[-5:],
                "rag_scores": rag_scores_ctx[-5:],
                "no_answer_seconds": (latency_ms / 1000) if latency_ms is not None else None,
                "feedback_negative_ratio": await _feedback_negative_ratio(db, conv.id),
            }

            for rule in active_rules:
                matches, detail = evaluate_rule(
                    trigger_type=rule.trigger_type,
                    trigger_config=rule.trigger_config or {},
                    context=escalation_ctx,
                )
                if matches:
                    conv.escalation_pending = True
                    conv.escalation_trigger_reason = f"{rule.name}: {detail}"
                    await db.commit()
                    return True
    except Exception as _esc_exc:
        await db.rollback()
        log.warning("chat.escalation_eval_failed", error=str(_esc_exc))
    return False


async def persist_turn(
    db: AsyncSession,
    *,
    session_id: str,
    device: str | None,
    browser: str | None,
    origin_url: str | None,
    question: str,
    final_text: str,
    sources: list[dict],
    latency_ms: int,
    is_playground: bool,
    history: list[dict],
    context_chunks: list[dict],
) -> tuple[str | None, str | None, bool]:
    """Persiste conversación y mensajes, evalúa escalación; devuelve (msg_id, conv_id, escalar)."""
    assistant_message_id: str | None = None
    conversation_id: str | None = None
    escalation_prompt: bool = False
    try:
        conv = await history_svc.get_or_create_conversation(
            db,
            session_id=session_id,
            device=device,
            browser=browser,
            origin_url=origin_url,
        )
        await history_svc.add_message(
            db, conversation_id=conv.id, role=MessageRole.user, content=question
        )
        assistant_msg = await history_svc.add_message(
            db,
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=final_text,
            sources=sources,
            latency_ms=latency_ms,
        )
        await db.commit()
        assistant_message_id = str(assistant_msg.id)
        conversation_id = str(conv.id)

        if not is_playground and not conv.escalated_at and not conv.escalation_pending:
            try:
                escalation_prompt = await asyncio.wait_for(
                    detect_escalation(
                        db,
                        conv,
                        question=question,
                        history=history,
                        final_text=final_text,
                        context_chunks=context_chunks,
                        latency_ms=latency_ms,
                    ),
                    timeout=3.0,
                )
            except asyncio.TimeoutError:
                log.warning("chat.escalation_eval_timeout")
    except Exception as _hist_exc:
        log.warning("chat.history_save_failed", error=str(_hist_exc))

    return assistant_message_id, conversation_id, escalation_prompt
