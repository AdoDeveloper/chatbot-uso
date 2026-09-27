"""Búsqueda de texto en el listado de conversaciones."""
from __future__ import annotations

import uuid

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageRole
from app.services.chat.history import list_conversations


async def _conversation_with(db, text: str) -> ChatConversation:
    conv = ChatConversation(id=uuid.uuid4(), session_id=str(uuid.uuid4()), status=ConversationStatus.active)
    db.add(conv)
    await db.flush()
    db.add(ChatMessage(conversation_id=conv.id, role=MessageRole.user, content=text))
    await db.commit()
    return conv


async def test_percent_and_underscore_are_searched_literally(db_session):
    beca = await _conversation_with(db_session, "¿La beca cubre el 100% del arancel?")
    await _conversation_with(db_session, "¿Cuándo es la matrícula?")
    guion = await _conversation_with(db_session, "Mi usuario es juan_perez")

    rows, total = await list_conversations(db_session, search="100%", source="all")
    assert [c.id for c in rows] == [beca.id] and total == 1

    rows, total = await list_conversations(db_session, search="n_p", source="all")
    assert [c.id for c in rows] == [guion.id] and total == 1
