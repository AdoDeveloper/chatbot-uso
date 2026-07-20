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
    """3 notification logs in_app visibles para admin, con target para
    verificar el enmascarado en la respuesta."""
    logs = [
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready.value,
            channel="in_app",
            target="admin@uso.edu.sv",
            status="sent",
            error_message=None,
            payload_json={},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_error.value,
            channel="in_app",
            target="50312345678",
            status="failed",
            error_message="timeout",
            payload_json={},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.escalation.value,
            channel="in_app",
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
        # alfabéticamente — doc_ready antes que doc_error, luego escalation.
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
        email_item = items["doc_ready"]
        assert email_item["target"] == "ad***@uso.edu.sv"
        assert "admin@uso.edu.sv" not in r.text

    async def test_masks_non_email_target(self, client, admin_user, auth_headers, seed_logs):
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        items = {item["event"]: item for item in r.json()["items"]}
        phone_item = items["doc_error"]
        assert phone_item["target"] == "503***"

    async def test_empty_target_masks_to_none(self, client, admin_user, auth_headers, seed_logs):
        """_mask_target trata "" (falsy) igual que None: no revela nada."""
        r = await client.get(
            "/api/v1/notifications", headers=auth_headers(admin_user)
        )
        items = {item["event"]: item for item in r.json()["items"]}
        assert items["escalation"]["target"] is None
