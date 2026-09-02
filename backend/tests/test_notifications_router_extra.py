"""Tests para endpoints de app/api/v1/notifications/router.py sin cobertura
en test_notifications.py (que ya cubre update de regla, inbox, mark-read y
__repr__ seguro).

Cubre:
  - GET /notifications/rules (listado)
  - GET /notifications/rules/email/status (agregado email_enabled)
  - GET/PUT /notifications/report-schedule
  - PUT /notifications/rules/email/toggle (toggle masivo del canal email)
  - GET /notifications (historial paginado)
  - Enmascarado de target (email/teléfono) en items del historial
"""
from __future__ import annotations

import uuid

import pytest

from app.api.v1.notifications.router import _summarize_payload
from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.notification_log import NotificationLog
from app.models.notification_rule import NotificationRule


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


@pytest.fixture
async def seed_rules(db_session):
    """Siembra reglas para varios eventos/canales, incluyendo email enabled."""
    rules = [
        NotificationRule(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=True,
            target="ops@uso.edu.sv",
            config_json={},
        ),
        NotificationRule(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_error,
            channel=NotificationChannel.email,
            enabled=False,
            target=None,
            config_json={},
        ),
        NotificationRule(
            id=uuid.uuid4(),
            event=NotificationEvent.escalation,
            channel=NotificationChannel.in_app,
            enabled=True,
            target=None,
            config_json={},
        ),
    ]
    for rule in rules:
        db_session.add(rule)
    await db_session.commit()
    return rules


@pytest.fixture
async def seed_logs(db_session):
    """3 notification logs de canal email, con target para verificar el enmascarado."""
    logs = [
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready.value,
            channel="email",
            target="admin@uso.edu.sv",
            status="sent",
            error_message=None,
            payload_json={},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_error.value,
            channel="email",
            target="50312345678",
            status="failed",
            error_message="timeout",
            payload_json={},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.escalation.value,
            channel="email",
            target="",
            status="sent",
            error_message=None,
            payload_json={},
            read_at=None,
        ),
    ]
    for log in logs:
        db_session.add(log)
    await db_session.commit()
    return logs


# ── GET /rules ───────────────────────────────────────────────────────────


