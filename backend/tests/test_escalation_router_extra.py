"""Tests para los endpoints de app/api/v1/escalation/router.py no cubiertos
por test_escalation_router.py (ping_smtp, test_rule, rules CRUD) ni por
test_conversations_router.py (que no toca este router en absoluto).

Cubre: list_trigger_schemas, test_escalation, get_escalation_metrics, y RBAC
(admin/editor/viewer) para todos los endpoints del módulo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, EscalationEventType, EscalationTrigger, UserRole
from app.models.escalation_event import EscalationEvent
from app.models.escalation_rule import EscalationRule


@pytest.fixture
async def editor_user(make_user):
    return await make_user(role=UserRole.editor)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


class TestTriggerSchemas:
    async def test_list_trigger_schemas_admin(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/escalation/triggers/schemas", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        trigger_types = {item["trigger_type"] for item in body}
        assert trigger_types == {t.value for t in EscalationTrigger}

    async def test_list_trigger_schemas_shape(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/escalation/triggers/schemas", headers=auth_headers(admin_user))
        body = r.json()
        no_answer = next(item for item in body if item["trigger_type"] == "no_answer")
        assert "wait_seconds" in no_answer["fields"]
        assert no_answer["fields"]["wait_seconds"]["default"] == 120

    async def test_list_trigger_schemas_editor_allowed(self, client, editor_user, auth_headers):
        r = await client.get("/api/v1/escalation/triggers/schemas", headers=auth_headers(editor_user))
        assert r.status_code == 200

    async def test_list_trigger_schemas_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/escalation/triggers/schemas", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_list_trigger_schemas_requires_auth(self, client):
        r = await client.get("/api/v1/escalation/triggers/schemas")
        assert r.status_code == 401


class TestEscalationTest:
    async def test_test_escalation_dispatches_to_admins(self, client, admin_user, auth_headers, monkeypatch):
        import app.api.v1.escalation.router as router_mod

        calls = []

        async def _fake_dispatch(db, *, conversation_id, question, reason, **kwargs):
            calls.append({"conversation_id": conversation_id, "question": question, "reason": reason})

        monkeypatch.setattr(router_mod.svc, "dispatch_escalation", _fake_dispatch)

        r = await client.post("/api/v1/escalation/test", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "administradores" in body["message"]
        assert len(calls) == 1
        assert calls[0]["conversation_id"] == "test-conversation"

    async def test_test_escalation_editor_forbidden(self, client, editor_user, auth_headers):
        r = await client.post("/api/v1/escalation/test", headers=auth_headers(editor_user))
        assert r.status_code == 403

    async def test_test_escalation_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.post("/api/v1/escalation/test", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_test_escalation_requires_auth(self, client):
        r = await client.post("/api/v1/escalation/test")
        assert r.status_code == 401


class TestEscalationMetrics:
    async def test_metrics_empty(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/escalation/metrics", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["by_status"] == {}
        assert body["by_trigger"] == {}
        assert body["avg_resolution_seconds"] is None
        assert body["resolution_rate"] is None
        assert body["csat_avg"] is None

    async def test_metrics_with_real_data(self, client, admin_user, auth_headers, db_session):
        now = datetime.now(timezone.utc)

        conv_resolved = ChatConversation(
            id=uuid.uuid4(),
            session_id=str(uuid.uuid4()),
            status=ConversationStatus.resolved,
            escalated_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
            csat_score=4,
        )
        conv_escalated = ChatConversation(
            id=uuid.uuid4(),
            session_id=str(uuid.uuid4()),
            status=ConversationStatus.escalated,
            escalated_at=now - timedelta(minutes=30),
        )
        db_session.add_all([conv_resolved, conv_escalated])
        await db_session.flush()

        event = EscalationEvent(
            id=uuid.uuid4(),
            conversation_id=conv_resolved.id,
            event_type=EscalationEventType.escalated,
            trigger_type="no_answer",
            created_at=now - timedelta(hours=2),
        )
        db_session.add(event)
        await db_session.commit()

        r = await client.get("/api/v1/escalation/metrics?days=7", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["by_status"]["resolved"] == 1
        assert body["by_status"]["escalated"] == 1
        assert body["by_trigger"]["no_answer"] == 1
        assert body["resolved_count"] == 1
        assert body["resolution_rate"] == pytest.approx(0.5)
        assert body["avg_resolution_seconds"] == pytest.approx(3600.0, rel=0.01)
        assert body["csat_avg"] == pytest.approx(4.0)

    async def test_metrics_days_out_of_range_rejected(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/escalation/metrics?days=0", headers=auth_headers(admin_user))
        assert r.status_code == 422

        r2 = await client.get("/api/v1/escalation/metrics?days=9999", headers=auth_headers(admin_user))
        assert r2.status_code == 422

    async def test_metrics_editor_allowed(self, client, editor_user, auth_headers):
        r = await client.get("/api/v1/escalation/metrics", headers=auth_headers(editor_user))
        assert r.status_code == 200

    async def test_metrics_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/escalation/metrics", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_metrics_requires_auth(self, client):
        r = await client.get("/api/v1/escalation/metrics")
        assert r.status_code == 401


class TestRulesRbac:
    async def test_list_rules_editor_allowed(self, client, editor_user, auth_headers):
        r = await client.get("/api/v1/escalation/rules", headers=auth_headers(editor_user))
        assert r.status_code == 200

    async def test_list_rules_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/escalation/rules", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_create_rule_editor_forbidden(self, client, editor_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules",
            json={
                "name": "Intento editor",
                "description": "",
                "trigger_type": "user_request",
                "trigger_config": {},
                "enabled": True,
            },
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_delete_rule_editor_forbidden(self, client, editor_user, auth_headers, db_session):
        rule = EscalationRule(
            id=uuid.uuid4(),
            name="Regla existente",
            description="",
            trigger_type=EscalationTrigger.user_request,
            trigger_config={},
            enabled=True,
        )
        db_session.add(rule)
        await db_session.commit()

        r = await client.delete(
            f"/api/v1/escalation/rules/{rule.id}", headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_rules_requires_auth(self, client):
        r = await client.get("/api/v1/escalation/rules")
        assert r.status_code == 401


class TestSmtpPingAndRuleTestRbac:
    async def test_ping_smtp_editor_forbidden(self, client, editor_user, auth_headers):
        r = await client.post("/api/v1/escalation/smtp-ping", headers=auth_headers(editor_user))
        assert r.status_code == 403

    async def test_ping_smtp_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.post("/api/v1/escalation/smtp-ping", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_rule_test_editor_forbidden(self, client, editor_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={"trigger_type": "no_answer", "trigger_config": {}, "context": {}},
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_rule_test_viewer_forbidden(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={"trigger_type": "no_answer", "trigger_config": {}, "context": {}},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403
