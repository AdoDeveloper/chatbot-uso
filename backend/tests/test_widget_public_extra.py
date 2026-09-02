from __future__ import annotations

import uuid

import pytest


@pytest.fixture
async def widget_config(db_session):
    from app.models.widget_config import WidgetConfig
    wc = WidgetConfig(
        id=uuid.uuid4(),
        chatbot_name="Test Bot",
        welcome_message="Hola",
        primary_color="#2563EB",
        position="right",
        api_key="test-widget-key-extra",
        domain_allowlist=["*"],
        show_sources=True,
        enable_feedback_icons=True,
        show_bot_icon=True,
        suggestions=[],
        proactive_message="",
        enable_csat=True,
        csat_question="¿Qué tan útil fue?",
    )
    db_session.add(wc)
    await db_session.commit()
    return wc


@pytest.fixture
async def make_conversation(db_session):
    from app.models.chat_conversation import ChatConversation
    from app.models.enums import ConversationStatus

    async def _factory(*, escalation_pending=False, escalation_trigger_reason=None):
        c = ChatConversation(
            id=uuid.uuid4(), session_id=f"sess-{uuid.uuid4().hex[:8]}",
            status=ConversationStatus.active,
            escalation_pending=escalation_pending,
            escalation_trigger_reason=escalation_trigger_reason,
        )
        db_session.add(c)
        await db_session.commit()
        await db_session.refresh(c)
        return c
    return _factory


@pytest.fixture
def stub_dispatch_escalation(monkeypatch):
    calls = []

    async def _fake_dispatch(db, *, conversation_id, question, reason, trigger_type=None, extra=None):
        calls.append({
            "conversation_id": conversation_id, "question": question,
            "reason": reason, "trigger_type": trigger_type, "extra": extra,
        })

    import app.api.v1.widget.router as widget_router
    monkeypatch.setattr(
        "app.services.escalation.service.dispatch_escalation", _fake_dispatch
    )
    return calls


class TestPublicEscalationContact:
    async def test_manual_request_without_pending_flag_succeeds(
        self, client, widget_config, make_conversation, stub_dispatch_escalation
    ):
        """Un contacto manual sin escalation_pending previo debe aceptarse igual."""
        conv = await make_conversation(escalation_pending=False)
        r = await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"conversation_id": str(conv.id), "contact_type": "email", "contact_value": "a@b.com"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        assert len(stub_dispatch_escalation) == 1
        assert stub_dispatch_escalation[0]["trigger_type"] == "user_consent"

    async def test_conversation_not_found_returns_404(self, client, widget_config, stub_dispatch_escalation):
        r = await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"conversation_id": str(uuid.uuid4()), "contact_type": "email", "contact_value": "a@b.com"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 404

    async def test_pending_escalation_dispatches_and_clears_flag(
        self, client, widget_config, make_conversation, stub_dispatch_escalation, db_session
    ):
        conv = await make_conversation(escalation_pending=True, escalation_trigger_reason="no_answer")
        r = await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"conversation_id": str(conv.id), "contact_type": "whatsapp", "contact_value": "+50370000000"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        assert len(stub_dispatch_escalation) == 1
        assert stub_dispatch_escalation[0]["trigger_type"] == "user_consent"

        await db_session.refresh(conv)
        assert conv.escalation_pending is False

    async def test_manual_request_leaves_pending_flag_unaffected(
        self, client, widget_config, make_conversation, stub_dispatch_escalation, db_session
    ):
        """El flag sigue False: nunca estuvo True, no hay nada que limpiar."""
        conv = await make_conversation(escalation_pending=False)
        await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"conversation_id": str(conv.id), "contact_type": "whatsapp", "contact_value": "+50370000000"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        await db_session.refresh(conv)
        assert conv.escalation_pending is False

    async def test_without_conversation_id_dispatches_manual_request(
        self, client, widget_config, stub_dispatch_escalation
    ):
        r = await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"contact_type": "email", "contact_value": "manual@x.com"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        assert len(stub_dispatch_escalation) == 1
        assert stub_dispatch_escalation[0]["conversation_id"] == ""


