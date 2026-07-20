"""
Corrective RAG — LangGraph state machine: expand → retrieve → grade → optional rewrite.
Greeting/factual shortcuts skip grading/rewriting. Max 1 rewrite to avoid loops.
"""
from __future__ import annotations

from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.models.llm_provider import LLMProvider
from app.services.ingestion import vector_store
from app.services.ai.embedding import embed_texts_async
from app.services.ai.llm_gateway import grade_documents, rewrite_query
from app.services.rag.router import QueryRoute, classify_query, get_greeting_response
from app.services.ai.reranker import rerank_async

log = structlog.get_logger()

MAX_REWRITES = 1


class RagState(TypedDict):
    question: str
    original_question: str
    source_ids: list[str] | None
    top_k: int
    score_threshold: float
    use_reranker: bool
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
    use_reranker = state.get("use_reranker", False)
    candidate_k = top_k * 4 if use_reranker else top_k
    docs = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={"indices": emb["sparse_indices"], "values": emb["sparse_values"]},
        source_ids=state.get("source_ids"),
        top_k=candidate_k,
        score_threshold=state.get("score_threshold", 0.0),
    )

    if use_reranker and docs:
        docs = await rerank_async(state["original_question"], docs, top_k)

    return {"documents": docs}


async def _grade(state: RagState) -> dict:
    docs = state["documents"]
    if not docs:
        return {"relevant_docs": []}

    grades = await grade_documents(
        question=state["original_question"],
        documents=docs,
        provider=state["provider"],
        api_key=state["api_key"],
    )
    relevant = [d for d, g in zip(docs, grades) if g]
    log.info("rag.grade", total=len(docs), relevant=len(relevant))
    return {"relevant_docs": relevant}


async def _rewrite(state: RagState) -> dict:
    new_q = await rewrite_query(
        question=state["original_question"],
        provider=state["provider"],
        api_key=state["api_key"],
    )
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
    """Persist an UnansweredQuestion when no context was found. Best-effort, never raises."""
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
    top_k: int = 5,
    score_threshold: float = 0.0,
    use_reranker: bool = False,
    use_corrective_rag: bool = True,
    conversation_id: str | None = None,
    greeting_response: str | None = None,
) -> list[dict] | str:
    """
    Adaptive RAG entry point. Returns either:
      - list[dict]: context chunks for LLM generation
      - str: direct response (for greetings, no retrieval needed)

    `greeting_response` lets the caller pass the admin-customized greeting from
    ChatbotSettings; falls back to the hardcoded default when not provided.
    """
    route = classify_query(question)
    log.info("rag.route", question=question[:80], route=route)

    if route == QueryRoute.GREETING:
        return get_greeting_response(greeting_response)

    if route == QueryRoute.FACTUAL or not use_corrective_rag:
        docs = await run_simple_rag(
            question=question,
            source_ids=source_ids,
            top_k=top_k,
            score_threshold=score_threshold,
            use_reranker=use_reranker,
        )
        if not docs:
            await _maybe_flag_unanswered(question, conversation_id)
        return docs

    docs = await run_corrective_rag(
        question=question,
        provider=provider,
        api_key=api_key,
        source_ids=source_ids,
        top_k=top_k,
        score_threshold=score_threshold,
        use_reranker=use_reranker,
    )
    if not docs:
        await _maybe_flag_unanswered(question, conversation_id)
    return docs


async def run_corrective_rag(
    question: str,
    provider: LLMProvider,
    api_key: str | None,
    source_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float = 0.0,
    use_reranker: bool = False,
) -> list[dict]:
    initial: RagState = {
        "question": question,
        "original_question": question,
        "source_ids": source_ids,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "use_reranker": use_reranker,
        "documents": [],
        "relevant_docs": [],
        "rewrite_count": 0,
        "provider": provider,
        "api_key": api_key,
    }
    final_state = await _graph.ainvoke(initial)
    context = final_state["relevant_docs"]

    log.info("rag.done", question=question[:80], context_chunks=len(context), reranked=use_reranker)
    return context


async def run_simple_rag(
    question: str,
    source_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float = 0.0,
    use_reranker: bool = False,
) -> list[dict]:
    """Retrieval without corrective grading (no LLM cost)."""
    embeddings = await embed_texts_async([question], prefix="query: ")
    emb = embeddings[0]

    candidate_k = top_k * 4 if use_reranker else top_k
    docs = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={"indices": emb["sparse_indices"], "values": emb["sparse_values"]},
        source_ids=source_ids,
        top_k=candidate_k,
        score_threshold=score_threshold,
    )

    if use_reranker and docs:
        docs = await rerank_async(question, docs, top_k)

    return docs
