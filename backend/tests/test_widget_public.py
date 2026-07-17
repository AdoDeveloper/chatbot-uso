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
        api_key="test-widget-key-public",
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


class TestPublicConfig:
    async def test_get_config_with_valid_key(self, client, widget_config):
        r = await client.get(
            "/api/v1/widget/public/config",
            headers={"X-Widget-Key": widget_config.api_key},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["chatbot_name"] == "Test Bot"

    async def test_get_config_without_key_is_403(self, client):
        r = await client.get("/api/v1/widget/public/config")
        assert r.status_code == 403

    async def test_get_config_with_invalid_key_is_403(self, client):
        r = await client.get(
            "/api/v1/widget/public/config",
            headers={"X-Widget-Key": "invalid-key"},
        )
        assert r.status_code == 403


class TestPublicChat:
    async def test_chat_with_valid_key_returns_200(self, client, widget_config):
        async with client.stream(
            "POST", "/api/v1/widget/public/chat",
            json={"question": "hola", "session_id": "test-session"},
            headers={"X-Widget-Key": widget_config.api_key},
        ) as resp:
            assert resp.status_code == 200

    async def test_chat_without_key_is_403(self, client):
        r = await client.post(
            "/api/v1/widget/public/chat",
            json={"question": "hola"},
        )
        assert r.status_code == 403


class TestPublicFeedback:
    async def test_feedback_requires_widget_key(self, client):
        r = await client.patch(
            f"/api/v1/widget/public/messages/{uuid.uuid4()}/feedback",
            json={"feedback": "positive"},
        )
        assert r.status_code == 403


class TestPublicEscalation:
    async def test_escalation_contact_requires_widget_key(self, client):
        r = await client.post(
            "/api/v1/widget/public/escalation/contact",
            json={"contact_type": "email", "contact_value": "a@b.com"},
        )
        assert r.status_code == 403


class TestPublicCsat:
    async def test_csat_requires_widget_key(self, client):
        r = await client.post(
            "/api/v1/widget/public/csat",
            json={"conversation_id": str(uuid.uuid4()), "score": 4},
        )
        assert r.status_code == 403
