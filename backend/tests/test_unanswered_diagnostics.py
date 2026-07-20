from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import MessageRole
from app.models.unanswered_question import UnansweredQuestion
from app.services.knowledge.unanswered_diagnostics import root_cause_analysis


async def _make_conversation(db_session, *, session_id: str | None = None) -> ChatConversation:
    conv = ChatConversation(
        id=uuid.uuid4(),
        session_id=session_id or f"sess-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _make_message(
    db_session,
    *,
    conversation_id,
    role: MessageRole,
    content: str,
    rag_route: str | None = None,
    sources_json: list | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        rag_route=rag_route,
        sources_json=sources_json if sources_json is not None else [],
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


async def _make_unanswered(
    db_session,
    *,
    question: str,
    conversation_id=None,
    detected_topic: str | None = None,
) -> UnansweredQuestion:
    q = UnansweredQuestion(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        question=question,
        detected_topic=detected_topic,
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)
    return q


@pytest.mark.asyncio
async def test_root_cause_analysis_not_found_raises(db_session):
    with pytest.raises(NotFoundError):
        await root_cause_analysis(db_session, question_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_root_cause_analysis_indeterminate_without_conversation(db_session):
    q = await _make_unanswered(db_session, question="Pregunta sin conversacion asociada")

    result = await root_cause_analysis(db_session, question_id=q.id)

    assert result["question_id"] == str(q.id)
    codes = [c["code"] for c in result["causes"]]
    assert codes == ["indeterminate"]
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_root_cause_analysis_recurring_question(db_session):
    text = "Como reinicio mi contrasena de acceso al sistema"
    for _ in range(3):
        await _make_unanswered(db_session, question=text)
    # Case-insensitive matching: same text with different casing still counts.
    target = await _make_unanswered(db_session, question=text.upper())

    result = await root_cause_analysis(db_session, question_id=target.id)

    codes = [c["code"] for c in result["causes"]]
    assert "recurring" in codes
    recurring = next(c for c in result["causes"] if c["code"] == "recurring")
    assert "4 veces" in recurring["detail"]
    assert any("FAQ" in s for s in result["suggestions"])


@pytest.mark.asyncio
async def test_root_cause_analysis_below_threshold_not_recurring(db_session):
    text = "Pregunta que aparece solo dos veces"
    await _make_unanswered(db_session, question=text)
    target = await _make_unanswered(db_session, question=text)

    result = await root_cause_analysis(db_session, question_id=target.id)

    codes = [c["code"] for c in result["causes"]]
    assert "recurring" not in codes


@pytest.mark.asyncio
async def test_root_cause_analysis_no_coverage(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session, conversation_id=conv.id, role=MessageRole.user, content="hola"
    )
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="No tengo informacion suficiente para responder.",
        rag_route="no_context",
    )
    q = await _make_unanswered(
        db_session, question="Pregunta sin cobertura", conversation_id=conv.id, detected_topic="facturacion"
    )

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "no_coverage" in codes
    no_cov = next(c for c in result["causes"] if c["code"] == "no_coverage")
    assert "no_context" in no_cov["detail"]
    assert any("facturacion" in s for s in result["suggestions"])


@pytest.mark.asyncio
async def test_root_cause_analysis_no_match_route_also_counts_as_no_coverage(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="respuesta generica",
        rag_route="NO_MATCH",
    )
    q = await _make_unanswered(db_session, question="otra pregunta", conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "no_coverage" in codes


@pytest.mark.asyncio
async def test_root_cause_analysis_loop_detected(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session, conversation_id=conv.id, role=MessageRole.user, content="pregunta 1"
    )
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="Lo siento, no puedo ayudar con eso.",
        rag_route="answered",
    )
    await _make_message(
        db_session, conversation_id=conv.id, role=MessageRole.user, content="pregunta 2"
    )
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="Lo siento, no puedo ayudar con eso.",
        rag_route="answered",
    )
    q = await _make_unanswered(db_session, question="pregunta en bucle", conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "loop" in codes
    assert any("loop_detected" in s for s in result["suggestions"])


@pytest.mark.asyncio
async def test_root_cause_analysis_low_confidence_sources(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="respuesta con baja confianza",
        rag_route="answered",
        sources_json=[{"score": 0.1}, {"score": 0.2}],
    )
    q = await _make_unanswered(db_session, question="pregunta baja confianza", conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "low_confidence" in codes
    low_conf = next(c for c in result["causes"] if c["code"] == "low_confidence")
    assert "0.20" in low_conf["detail"]
    assert any("score_threshold" in s for s in result["suggestions"])


@pytest.mark.asyncio
async def test_root_cause_analysis_high_confidence_sources_no_low_confidence_cause(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="respuesta con buena confianza",
        rag_route="answered",
        sources_json=[{"score": 0.9}],
    )
    q = await _make_unanswered(db_session, question="pregunta ok", conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "low_confidence" not in codes


@pytest.mark.asyncio
async def test_root_cause_analysis_malformed_sources_json_is_ignored(db_session):
    """sources_json con entradas no-dict o score no numerico: el bloque
    low_confidence usa try/except Exception y no debe romper el análisis."""
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="respuesta con sources raros",
        rag_route="answered",
        sources_json=["not-a-dict", {"score": "abc"}],
    )
    q = await _make_unanswered(db_session, question="pregunta sources raros", conversation_id=conv.id)

    # float("abc") raises ValueError inside the sources-scoring block, but
    # that block is wrapped in `except Exception: pass`, so it's silently
    # swallowed and the analysis still returns normally without a
    # low_confidence cause.
    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert "low_confidence" not in codes


@pytest.mark.asyncio
async def test_root_cause_analysis_only_user_messages_no_bot_reply(db_session):
    conv = await _make_conversation(db_session)
    await _make_message(
        db_session, conversation_id=conv.id, role=MessageRole.user, content="solo usuario"
    )
    q = await _make_unanswered(db_session, question="pregunta sin respuesta de bot", conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=q.id)

    codes = [c["code"] for c in result["causes"]]
    assert codes == ["indeterminate"]


@pytest.mark.asyncio
async def test_root_cause_analysis_multiple_causes_combined(db_session):
    text = "pregunta combinada de varias causas"
    for _ in range(3):
        await _make_unanswered(db_session, question=text)

    conv = await _make_conversation(db_session)
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="No encontre informacion.",
        rag_route="no_context",
    )
    await _make_message(
        db_session,
        conversation_id=conv.id,
        role=MessageRole.assistant,
        content="No encontre informacion.",
        rag_route="no_context",
    )
    target = await _make_unanswered(db_session, question=text, conversation_id=conv.id)

    result = await root_cause_analysis(db_session, question_id=target.id)

    codes = {c["code"] for c in result["causes"]}
    assert "recurring" in codes
    assert "no_coverage" in codes
    assert "loop" in codes
    assert len(result["suggestions"]) == 3
