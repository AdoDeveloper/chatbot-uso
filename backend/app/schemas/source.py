from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ReviewStatus, SourceStatus, SourceType


class SourceResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    type: SourceType
    status: SourceStatus
    review_status: ReviewStatus
    reviewed_at: datetime | None = None
    reviewed_by_name: str | None = None
    rejection_reason: str | None = None
    file_size: int | None
    chunk_count: int
    error_message: str | None
    error_code: str | None = None
    error_hint: str | None = None
    progress_stage: str | None
    meta: dict
    tags: list[str] = []
    created_by_id: uuid.UUID | None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_source(cls, source: object) -> "SourceResponse":
        meta: dict = getattr(source, "meta", {}) or {}
        user = getattr(source, "created_by", None)
        reviewer = getattr(source, "reviewed_by", None)
        return cls(
            id=source.id,  # type: ignore[attr-defined]
            name=source.name,  # type: ignore[attr-defined]
            description=meta.get("description"),
            type=source.type,  # type: ignore[attr-defined]
            status=source.status,  # type: ignore[attr-defined]
            review_status=source.review_status,  # type: ignore[attr-defined]
            reviewed_at=source.reviewed_at,  # type: ignore[attr-defined]
            reviewed_by_name=reviewer.full_name if reviewer else None,
            rejection_reason=source.rejection_reason,  # type: ignore[attr-defined]
            file_size=source.file_size,  # type: ignore[attr-defined]
            chunk_count=source.chunk_count,  # type: ignore[attr-defined]
            error_message=source.error_message,  # type: ignore[attr-defined]
            error_code=getattr(source, "error_code", None),
            error_hint=getattr(source, "error_hint", None),
            progress_stage=source.progress_stage,  # type: ignore[attr-defined]
            meta=meta,
            tags=meta.get("tags", []),
            created_by_id=source.created_by_id,  # type: ignore[attr-defined]
            created_by_name=user.full_name if user else None,
            created_at=source.created_at,  # type: ignore[attr-defined]
            updated_at=source.updated_at,  # type: ignore[attr-defined]
        )


class SourceUpdateMeta(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = None
    meta: dict | None = None