class TestPublicFeedback:
    async def test_feedback_on_existing_message(self, client, widget_config, db_session, make_conversation):
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        conv = await make_conversation()
        msg = ChatMessage(id=uuid.uuid4(), conversation_id=conv.id, role=MessageRole.assistant, content="respuesta")
        db_session.add(msg)
        await db_session.commit()

        r = await client.patch(
            f"/api/v1/widget/public/messages/{msg.id}/feedback",
            json={"feedback": "positive", "conversation_id": str(conv.id)},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        await db_session.refresh(msg)
        assert msg.feedback == "positive"

    async def test_feedback_on_nonexistent_message_is_noop_204(self, client, widget_config):
        r = await client.patch(
            f"/api/v1/widget/public/messages/{uuid.uuid4()}/feedback",
            json={"feedback": "negative", "conversation_id": str(uuid.uuid4())},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204

    async def test_feedback_requires_conversation_id(self, client, widget_config, db_session, make_conversation):
        """conversation_id ahora es obligatorio - sin él, message_id por sí
        solo no prueba que el llamante pertenezca a esa conversación."""
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        conv = await make_conversation()
        msg = ChatMessage(id=uuid.uuid4(), conversation_id=conv.id, role=MessageRole.assistant, content="respuesta")
        db_session.add(msg)
        await db_session.commit()

        r = await client.patch(
            f"/api/v1/widget/public/messages/{msg.id}/feedback",
            json={"feedback": "positive"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 422

    async def test_feedback_with_wrong_conversation_id_is_rejected(
        self, client, widget_config, db_session, make_conversation,
    ):
        """IDOR: un mensaje real, pero con un conversation_id que no le
        pertenece, no debe poder alterar el feedback - antes bastaba con
        adivinar/interceptar el message_id, sin ninguna prueba de que el
        llamante fuera parte de esa conversación."""
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        real_conv = await make_conversation()
        other_conv = await make_conversation()
        msg = ChatMessage(
            id=uuid.uuid4(), conversation_id=real_conv.id,
            role=MessageRole.assistant, content="respuesta",
        )
        db_session.add(msg)
        await db_session.commit()

        r = await client.patch(
            f"/api/v1/widget/public/messages/{msg.id}/feedback",
            json={"feedback": "positive", "conversation_id": str(other_conv.id)},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204  # noop, mismo comportamiento que "mensaje inexistente"
        await db_session.refresh(msg)
        assert msg.feedback is None


class TestPublicCsat:
    async def test_csat_disabled_returns_403(self, client, db_session):
        from app.models.widget_config import WidgetConfig
        wc = WidgetConfig(
            id=uuid.uuid4(), chatbot_name="Bot", welcome_message="Hola", primary_color="#000",
            position="right", api_key="test-widget-key-nocsat", domain_allowlist=["*"],
            show_sources=True, enable_feedback_icons=True, show_bot_icon=True,
            suggestions=[], proactive_message="", enable_csat=False, csat_question="",
        )
        db_session.add(wc)
        await db_session.commit()

        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(uuid.uuid4()), "score": 5},
            headers={"X-Widget-Key": wc.api_key},
        )
        assert r.status_code == 403

    async def test_csat_enabled_records_score(self, client, widget_config, make_conversation, db_session):
        conv = await make_conversation()
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(conv.id), "score": 4, "comment": "buena atención"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        await db_session.refresh(conv)
        assert conv.csat_score == 4
        assert conv.csat_comment == "buena atención"
        assert conv.csat_reasons == []

    async def test_csat_records_known_reasons(self, client, widget_config, make_conversation, db_session):
        conv = await make_conversation()
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={
                "conversation_id": str(conv.id), "score": 5,
                "reasons": ["helpful_answer", "fast_response"],
            },
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        await db_session.refresh(conv)
        assert conv.csat_reasons == ["helpful_answer", "fast_response"]

    async def test_csat_rejects_unknown_reason(self, client, widget_config, make_conversation):
        conv = await make_conversation()
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(conv.id), "score": 5, "reasons": ["not_a_real_reason"]},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 422

    async def test_csat_deduplicates_reasons(self, client, widget_config, make_conversation, db_session):
        conv = await make_conversation()
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(conv.id), "score": 3, "reasons": ["no_solution", "no_solution"]},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 204
        await db_session.refresh(conv)
        assert conv.csat_reasons == ["no_solution"]


class TestPublicChatLlmQueueTimeout:
    async def test_llm_queue_timeout_returns_503(self, client, widget_config, monkeypatch):
        """Reproduce el timeout de adquisición del semáforo LLM. La rama de
        error usa `log.warning(...)`, pero `log` nunca se define/importa en
        app/api/v1/widget/router.py - esto dispara un NameError que oculta
        el 503 real detrás de un 500 genérico del handler global."""
        import asyncio
        import app.api.v1.widget.router as widget_router

        async def _timeout_acquire():
            raise asyncio.TimeoutError()

        class _FakeSemaphore:
            def acquire(self):
                return _timeout_acquire()

        monkeypatch.setattr(widget_router, "_llm_semaphore", None, raising=False)

        import app.api.v1.chat.router as chat_router
        monkeypatch.setattr(chat_router, "_llm_semaphore", _FakeSemaphore())

        r = await client.post(
            "/api/v1/widget/public/chat",
            json={"question": "hola", "session_id": "timeout-session"},
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 503
        assert "solicitado" in r.json()["detail"]
