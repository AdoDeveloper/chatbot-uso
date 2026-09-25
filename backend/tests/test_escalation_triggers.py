"""Cobertura de los triggers de escalación no_answer y negative_feedback."""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import MessageFeedback, MessageRole
from app.models.escalation_rule import EscalationRule
from app.services.chat.pipeline import _feedback_negative_ratio, _recent_assistant_rag_scores, detect_escalation

_next_ts = itertools.count()


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
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_next_ts)),
    )
    db_session.add(msg)
    await db_session.commit()


async def _add_assistant_message_with_score(db_session, conv_id, score: float) -> None:
    msg = ChatMessage(
        id=uuid.uuid4(), conversation_id=conv_id, role=MessageRole.assistant,
        content="respuesta", sources_json=[{"source_id": "s1", "score": score}],
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_next_ts)),
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
        db_session, conv, question="test",
    )
    assert escalated is True
    assert conv.escalation_pending is True
    assert "Feedback negativo" in conv.escalation_trigger_reason


async def _add_assistant_text(db_session, conv_id, content: str) -> None:
    db_session.add(ChatMessage(
        id=uuid.uuid4(), conversation_id=conv_id, role=MessageRole.assistant, content=content,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_next_ts)),
    ))
    await db_session.commit()


async def _no_answer_rule(db_session, consecutive: int = 2) -> None:
    db_session.add(EscalationRule(
        id=uuid.uuid4(), name="Sin respuesta", trigger_type="no_answer",
        trigger_config={"consecutive": consecutive}, enabled=True,
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_no_answer_rule_triggers_after_consecutive_unanswered_replies(db_session):
    conv = await _make_conversation(db_session)
    await _no_answer_rule(db_session)
    await _add_assistant_text(db_session, conv.id, "El trámite cuesta $25.")
    await _add_assistant_text(db_session, conv.id, "No dispongo de esa información.")
    await _add_assistant_text(db_session, conv.id, "No tengo información sobre el horario de la cafetería.")

    escalated = await detect_escalation(db_session, conv, question="¿y el horario?")
    assert escalated is True
    assert "Sin respuesta" in conv.escalation_trigger_reason


@pytest.mark.asyncio
async def test_no_answer_rule_ignores_a_single_or_interrupted_miss(db_session):
    conv = await _make_conversation(db_session)
    await _no_answer_rule(db_session)
    await _add_assistant_text(db_session, conv.id, "No dispongo de esa información.")
    await _add_assistant_text(db_session, conv.id, "El trámite tarda 3 días hábiles.")
    await _add_assistant_text(db_session, conv.id, "No dispongo de esa información.")

    assert await detect_escalation(db_session, conv, question="otra") is False


@pytest.mark.asyncio
async def test_no_answer_rule_ignores_off_topic_refusals(db_session):
    conv = await _make_conversation(db_session)
    await _no_answer_rule(db_session)
    for _ in range(3):
        await _add_assistant_text(db_session, conv.id, "Solo puedo ayudarle con temas de la Universidad de Sonsonate.")

    assert await detect_escalation(db_session, conv, question="receta") is False


@pytest.mark.asyncio
async def test_recent_assistant_rag_scores_reads_real_history_chronologically(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message_with_score(db_session, conv.id, 0.01)
    await _add_assistant_message_with_score(db_session, conv.id, 0.02)
    await _add_assistant_message_with_score(db_session, conv.id, 0.03)

    scores = await _recent_assistant_rag_scores(db_session, conv.id, limit=5)
    assert scores == [0.01, 0.02, 0.03]


@pytest.mark.asyncio
async def test_recent_assistant_rag_scores_respects_limit_keeping_most_recent(db_session):
    conv = await _make_conversation(db_session)
    for score in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]:
        await _add_assistant_message_with_score(db_session, conv.id, score)

    scores = await _recent_assistant_rag_scores(db_session, conv.id, limit=3)
    assert scores == [0.04, 0.05, 0.06]


@pytest.mark.asyncio
async def test_recent_assistant_rag_scores_excludes_turns_without_sources(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message(db_session, conv.id, feedback=None)  # saludo, sin sources_json
    await _add_assistant_message(db_session, conv.id, feedback=None)  # saludo, sin sources_json
    await _add_assistant_message_with_score(db_session, conv.id, 0.9)  # respuesta real, alta confianza

    scores = await _recent_assistant_rag_scores(db_session, conv.id, limit=5)
    assert scores == [0.9]


@pytest.mark.asyncio
async def test_confidence_below_rule_does_not_trigger_on_greetings_without_sources(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message(db_session, conv.id, feedback=None)  # saludo
    await _add_assistant_message(db_session, conv.id, feedback=None)  # saludo

    rule = EscalationRule(
        id=uuid.uuid4(), name="Confianza baja", trigger_type="confidence_below",
        trigger_config={"threshold": 0.02, "consecutive": 2}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="hola",
    )
    assert escalated is False
    assert conv.escalation_pending is False


@pytest.mark.asyncio
async def test_detect_escalation_fails_safe_and_logs_degraded(db_session, monkeypatch):
    from app.services.chat import pipeline as pipeline_mod

    conv = await _make_conversation(db_session)
    rule = EscalationRule(
        id=uuid.uuid4(), name="Regla rota", trigger_type="confidence_below",
        trigger_config={"threshold": 0.02, "consecutive": 2}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    def _boom(*a, **k):
        raise RuntimeError("trigger_config corrupto")

    monkeypatch.setattr(pipeline_mod, "evaluate_rule", _boom)

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        pipeline_mod.log, "warning",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )

    escalated = await detect_escalation(
        db_session, conv, question="test",
    )

    assert escalated is False
    # detect_escalation hace rollback() en el camino de error, lo que expira los atributos in-memory de `conv` - se relee explícitamente.
    await db_session.refresh(conv)
    assert conv.escalation_pending is False
    degraded_calls = [kwargs for event, kwargs in calls if event == "chat.escalation_eval_failed"]
    assert len(degraded_calls) == 1
    assert degraded_calls[0]["degraded"] is True


@pytest.mark.asyncio
async def test_confidence_below_rule_triggers_on_real_consecutive_turns(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message_with_score(db_session, conv.id, 0.01)
    await _add_assistant_message_with_score(db_session, conv.id, 0.015)  # turno "actual"

    rule = EscalationRule(
        id=uuid.uuid4(), name="Confianza baja", trigger_type="confidence_below",
        trigger_config={"threshold": 0.02, "consecutive": 2}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="test",
    )
    assert escalated is True
    assert "Confianza baja" in conv.escalation_trigger_reason


@pytest.mark.asyncio
async def test_confidence_below_rule_does_not_trigger_with_one_good_turn(db_session):
    conv = await _make_conversation(db_session)
    await _add_assistant_message_with_score(db_session, conv.id, 0.01)
    await _add_assistant_message_with_score(db_session, conv.id, 0.03)  # buena, rompe la racha

    rule = EscalationRule(
        id=uuid.uuid4(), name="Confianza baja", trigger_type="confidence_below",
        trigger_config={"threshold": 0.02, "consecutive": 2}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="test",
    )
    assert escalated is False


async def _widget(db_session, enable_escalation: bool):
    from app.models.widget_config import WidgetConfig

    db_session.add(WidgetConfig(
        id=uuid.uuid4(), chatbot_name="Asistente", welcome_message="Hola", primary_color="#2563EB",
        position="right", api_key=f"k-{uuid.uuid4().hex[:8]}", domain_allowlist=["*"], suggestions=[],
        proactive_message="", enable_escalation=enable_escalation,
    ))
    db_session.add(EscalationRule(id=uuid.uuid4(), name="Solicita agente", trigger_type="user_request",
                                  trigger_config={}, enabled=True))
    await db_session.commit()


@pytest.mark.asyncio
async def test_human_request_gets_direct_reply_when_escalation_is_available(db_session):
    from app.services.chat.pipeline import HUMAN_REQUEST_REPLY, human_request_reply

    await _widget(db_session, enable_escalation=True)
    assert await human_request_reply(db_session, "Quiero hablar con una persona") == HUMAN_REQUEST_REPLY
    assert await human_request_reply(db_session, "¿Qué necesita una persona para inscribirse?") is None


@pytest.mark.asyncio
async def test_human_request_is_answered_normally_when_escalation_is_disabled(db_session):
    from app.services.chat.pipeline import human_request_reply

    await _widget(db_session, enable_escalation=False)
    assert await human_request_reply(db_session, "Quiero hablar con una persona") is None
