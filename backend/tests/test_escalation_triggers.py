"""Cobertura de los triggers de escalación no_answer y negative_feedback.

Verifica que pipeline.detect_escalation() calcule y pase al motor de reglas
valores reales de no_answer_seconds y feedback_negative_ratio, para que las
reglas de esos dos tipos puedan dispararse según la configuración y el
comportamiento real del chatbot.
"""
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

# Timestamp creciente explícito: varios mensajes insertados en el mismo instante de reloj de MySQL no tendrían desempate estable en el ORDER BY created_at.
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
        db_session, conv, question="test", history=[], final_text="respuesta",
        latency_ms=500,
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
        latency_ms=8000,
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
        latency_ms=500,
    )
    assert escalated is False
    assert conv.escalation_pending is False


@pytest.mark.asyncio
async def test_recent_assistant_rag_scores_reads_real_history_chronologically(db_session):
    """confidence_below evalúa "N respuestas consecutivas": los scores se leen
    del historial real de la conversación en orden cronológico, no de los N
    chunks de la respuesta actual (que es una señal distinta)."""
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
        db_session, conv, question="hola", history=[], final_text="¡Hola! ¿En qué puedo ayudarte?",
        latency_ms=100,
    )
    assert escalated is False
    assert conv.escalation_pending is False


@pytest.mark.asyncio
async def test_detect_escalation_fails_safe_and_logs_degraded(db_session, monkeypatch):
    """Si evaluate_rule lanza (p.ej. trigger_config corrupto guardado por un
    admin), detect_escalation debía devolver False sin propagar la excepción
    - eso ya funcionaba. Lo que faltaba: el log de este camino era idéntico
    al de "ninguna regla se disparó" (mismo mensaje, sin marca distintiva),
    así que un fallo sistemático de evaluación era indistinguible de que
    simplemente no hubiera nada que escalar. degraded=True lo hace visible,
    igual que llm.grade_failed_open."""
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
        db_session, conv, question="test", history=[], final_text="respuesta",
        latency_ms=500,
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
    """El propio turno actual (persistido por persist_turn antes de llamar a
    detect_escalation) ya cuenta como el N-ésimo de la secuencia."""
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
        db_session, conv, question="test", history=[], final_text="respuesta",
        latency_ms=500,
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
        db_session, conv, question="test", history=[], final_text="respuesta",
        latency_ms=500,
    )
    assert escalated is False


@pytest.mark.asyncio
async def test_uses_published_enable_escalation_over_live_row(db_session):
    """Reproduce el bug real: la fila viva de WidgetConfig tiene
    enable_escalation=False (cambiada en el panel sin republicar), pero la
    última versión publicada (trigger_source='deploy') la tenía en True -
    debe ganar la publicada, que es la misma fuente que GET
    /widget/public/config le muestra al usuario del widget."""
    from app.models.config_version import ConfigVersion
    from app.models.widget_config import WidgetConfig

    conv = await _make_conversation(db_session)
    db_session.add(WidgetConfig(
        id=uuid.uuid4(), api_key="wk_test_key", enable_escalation=False,
    ))
    db_session.add(ConfigVersion(
        id=uuid.uuid4(), version_number=1, trigger_source="deploy", is_active=False,
        config_snapshot={
            "schema_version": 2,
            "sections": {"widget_config": {"enable_escalation": True}},
        },
    ))
    rule = EscalationRule(
        id=uuid.uuid4(), name="Usuario solicita agente", trigger_type="user_request",
        trigger_config={}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="Quiero hablar con un humano", history=[],
        final_text="respuesta", latency_ms=500,
    )
    assert escalated is True
    assert conv.escalation_pending is True


@pytest.mark.asyncio
async def test_respects_live_row_when_never_published(db_session):
    """Sin ninguna versión publicada (nunca se hizo deploy), cae al mismo
    fallback que public_config: la fila viva de WidgetConfig."""
    from app.models.widget_config import WidgetConfig

    conv = await _make_conversation(db_session)
    db_session.add(WidgetConfig(
        id=uuid.uuid4(), api_key="wk_test_key_2", enable_escalation=False,
    ))
    rule = EscalationRule(
        id=uuid.uuid4(), name="Usuario solicita agente", trigger_type="user_request",
        trigger_config={}, enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    escalated = await detect_escalation(
        db_session, conv, question="Quiero hablar con un humano", history=[],
        final_text="respuesta", latency_ms=500,
    )
    assert escalated is False
    assert conv.escalation_pending is False
