from __future__ import annotations

import pytest

from app.schemas.settings import NO_CONTEXT_MESSAGE
from app.services.rag.quality import is_no_answer_reply


@pytest.mark.parametrize("text", [
    "No dispongo de esa información. Le sugiero contactar a Registro Académico.",
    "No tengo información sobre el horario de la cafetería.",
    "Lo siento, no encontré información sobre ese trámite.",
    "En el reglamento no se especifica la fecha de aprobación.",
    NO_CONTEXT_MESSAGE,
])
def test_detects_knowledge_gaps(text):
    assert is_no_answer_reply(text) is True


@pytest.mark.parametrize("text", [
    "El curso pre-universitario cuesta $30 y dura 3 semanas.",
    "Solo puedo ayudarle con temas de la Universidad de Sonsonate.",
    "",
    None,
    "Para la constancia pague $10. " * 20 + "No dispongo de otros datos.",
])
def test_ignores_real_answers_and_off_topic_refusals(text):
    assert is_no_answer_reply(text) is False
