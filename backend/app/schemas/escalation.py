from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import EscalationTrigger


class EscalationRuleCreate(BaseModel):
    name: str
    description: str = ""
    trigger_type: EscalationTrigger
    trigger_config: dict[str, Any] = {}
    enabled: bool = True


class EscalationRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_config: dict[str, Any] | None = None
    enabled: bool | None = None


class EscalationRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    trigger_type: EscalationTrigger
    trigger_config: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelPingResult(BaseModel):
    ok: bool
    status: int | None = None
    error: str | None = None
    latency_ms: int | None = None
    pinged_at: datetime


class EscalationTestResult(BaseModel):
    success: bool
    message: str


class RuleTestContext(BaseModel):
    """Contexto manual para probar una regla sin disparar canales."""
    user_message: str | None = None
    bot_answers: list[str] = []
    rag_scores: list[float] = []
    no_answer_seconds: int | None = None
    feedback_negative_ratio: float | None = None


class RuleTestRequest(BaseModel):
    rule_id: uuid.UUID | None = None
    # Si no se pasa rule_id, se prueba con trigger_type + trigger_config inline
    trigger_type: EscalationTrigger | None = None
    trigger_config: dict[str, Any] | None = None
    context: RuleTestContext


class RuleTestResult(BaseModel):
    matches: bool
    detail: str
    trigger_type: EscalationTrigger
    payload_preview: dict[str, Any]


class TriggerSchemaOut(BaseModel):
    trigger_type: EscalationTrigger
    fields: dict[str, Any]
