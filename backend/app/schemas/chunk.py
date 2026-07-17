from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class ChunkOut(BaseModel):
    id: str
    text: str
    source_id: str
    source_name: str
    chunk_index: int
    section: str | None = None
    parent_id: str | None = None
    parent_text: str | None = None
    # Review flags — live in Qdrant payload, populated at ingest
    warnings: list[str] = []
    is_discarded: bool = False
    was_edited: bool = False  # true if there is any row in chunk_edits


class ChunkListOut(BaseModel):
    chunks: list[ChunkOut]
    total: int
    page: int
    page_size: int
    warning_counts: dict[str, int] = {}  # e.g. {"short": 3, "pii": 2}


class ChunkEditRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    reason: str | None = Field(default=None, max_length=500)


class ChunkEditOut(BaseModel):
    id: str
    chunk_point_id: str
    previous_content: str
    new_content: str
    edited_by_name: str | None = None
    reason: str | None = None
    edited_at: datetime


class ChunkTestRequest(BaseModel):
    query: str
    source_ids: list[str] | None = None
    top_k: int = 5
    use_reranker: bool = False


class ChunkTestResult(BaseModel):
    text: str
    source_name: str
    score: float
    chunk_index: int
    section: str | None = None


class ChunkTestResponse(BaseModel):
    chunks: list[ChunkTestResult]
    latency_ms: int