class TestListRules:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/notifications/rules")
        assert r.status_code in (401, 403)

    async def test_viewer_rejected(self, client, viewer_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications/rules", headers=auth_headers(viewer_user)
        )
        assert r.status_code in (401, 403)

    async def test_returns_all_rules_ordered(
        self, client, admin_user, auth_headers, seed_rules
    ):
        r = await client.get(
            "/api/v1/notifications/rules", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 3
        # ORDER BY event, channel: MySQL ordena el ENUM nativo por posición de
        # declaración (ver NotificationEvent en app/models/enums.py), no
        # alfabéticamente - doc_ready antes que doc_error, luego escalation.
        assert [item["event"] for item in body] == [
            "doc_ready", "doc_error", "escalation",
        ]

    async def test_empty_when_no_rules(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications/rules", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.json() == []


# ── GET /rules/email/status ─────────────────────────────────────────────


class TestEmailStatus:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/notifications/rules/email/status")
        assert r.status_code in (401, 403)

    async def test_true_when_at_least_one_email_rule_enabled(
        self, client, admin_user, auth_headers, seed_rules
    ):
        r = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        assert r.json()["email_enabled"] is True

    async def test_false_when_no_email_rules_enabled(
        self, client, admin_user, auth_headers, db_session
    ):
        rule = NotificationRule(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=False,
            target=None,
            config_json={},
        )
        db_session.add(rule)
        await db_session.commit()

        r = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.json()["email_enabled"] is False

    async def test_false_when_no_rules_at_all(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.json()["email_enabled"] is False

    async def test_smtp_configured_true_when_env_vars_set(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.services.notifications import smtp as smtp_mod

        async def _fake_get_smtp_config(db=None):
            return smtp_mod.SMTPSettings(
                host="smtp.example.org", port=587, user="bot@example.org",
                password="s3cr3t", from_email="bot@example.org", tls=True,
            )

        monkeypatch.setattr(smtp_mod, "get_smtp_config", _fake_get_smtp_config)
        r = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.json()["smtp_configured"] is True

    async def test_smtp_configured_false_when_missing(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.services.notifications import smtp as smtp_mod

        async def _fake_get_smtp_config(db=None):
            return None

        monkeypatch.setattr(smtp_mod, "get_smtp_config", _fake_get_smtp_config)
        r = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert r.json()["smtp_configured"] is False


# ── PUT /rules/email/toggle ──────────────────────────────────────────────


class TestToggleEmailChannel:
    async def test_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.put(
            "/api/v1/notifications/rules/email/toggle",
            json={"enabled": True},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code in (401, 403)

    async def test_disables_all_email_rules_leaves_in_app_untouched(
        self, client, admin_user, auth_headers, seed_rules
    ):
        r = await client.put(
            "/api/v1/notifications/rules/email/toggle",
            json={"enabled": False},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is False
        assert body["affected"] == 2  # 2 reglas email en el seed

        rules = await client.get(
            "/api/v1/notifications/rules", headers=auth_headers(admin_user)
        )
        by_channel = {r["channel"]: r["enabled"] for r in rules.json()}
        # La regla in_app (escalation) no debió tocarse.
        in_app_rule = next(
            r for r in rules.json() if r["channel"] == "in_app"
        )
        assert in_app_rule["enabled"] is True

    async def test_enables_all_email_rules(
        self, client, admin_user, auth_headers, seed_rules
    ):
        r = await client.put(
            "/api/v1/notifications/rules/email/toggle",
            json={"enabled": True},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["affected"] == 2

        status = await client.get(
            "/api/v1/notifications/rules/email/status", headers=auth_headers(admin_user)
        )
        assert status.json()["email_enabled"] is True

    async def test_no_email_rules_affected_zero(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/notifications/rules/email/toggle",
            json={"enabled": True},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["affected"] == 0


# ── GET / PUT /report-schedule ───────────────────────────────────────────


class TestReportSchedule:
    async def test_get_requires_auth(self, client):
        r = await client.get("/api/v1/notifications/report-schedule")
        assert r.status_code in (401, 403)

    async def test_get_returns_default_when_unset(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications/report-schedule", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unit"] == "daily"
        assert body["hour"] == 8

    async def test_put_requires_admin_perm(self, client, viewer_user, auth_headers):
        r = await client.put(
            "/api/v1/notifications/report-schedule",
            json={"unit": "daily", "hour": 9, "minute": 0},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code in (401, 403)

    async def test_put_updates_and_get_reflects_it(
        self, client, admin_user, auth_headers
    ):
        payload = {
            "unit": "weekly",
            "hour": 14,
            "minute": 30,
            "days_of_week": [0, 2, 4],
        }
        r = await client.put(
            "/api/v1/notifications/report-schedule",
            json=payload,
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        assert r.json()["unit"] == "weekly"
        assert r.json()["hour"] == 14
        assert r.json()["days_of_week"] == [0, 2, 4]

        r2 = await client.get(
            "/api/v1/notifications/report-schedule", headers=auth_headers(admin_user)
        )
        assert r2.json()["unit"] == "weekly"
        assert r2.json()["hour"] == 14

    async def test_put_rejects_weekly_without_days_of_week(
        self, client, admin_user, auth_headers
    ):
        r = await client.put(
            "/api/v1/notifications/report-schedule",
            json={"unit": "weekly", "hour": 8, "minute": 0},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_put_rejects_monthly_without_day_of_month(
        self, client, admin_user, auth_headers
    ):
        r = await client.put(
            "/api/v1/notifications/report-schedule",
            json={"unit": "monthly", "hour": 8, "minute": 0},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_put_rejects_invalid_unit(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/notifications/report-schedule",
            json={"unit": "hourly", "hour": 8, "minute": 0},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422


# ── GET / (historial paginado) ───────────────────────────────────────────


class TestListNotifications:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/notifications")
        assert r.status_code in (401, 403)

    async def test_viewer_rejected(self, client, viewer_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(viewer_user)
        )
        assert r.status_code in (401, 403)

    async def test_returns_paginated_history(
        self, client, admin_user, auth_headers, seed_logs
    ):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert len(body["items"]) == 3

    async def test_respects_page_and_page_size(
        self, client, admin_user, auth_headers, seed_logs
    ):
        r = await client.get(
            "/api/v1/notifications?page=1&page_size=2", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3

        r2 = await client.get(
            "/api/v1/notifications?page=2&page_size=2", headers=auth_headers(admin_user)
        )
        assert len(r2.json()["items"]) == 1

    async def test_empty_history_when_no_logs(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_masks_email_target(self, client, admin_user, auth_headers, seed_logs):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        items = {item["event"]: item for item in r.json()["items"]}
        email_channel = items["doc_ready"]["channels"][0]
        assert email_channel["channel"] == "email"
        assert email_channel["target"] == "ad***@uso.edu.sv"
        assert "admin@uso.edu.sv" not in r.text

    async def test_masks_non_email_target(self, client, admin_user, auth_headers, seed_logs):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        items = {item["event"]: item for item in r.json()["items"]}
        phone_channel = items["doc_error"]["channels"][0]
        assert phone_channel["target"] == "503***"

    async def test_groups_multi_channel_trigger_into_one_row(
        self, client, db_session, admin_user, auth_headers
    ):
        """Un mismo trigger_id entregado por correo y a 3 admins in_app
        aparece como una fila con 2 canales, no 4 filas crudas."""
        trigger_id = uuid.uuid4()
        db_session.add(NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.service_down.value, channel="email",
            target="ops@uso.edu.sv", status="sent", error_message=None,
            payload_json={}, read_at=None,
        ))
        for _ in range(3):
            db_session.add(NotificationLog(
                id=uuid.uuid4(), trigger_id=trigger_id,
                event=NotificationEvent.service_down.value, channel="in_app",
                target="in_app", status="sent", error_message=None,
                payload_json={}, read_at=None,
            ))
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        trigger = body["items"][0]
        assert trigger["id"] == str(trigger_id)
        assert trigger["event"] == "service_down"
        channels = {c["channel"]: c for c in trigger["channels"]}
        assert channels["email"]["recipients"] == 1
        assert channels["email"]["target"] == "op***@uso.edu.sv"
        assert channels["in_app"]["recipients"] == 3
        assert channels["in_app"]["target"] is None  # in_app no expone un destino individual

    async def test_channel_status_reflects_any_failure_in_the_group(
        self, client, db_session, admin_user, auth_headers
    ):
        """Si al menos una entrega del canal falló, el canal se reporta 'failed'."""
        trigger_id = uuid.uuid4()
        db_session.add(NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="email",
            target="a@uso.edu.sv", status="sent", error_message=None,
            payload_json={}, read_at=None,
        ))
        db_session.add(NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="email",
            target="b@uso.edu.sv", status="failed", error_message="smtp timeout",
            payload_json={}, read_at=None,
        ))
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        body = r.json()
        trigger = next(t for t in body["items"] if t["id"] == str(trigger_id))
        email_channel = trigger["channels"][0]
        assert email_channel["status"] == "failed"
        assert email_channel["error_message"] == "smtp timeout"
        assert email_channel["recipients"] == 2

    async def test_empty_target_masks_to_none(self, client, admin_user, auth_headers, seed_logs):
        """_mask_target trata "" (falsy) igual que None: no revela nada."""
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        items = {item["event"]: item for item in r.json()["items"]}
        assert items["escalation"]["channels"][0]["target"] is None

    async def test_summary_reflects_the_distinguishing_payload_field(
        self, client, db_session, admin_user, auth_headers
    ):
        """El historial distingue dos disparos del mismo evento por su summary."""
        for name in ("Instructivo_alumnos.pdf", "Reglamento_2026.pdf"):
            db_session.add(NotificationLog(
                id=uuid.uuid4(), trigger_id=uuid.uuid4(),
                event=NotificationEvent.doc_ready.value, channel="email",
                target="a@uso.edu.sv", status="sent", error_message=None,
                payload_json={"source_name": name}, read_at=None,
            ))
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        summaries = {t["summary"] for t in r.json()["items"] if t["event"] == "doc_ready"}
        assert "Instructivo_alumnos.pdf" in summaries
        assert "Reglamento_2026.pdf" in summaries

    async def test_own_log_id_points_to_the_requesting_admins_copy(
        self, client, db_session, admin_user, make_user, auth_headers
    ):
        other_admin = await make_user(role=UserRole.admin, email="other@test.local")
        trigger_id = uuid.uuid4()
        own_log = NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="in_app",
            target="in_app", status="sent", error_message=None,
            payload_json={}, read_at=None, user_id=admin_user.id,
        )
        other_log = NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="in_app",
            target="in_app", status="sent", error_message=None,
            payload_json={}, read_at=None, user_id=other_admin.id,
        )
        db_session.add(own_log)
        db_session.add(other_log)
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        trigger = next(t for t in r.json()["items"] if t["id"] == str(trigger_id))
        assert trigger["own_log_id"] == str(own_log.id)
        assert trigger["own_read_at"] is None

    async def test_own_log_id_reflects_read_state(
        self, client, db_session, admin_user, auth_headers
    ):
        from datetime import datetime, timezone
        trigger_id = uuid.uuid4()
        db_session.add(NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="in_app",
            target="in_app", status="sent", error_message=None,
            payload_json={}, read_at=datetime.now(timezone.utc), user_id=admin_user.id,
        ))
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        trigger = next(t for t in r.json()["items"] if t["id"] == str(trigger_id))
        assert trigger["own_read_at"] is not None

    async def test_own_log_id_is_none_when_only_email_channel(
        self, client, db_session, admin_user, auth_headers
    ):
        trigger_id = uuid.uuid4()
        db_session.add(NotificationLog(
            id=uuid.uuid4(), trigger_id=trigger_id,
            event=NotificationEvent.doc_ready.value, channel="email",
            target="a@uso.edu.sv", status="sent", error_message=None,
            payload_json={}, read_at=None,
        ))
        await db_session.commit()

        r = await client.get("/api/v1/notifications", headers=auth_headers(admin_user))
        trigger = next(t for t in r.json()["items"] if t["id"] == str(trigger_id))
        assert trigger["own_log_id"] is None


class TestSummarizePayload:
    """Unit tests de _summarize_payload() (no toca la BD)."""

    def test_doc_ready_uses_source_name(self):
        assert _summarize_payload("doc_ready", {"source_name": "Instructivo.pdf"}) == "Instructivo.pdf"

    def test_doc_error_uses_source_name(self):
        assert _summarize_payload("doc_error", {"source_name": "malformado.docx"}) == "malformado.docx"

    def test_escalation_uses_question(self):
        result = _summarize_payload("escalation", {"question": "¿Cuándo abren las inscripciones?"})
        assert result == "¿Cuándo abren las inscripciones?"

    def test_service_down_uses_service_name(self):
        assert _summarize_payload("service_down", {"service": "qdrant"}) == "Servicio: qdrant"

    def test_provider_down_uses_providers(self):
        result = _summarize_payload("provider_down", {"providers": "Groq, Mistral"})
        assert result == "Groq, Mistral"

    def test_rate_limit_threshold_uses_percent(self):
        assert _summarize_payload("rate_limit_threshold", {"percent": 85.0}) == "85.0% del límite alcanzado"

    def test_unanswered_digest_with_pending(self):
        assert _summarize_payload("unanswered_digest", {"total_open": 3}) == "3 preguntas sin responder"

    def test_unanswered_digest_singular(self):
        assert _summarize_payload("unanswered_digest", {"total_open": 1}) == "1 pregunta sin responder"

    def test_unanswered_digest_zero_pending(self):
        assert _summarize_payload("unanswered_digest", {"total_open": 0}) == "Sin pendientes"

    def test_unknown_event_returns_none(self):
        assert _summarize_payload("some_future_event", {"foo": "bar"}) is None

    def test_empty_payload_returns_none(self):
        assert _summarize_payload("doc_ready", {}) is None

    def test_missing_distinguishing_field_returns_none(self):
        assert _summarize_payload("doc_ready", {"chunks": 12}) is None

    def test_long_value_is_truncated(self):
        long_question = "¿" + "x" * 100 + "?"
        result = _summarize_payload("escalation", {"question": long_question})
        assert result is not None
        assert len(result) <= 80
        assert result.endswith("…")
