from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.user import User
from app.schemas.chunk import (
    ChunkEditOut,
    ChunkEditRequest,
    ChunkListOut,
    ChunkOut,
    ChunkTestRequest,
    ChunkTestResponse,
    ChunkTestResult,
)
from app.services.ingestion import vector_store
from app.services.ai.embedding import embed_texts_async
from app.services.ai.reranker import rerank_async
from app.services.knowledge import chunk_editing

router = APIRouter(prefix="/chunks", tags=["chunks"])


@router.get("/source/{source_id}", response_model=ChunkListOut)
async def list_source_chunks(
    source_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    warning: str | None = Query(None, description="Filter to a specific warning (short|long|pii)"),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_perm(P.KNOWLEDGE_READ)),
):
    return await chunk_editing.list_source_chunks(
        db, source_id=source_id, page=page, page_size=page_size, warning=warning,
    )


@router.get("/{point_id}", response_model=ChunkOut)
async def get_chunk(
    point_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_perm(P.KNOWLEDGE_READ)),
):
    """Get a single chunk by Qdrant point ID."""
    return await chunk_editing.get_chunk(db, point_id=point_id)


@router.patch("/{point_id}/content", response_model=ChunkOut)
async def edit_chunk(
    point_id: str,
    body: ChunkEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    """
    Edit a chunk's text. The embedding is regenerated, warnings are recomputed,
    and an audit row is written. The edit applies immediately — chunks are
    editable at any time, in any review state.

    Invalidates the semantic cache of the chunk's environment so stale answers
    referencing the previous text won't be served.
    """
    return await chunk_editing.edit_chunk(
        db, point_id=point_id, new_text=body.text, reason=body.reason, current_user=current_user,
    )


@router.post("/{point_id}/discard", response_model=ChunkOut)
async def discard_chunk(
    point_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    """Mark a chunk as discarded — it will be excluded from retrieval."""
    return await chunk_editing.set_discarded(point_id=point_id, value=True, user=current_user)


@router.post("/{point_id}/restore", response_model=ChunkOut)
async def restore_chunk(
    point_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    """Undo a previous discard — the chunk becomes retrievable again."""
    return await chunk_editing.set_discarded(point_id=point_id, value=False, user=current_user)


@router.get("/{point_id}/history", response_model=list[ChunkEditOut])
async def chunk_history(
    point_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_perm(P.KNOWLEDGE_READ)),
):
    """List edits applied to a chunk, newest first."""
    return await chunk_editing.chunk_history(db, point_id=point_id)


@router.post("/test-query", response_model=ChunkTestResponse)
async def test_query(
    body: ChunkTestRequest,
    _=Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    """
    Hit-test: execute a query against the knowledge base and return
    ranked chunks with scores. Does NOT call LLM — retrieval only.
    """
    start = time.monotonic()

    embeddings = await embed_texts_async([body.query], prefix="query: ")
    emb = embeddings[0]

    results = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={"indices": emb["sparse_indices"], "values": emb["sparse_values"]},
        source_ids=body.source_ids,
        top_k=body.top_k * 4 if body.use_reranker else body.top_k,
        score_threshold=0.0,
    )

    if body.use_reranker and results:
        results = await rerank_async(body.query, results, body.top_k)
    else:
        results = results[: body.top_k]

    elapsed_ms = int((time.monotonic() - start) * 1000)

    chunks = [
        ChunkTestResult(
            text=r.get("text", "")[:500],
            source_name=r.get("source_name", ""),
            score=round(r.get("score", 0), 4),
            chunk_index=r.get("chunk_index", 0),
            section=r.get("section"),
        )
        for r in results
    ]

    return ChunkTestResponse(chunks=chunks, latency_ms=elapsed_ms)
