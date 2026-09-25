"""Corrective RAG - LangGraph state machine: expand → retrieve → grade → optional rewrite."""
from __future__ import annotations

import asyncio
from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.models.llm_provider import LLMProvider
from app.services.ai.embedding import embed_texts_async
from app.services.ai.llm_gateway import grade_documents, rewrite_query
from app.services.ingestion import vector_store
from app.services.rag.router import QueryRoute, classify_query, get_greeting_response

log = structlog.get_logger()

MAX_REWRITES = 1

_MAX_SANE_THRESHOLD = 0.05


def _sane_threshold(configured: float) -> float:
    if configured >= _MAX_SANE_THRESHOLD:
        log.warning(
            "rag.threshold_ignored",
            configured=configured,
            max_sane=_MAX_SANE_THRESHOLD,
            reason="fuera de la escala RRF; se ignora para no vaciar el contexto",
        )
        return 0.0
    return configured


_MIN_DOCS_TRAS_FILTRO = 3
_GRADE_MAX_DOCS = 8


def _completar_con_mejores(docs: list[dict], relevantes: list[dict]) -> list[dict]:
    """Aprobados por el evaluador más los mejores de la búsqueda, en el orden de la búsqueda."""
    if not relevantes:
        return []
    conservar = {id(d) for d in docs[:_MIN_DOCS_TRAS_FILTRO]} | {id(d) for d in relevantes}
    elegidos = [d for d in docs if id(d) in conservar]
    log.info("rag.grade_completado", aprobados=len(relevantes), final=len(elegidos))
    return elegidos


def _sin_respuesta(docs: list[dict], ratio: float | None) -> bool:
    """Una pregunta queda sin responder cuando el evaluador no aprueba nada."""
    return not docs or ratio == 0


class RagState(TypedDict):
    question: str
    original_question: str
    source_ids: list[str] | None
    top_k: int
    score_threshold: float
    documents: list[dict]
    relevant_docs: list[dict]
    # Cuántos aprobó el evaluador antes de completar el contexto.
    approved_count: int
    rewrite_count: int
    provider: LLMProvider
    api_key: str | None


async def _expand(state: RagState) -> dict:
    expanded = await rewrite_query(
        question=state["original_question"],
        provider=state["provider"],
        api_key=state["api_key"],
    )
    log.info("rag.expand", original=state["original_question"][:80], expanded=expanded[:80])
    return {"question": expanded}


async def _retrieve(state: RagState) -> dict:
    question = state["question"]
    log.info("rag.retrieve", question=question[:80], rewrite_count=state["rewrite_count"])

    embeddings = await embed_texts_async([question], prefix="query: ")
    emb = embeddings[0]

    top_k = state["top_k"]
    candidate_k = max(top_k, int(top_k * 5))
    effective_threshold = _sane_threshold(state.get("score_threshold", 0.0))
    docs = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={"indices": emb["sparse_indices"], "values": emb["sparse_values"]},
        source_ids=state.get("source_ids"),
        top_k=candidate_k,
        score_threshold=effective_threshold,
        balance_sources=True,
    )

    src_dist = {}
    for d in docs:
        sid = d.get("source_id", "?")
        src_dist[sid] = src_dist.get(sid, 0) + 1
    log.info("rag.retrieve_result", docs=len(docs), sources=src_dist)

    if docs:
        docs = docs[:top_k]

    return {"documents": docs}


async def _grade(state: RagState) -> dict:
    docs = state["documents"][:_GRADE_MAX_DOCS]
    if not docs:
        return {"relevant_docs": []}

    grades = await grade_documents(
        question=state["question"],
        documents=docs,
        provider=state["provider"],
        api_key=state["api_key"],
    )
    relevant = [d for d, g in zip(docs, grades) if g]
    aprobados = len(relevant)
    log.info("rag.grade", total=len(docs), relevant=aprobados)
    relevant = _completar_con_mejores(docs, relevant)
    return {"relevant_docs": relevant, "approved_count": aprobados}


async def _rewrite(state: RagState) -> dict:
    # Se evita la consulta que acaba de fallar para no repetir la misma reformulación.
    new_q = await rewrite_query(
        question=state["original_question"],
        provider=state["provider"],
        api_key=state["api_key"],
        avoid=state["question"],
    )
    log.info("rag.rewrite", failed=state["question"][:60], retry=new_q[:60])
    return {"question": new_q, "rewrite_count": state["rewrite_count"] + 1}


def _decide_after_grade(state: RagState) -> str:
    if state["relevant_docs"]:
        return "done"
    if state["rewrite_count"] < MAX_REWRITES:
        return "rewrite"
    return "done"


def _build_graph() -> StateGraph:
    g = StateGraph(RagState)
    g.add_node("expand", _expand)
    g.add_node("retrieve", _retrieve)
    g.add_node("grade", _grade)
    g.add_node("rewrite", _rewrite)
    g.set_entry_point("expand")
    g.add_edge("expand", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", _decide_after_grade, {"done": END, "rewrite": "rewrite"})
    g.add_edge("rewrite", "retrieve")
    return g.compile()


_graph = _build_graph()


async def _classify_and_store_topic(
    question_id, question: str, provider: LLMProvider, api_key: str | None,
) -> None:
    """Clasifica el tema en background y lo persiste en una sesión aparte, fuera de la ruta de respuesta al usuario."""
    from app.services.ai.llm_gateway import classify_topic

    existing_topics: list[str] = []
    try:
        from sqlalchemy import select as _select

        from app.db.session import AsyncSessionLocal
        from app.models.unanswered_question import UnansweredQuestion as _UQ
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                _select(_UQ.detected_topic)
                .where(_UQ.detected_topic.is_not(None))
                .distinct()
                .limit(40)
            )
            existing_topics = [t for (t,) in result.all() if t]
    except Exception as exc:
        log.warning("unanswered.existing_topics_fetch_failed", error=str(exc))

    topic = await classify_topic(question, provider, api_key, existing_topics=existing_topics)
    if not topic:
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.unanswered_question import UnansweredQuestion
        async with AsyncSessionLocal() as db:
            row = await db.get(UnansweredQuestion, question_id)
            if row:
                row.detected_topic = topic
                await db.commit()
    except Exception as exc:
        log.warning("unanswered.topic_persist_failed", error=str(exc))


