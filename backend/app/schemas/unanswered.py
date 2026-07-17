from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UnansweredStatus


class UnansweredQuestionOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    question: str
    detected_topic: str | None
    status: UnansweredStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class UnansweredGroup(BaseModel):
    topic: str
    count: int
    first_seen: datetime
    last_seen: datetime
    questions: list[UnansweredQuestionOut]


class UnansweredGroupList(BaseModel):
    groups: list[UnansweredGroup]
    total: int


class CreateFAQFromUnanswered(BaseModel):
    answer: str
    tags: list[str] = []
