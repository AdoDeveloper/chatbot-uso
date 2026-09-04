"""
Corrective RAG - LangGraph state machine: expand → retrieve → grade → optional rewrite.
Greeting/factual shortcuts skip grading/rewriting. Max 1 rewrite to avoid loops.
"""
from __future__ import annotations

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

# Scores RRF de este corpus rondan 0.03; por encima de este techo, la escala no aplica.
#
# score_threshold no filtra por relevancia semántica de forma confiable, ni en
# esta escala RRF ni aplicado como coseno puro sobre el prefetch dense (0-1):
# verificado con multilingual-e5-large y gte-large contra el corpus real, una
# pregunta totalmente fuera de dominio obtiene coseno ~0.80-0.85, igual o por
# encima de preguntas relevantes reales - el hueco entre "relevante" e
# "irrelevante" es de centésimas o directamente inexistente. No es un defecto
# de un modelo puntual: con textos cortos en español, la similitud coseno
# entre embeddings de oraciones tiende a ser alta y poco discriminativa en
# general (anisotropía del espacio vectorial). El filtro de relevancia real de
# este pipeline es grade_documents (juicio semántico por LLM), no un umbral
# numérico - ver retrieve_context/_grade más abajo.
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


class RagState(TypedDict):
    question: str
    original_question: str
    source_ids: list[str] | None
    top_k: int
    score_threshold: float
    documents: list[dict]
    relevant_docs: list[dict]
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
    docs = state["documents"]
    if not docs:
        return {"relevant_docs": []}

    grades = await grade_documents(
        question=state["question"],
        documents=docs,
        provider=state["provider"],
        api_key=state["api_key"],
    )
    relevant = [d for d, g in zip(docs, grades) if g]
    log.info("rag.grade", total=len(docs), relevant=len(relevant))
    return {"relevant_docs": relevant}


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


async def _maybe_flag_unanswered(question: str, conversation_id: str | None = None) -> None:
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
        log.info("unanswered.flagged", question=question[:80])
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
) -> tuple[list[dict], float | None] | str:
    """
    Adaptive RAG entry point. Returns either:
      - tuple[list[dict], float | None]: context chunks + context_relevance_ratio
        (fracción de chunks recuperados que el grading marcó como relevantes)
      - str: direct response (for greetings, no retrieval needed)

    `greeting_response` lets the caller pass the admin-customized greeting from
    ChatbotSettings; falls back to the hardcoded default when not provided.
    """
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
        if not docs:
            await _maybe_flag_unanswered(question, conversation_id)
        return docs, ratio

    docs, ratio = await run_corrective_rag(
        question=question,
        provider=provider,
        api_key=api_key,
        source_ids=source_ids,
        top_k=top_k,
        score_threshold=score_threshold,
    )
    if not docs:
        await _maybe_flag_unanswered(question, conversation_id)
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
    ratio = (len(context) / len(total_docs)) if total_docs else None

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
    """Recuperación sin expansión/reescritura de la consulta (sin costo de LLM para esa parte).

    Si se pasa `provider`, aplica el mismo grading de relevancia que
    run_corrective_rag (grade_documents) sobre los resultados - pero sin el
    ciclo de expand/rewrite del grafo CRAG completo, que agrega una llamada
    LLM extra innecesaria para preguntas "factual" ya bien formuladas. Este
    es el filtro que evita pasarle al LLM de generación chunks de score
    bajo-medio como si fueran contexto confiable (ver docstring del módulo
    de evaluación de calidad RAG - sin esto, preguntas fuera del corpus con
    retrieval "ruidoso" podían producir respuestas inventadas con aparente
    confianza, ej. un teléfono inexistente).
    """
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
    if docs and provider is not None:
        grades = await grade_documents(question, docs, provider, api_key)
        docs = [d for d, g in zip(docs, grades) if g]
        log.info("rag.simple_grade", relevant=len(docs))

    ratio = (len(docs) / total_before_grade) if total_before_grade else None
    return docs, ratio
