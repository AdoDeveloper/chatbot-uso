import uuid

from app.models.chat_conversation import ChatConversation
from app.services.escalation import lifecycle


async def _conversation(db_session) -> ChatConversation:
    conv = ChatConversation(id=uuid.uuid4(), session_id=str(uuid.uuid4()))
    db_session.add(conv)
    await db_session.commit()
    return conv


async def test_contact_left_by_the_visitor_is_kept_with_the_escalation(db_session):
    conv = await _conversation(db_session)

    await lifecycle.mark_escalated(
        db_session, conversation_id=conv.id, trigger_type="user_consent",
        meta={"reason": "Solicitud", "contact": {"type": "email", "value": "alumno@correo.com"}},
    )

    contacts = await lifecycle.latest_contacts(db_session, [conv.id])
    assert contacts[conv.id] == {"type": "email", "value": "alumno@correo.com"}


async def test_a_new_contact_replaces_the_previous_one(db_session):
    conv = await _conversation(db_session)
    await lifecycle.mark_escalated(
        db_session, conversation_id=conv.id,
        meta={"contact": {"type": "email", "value": "viejo@correo.com"}},
    )

    await lifecycle.mark_escalated(
        db_session, conversation_id=conv.id,
        meta={"contact": {"type": "whatsapp", "value": "+50377778888"}},
    )

    contacts = await lifecycle.latest_contacts(db_session, [conv.id])
    assert contacts[conv.id] == {"type": "whatsapp", "value": "+50377778888"}


async def test_conversation_list_shows_the_contact(client, make_user, auth_headers, db_session):
    from app.models.enums import UserRole

    admin = await make_user(role=UserRole.admin)
    conv = await _conversation(db_session)
    await lifecycle.mark_escalated(
        db_session, conversation_id=conv.id,
        meta={"contact": {"type": "email", "value": "alumno@correo.com"}},
    )

    r = await client.get("/api/v1/conversations?status=escalated", headers=auth_headers(admin))

    item = next(i for i in r.json()["items"] if i["id"] == str(conv.id))
    assert item["escalation_contact"] == {"type": "email", "value": "alumno@correo.com"}
