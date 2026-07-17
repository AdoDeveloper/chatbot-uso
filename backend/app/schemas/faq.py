from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FAQCreate(BaseModel):
    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=5)
    tags: list[str] = []
    is_active: bool = True


class FAQUpdate(BaseModel):
    question: str | None = Field(None, min_length=5)
    answer: str | None = Field(None, min_length=5)
    tags: list[str] | None = None
    is_active: bool | None = None


class FAQOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    tags: list[str]
    is_active: bool
    source_id: uuid.UUID | None
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
