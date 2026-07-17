from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import ConversationStatus, MessageFeedback, MessageRole


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    sources_json: list[dict[str, Any]]
    latency_ms: int | None
    rag_route: str | None
    feedback: MessageFeedback | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatConversationOut(BaseModel):
    id: uuid.UUID
    session_id: str
    user_id: uuid.UUID | None
    status: ConversationStatus
    device: str | None
    browser: str | None
    origin_url: str | None
    started_at: datetime
    last_message_at: datetime
    escalated_at: datetime | None = None
    assigned_to_user_id: uuid.UUID | None = None
    assigned_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by_user_id: uuid.UUID | None = None
    csat_score: int | None = None
    escalation_trigger_reason: str | None = None
    tags: list[str] = []
    message_count: int = 0
    first_user_message: str | None = None

    model_config = {"from_attributes": True}


class ChatConversationDetail(ChatConversationOut):
    messages: list[ChatMessageOut] = []


class FeedbackUpdate(BaseModel):
    feedback: MessageFeedback