async def _maybe_flag_unanswered(
    question: str,
    conversation_id: str | None = None,
    *,
    provider: LLMProvider | None = None,
    api_key: str | None = None,
) -> None:
    """Persiste una UnansweredQuestion cuando no se encontró contexto. Best-effort, nunca lanza excepción."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.unanswered_question import UnansweredQuestion
        async with AsyncSessionLocal() as db:
            import uuid as _uuid
            row = UnansweredQuestion(
                question=question,
                conversation_id=_uuid.UUID(conversation_id) if conversation_id else None,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        log.info("unanswered.flagged", question=question[:80])
        if provider is not None:
            from app.core.versioning import _background_tasks
            task = asyncio.create_task(
                _classify_and_store_topic(row.id, question, provider, api_key)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    except Exception as exc:
        log.warning("unanswered.flag_failed", error=str(exc))


async def run_adaptive_rag(
    question: str,
    provider: LLMProvider,
    api_key: str | None,
    source_ids: list[str] | None = None,
    top_k: int = 12,
    score_threshold: float = 0.0,
    use_corrective_rag: bool = True,
    conversation_id: str | None = None,
    greeting_response: str | None = None,
    original_question: str | None = None,
) -> tuple[list[dict], float | None] | str:
    """Adaptive RAG entry point."""
    a_registrar = original_question or question
    route = classify_query(question)
    log.info("rag.route", question=question[:80], route=route)

    if route == QueryRoute.GREETING:
        return get_greeting_response(greeting_response)

    if route == QueryRoute.FACTUAL or not use_corrective_rag:
        docs, ratio = await run_simple_rag(
            question=question,
            source_ids=source_ids,
            top_k=top_k,
            score_threshold=score_threshold,
            # Grading de relevancia solo si corrective RAG no está desactivado.
            provider=provider if use_corrective_rag else None,
            api_key=api_key if use_corrective_rag else None,
        )
        if _sin_respuesta(docs, ratio):
            await _maybe_flag_unanswered(a_registrar, conversation_id, provider=provider, api_key=api_key)
        return docs, ratio

    docs, ratio = await run_corrective_rag(
        question=question,
        provider=provider,
        api_key=api_key,
        source_ids=source_ids,
        top_k=top_k,
        score_threshold=score_threshold,
    )
    if _sin_respuesta(docs, ratio):
        await _maybe_flag_unanswered(a_registrar, conversation_id, provider=provider, api_key=api_key)
    return docs, ratio


async def run_corrective_rag(
    question: str,
    provider: LLMProvider,
    api_key: str | None,
    source_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float = 0.0,
) -> tuple[list[dict], float | None]:
    initial: RagState = {
        "question": question,
        "original_question": question,
        "source_ids": source_ids,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "documents": [],
        "relevant_docs": [],
        "rewrite_count": 0,
        "provider": provider,
        "api_key": api_key,
    }
    final_state = await _graph.ainvoke(initial)
    context = final_state["relevant_docs"]
    total_docs = final_state["documents"]
    aprobados = final_state.get("approved_count", len(context))
    ratio = (aprobados / len(total_docs)) if total_docs else None

    log.info("rag.done", question=question[:80], context_chunks=len(context))
    return context, ratio


async def run_simple_rag(
    question: str,
    source_ids: list[str] | None = None,
    top_k: int = 12,
    score_threshold: float = 0.0,
    provider: LLMProvider | None = None,
    api_key: str | None = None,
) -> tuple[list[dict], float | None]:
    """Recuperación sin expansión/reescritura de la consulta (sin costo de LLM para esa parte)."""
    embeddings = await embed_texts_async([question], prefix="query: ")
    emb = embeddings[0]

    candidate_k = max(top_k, int(top_k * 5))
    effective_threshold = _sane_threshold(score_threshold)
    docs = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={"indices": emb["sparse_indices"], "values": emb["sparse_values"]},
        source_ids=source_ids,
        top_k=candidate_k,
        score_threshold=effective_threshold,
        balance_sources=True,
    )

    src_dist = {}
    for d in docs:
        sid = d.get("source_id", "?")
        src_dist[sid] = src_dist.get(sid, 0) + 1
    log.info("rag.simple_retrieval", docs=len(docs), sources=src_dist)

    if docs:
        docs = docs[:top_k]

    total_before_grade = len(docs)
    aprobados = len(docs)
    if docs and provider is not None:
        docs = docs[:_GRADE_MAX_DOCS]
        total_before_grade = len(docs)
        grades = await grade_documents(question, docs, provider, api_key)
        relevantes = [d for d, g in zip(docs, grades) if g]
        aprobados = len(relevantes)
        log.info("rag.simple_grade", relevant=aprobados)
        docs = _completar_con_mejores(docs, relevantes)

    # El ratio mide el juicio del filtro, no lo que se envía tras completar.
    ratio = (aprobados / total_before_grade) if total_before_grade else None
    return docs, ratio
