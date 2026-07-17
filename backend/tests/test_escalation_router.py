"""Tests de caracterización para app/api/v1/escalation/router.py.

ping_smtp y test_rule no estaban cubiertos por ningún otro archivo de
test (test_escalation_triggers.py prueba el motor de reglas puro, no
estos endpoints HTTP). Se fijan aquí antes de mover ping_smtp a
servicio, para confirmar que la migración no cambia comportamiento.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.enums import EscalationTrigger
from app.models.escalation_rule import EscalationRule


@pytest.fixture
async def seeded_rule(db_session):
    rule = EscalationRule(
        id=uuid.uuid4(),
        name="Sin respuesta 2 min",
        description="",
        trigger_type=EscalationTrigger.no_answer,
        trigger_config={"wait_seconds": 120},
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


class TestPingSmtp:
    async def test_ping_smtp_not_configured(self, client, admin_user, auth_headers, monkeypatch):
        import app.services.escalation.rules as rules_svc

        async def _no_config(db):
            return None
        monkeypatch.setattr(rules_svc, "get_smtp_config", _no_config)

        r = await client.post("/api/v1/escalation/smtp-ping", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "SMTP no configurado en el servidor"
        assert body["latency_ms"] is None

    async def test_ping_smtp_success(self, client, admin_user, auth_headers, monkeypatch):
        import app.services.escalation.rules as rules_svc
        from app.services.notifications.smtp import SMTPSettings

        async def _fake_config(db):
            return SMTPSettings(host="smtp.test", port=587, user="a", password="b", from_email="a@test.com", tls=True)
        monkeypatch.setattr(rules_svc, "get_smtp_config", _fake_config)

        async def _fake_send_email(*, to, subject, body_html, body_text=None, _config=None, db=None):
            return True
        monkeypatch.setattr(rules_svc, "send_email", _fake_send_email)

        r = await client.post("/api/v1/escalation/smtp-ping", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["status"] == 250
        assert body["error"] is None
        assert body["latency_ms"] is not None

    async def test_ping_smtp_send_fails(self, client, admin_user, auth_headers, monkeypatch):
        import app.services.escalation.rules as rules_svc
        from app.services.notifications.smtp import SMTPSettings

        async def _fake_config(db):
            return SMTPSettings(host="smtp.test", port=587, user="a", password="b", from_email="a@test.com", tls=True)
        monkeypatch.setattr(rules_svc, "get_smtp_config", _fake_config)

        async def _fake_send_email(*, to, subject, body_html, body_text=None, _config=None, db=None):
            return False
        monkeypatch.setattr(rules_svc, "send_email", _fake_send_email)

        r = await client.post("/api/v1/escalation/smtp-ping", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "No se pudo enviar el correo de prueba. Revise la configuración SMTP."


class TestRuleTest:
    async def test_rule_test_by_rule_id(self, client, admin_user, auth_headers, seeded_rule):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={
                "rule_id": str(seeded_rule.id),
                "context": {"no_answer_seconds": 200},
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["matches"] is True
        assert body["trigger_type"] == "no_answer"
        assert body["payload_preview"]["matched"] is True

    async def test_rule_test_by_rule_id_not_found(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={"rule_id": str(uuid.uuid4()), "context": {}},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_rule_test_inline_trigger(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={
                "trigger_type": "no_answer",
                "trigger_config": {"wait_seconds": 60},
                "context": {"no_answer_seconds": 30},
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["matches"] is False
        assert body["payload_preview"]["trigger_type"] == "no_answer"

    async def test_rule_test_requires_rule_id_or_trigger_type(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules/test",
            json={"context": {}},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400


class TestRulesCrud:
    async def test_list_rules_empty(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/escalation/rules", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_create_update_delete_rule(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/escalation/rules",
            json={
                "name": "Prueba",
                "description": "",
                "trigger_type": "user_request",
                "trigger_config": {},
                "enabled": True,
            },
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        rule_id = r.json()["id"]

        r2 = await client.patch(
            f"/api/v1/escalation/rules/{rule_id}",
            json={"enabled": False},
            headers=auth_headers(admin_user),
        )
        assert r2.status_code == 200
        assert r2.json()["enabled"] is False

        r3 = await client.delete(f"/api/v1/escalation/rules/{rule_id}", headers=auth_headers(admin_user))
        assert r3.status_code == 204

    async def test_update_rule_not_found(self, client, admin_user, auth_headers):
        r = await client.patch(
            f"/api/v1/escalation/rules/{uuid.uuid4()}",
            json={"enabled": False},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404
