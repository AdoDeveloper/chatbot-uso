"""Cobertura de los triggers de escalación no_answer y negative_feedback.

Antes de este fix, pipeline.detect_escalation() mandaba siempre
no_answer_seconds=None y feedback_negative_ratio=None al motor de reglas,
por lo que ninguna regla de esos dos tipos podía dispararse jamás,
sin importar la configuración ni el comportamiento real del chatbot.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import MessageFeedback, MessageRole
from app.models.escalation_rule import EscalationRule
from app.services.chat.pipeline import _feedback_negative_ratio, detect_escalation


async def _make_conversation(db_session) -> ChatConversation:
    conv = ChatConversation(id=uuid.uuid4(), session_id=str(uuid.uuid4()))
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _add_assistant_message(db_session, conv_id, feedback: MessageFeedback | None) -> None:
    msg = ChatMessage(
        id=uuid.uuid4(), conversation_id=conv_id, role=MessageRole.assistant,
        content="respuesta", feedback=feedback,
    )
    db_session.add(msg)
    await db_session.commit()


@pytest.mark.asyncio
async def test_feedback_negative_ratio_none_without_feedback(db_session):
    conv = await _make_conversation(db_session)
    ratio = await _feedback_negative_ratio(db_session, conv.id)
    assert ratio is None


@pytest.mark.asyncio
async def test_feedback_negative_ratio_computed_from_real_messages(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message(db_session, conv.id, MessageFeedback.negative)
    await _add_assistant_message(db_session, conv.id, MessageFeedback.negative)
    await _add_assistant_message(db_session, conv.id, MessageFeedback.positive)

    ratio = await _feedback_negative_ratio(db_session, conv.id)
    assert ratio == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_negative_feedback_rule_triggers_with_real_ratio(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message(db_session, conv.id, MessageFeedback.negative)
    await _add_assistant_message(db_session, conv.id, MessageFeedback.negative)

    rule = EscalationRule(
        id=uuid.uuid4(), name="Feedback negativo", trigger_type="negative_feedback",
        trigger_config={"threshold": 0.5}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="test", history=[], final_text="respuesta",
        context_chunks=[], latency_ms=500,
    )
    assert escalated is True
    assert conv.escalation_pending is True
    assert "Feedback negativo" in conv.escalation_trigger_reason


@pytest.mark.asyncio
async def test_no_answer_rule_triggers_with_real_latency(db_session):
    conv = await _make_conversation(db_session)

    rule = EscalationRule(
        id=uuid.uuid4(), name="Respuesta lenta", trigger_type="no_answer",
        trigger_config={"wait_seconds": 5}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    # latency_ms=8000 → 8s, por encima del umbral de 5s configurado.
    escalated = await detect_escalation(
        db_session, conv, question="test", history=[], final_text="respuesta",
        context_chunks=[], latency_ms=8000,
    )
    assert escalated is True
    assert conv.escalation_pending is True
    assert "Respuesta lenta" in conv.escalation_trigger_reason


@pytest.mark.asyncio
async def test_no_answer_rule_does_not_trigger_when_fast(db_session):
    conv = await _make_conversation(db_session)

    rule = EscalationRule(
        id=uuid.uuid4(), name="Respuesta lenta", trigger_type="no_answer",
        trigger_config={"wait_seconds": 120}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="test", history=[], final_text="respuesta",
        context_chunks=[], latency_ms=500,
    )
    assert escalated is False
    assert conv.escalation_pending is False
