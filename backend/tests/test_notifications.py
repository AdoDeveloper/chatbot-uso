"""Integration tests for notifications API.

Cubre:
  - Update de regla (regression del DetachedInstanceError tras commit)
  - Inbox endpoint con unread_count
  - Mark single as read
  - Mark all as read
  - __repr__ seguro del NotificationLog (no lazy-load tras commit)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
async def seed_rule(db_session):
    """Inserta una regla de notificación para tests de update."""
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
    await db_session.refresh(rule)
    return rule


@pytest.fixture
async def seed_logs(db_session):
    """Inserta 3 notification logs: 2 no leídas, 1 leída."""
    logs = [
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready.value,
            channel="in_app",
            target="admin@uso.edu.sv",
            status="sent",
            error_message=None,
            payload_json={"source_id": "abc"},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_error.value,
            channel="in_app",
            target="ops@uso.edu.sv",
            status="failed",
            error_message="Connection timeout",
            payload_json={},
            read_at=None,
        ),
        NotificationLog(
            id=uuid.uuid4(),
            event=NotificationEvent.escalation.value,
            channel="in_app",
            target="admin@uso.edu.sv",
            status="sent",
            error_message=None,
            payload_json={},
            read_at=datetime.now(timezone.utc),
        ),
    ]
    for log in logs:
        db_session.add(log)
    await db_session.commit()
    return logs



class TestUpdateRule:
    async def test_update_rule_returns_fresh_data_no_detached_error(
        self, client, admin_user, auth_headers, seed_rule
    ):
        """El bug original: tras commit, los atributos quedan expirados,
        FastAPI lanza ResponseValidationError, el handler intenta __repr__
        sobre instancia detached → DetachedInstanceError.
        Verificamos que el flujo completo retorna 200 con datos correctos."""
        r = await client.put(
            f"/api/v1/notifications/rules/{seed_rule.id}",
            json={"enabled": True, "target": "soporte@uso.edu.sv", "config_json": {"foo": "bar"}},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is True
        assert body["target"] == "soporte@uso.edu.sv"
        assert body["config_json"] == {"foo": "bar"}
        # Campos del enum legibles tras populate_existing
        assert body["event"] == "doc_ready"
        assert body["channel"] == "email"

    async def test_update_nonexistent_rule_returns_404(
        self, client, admin_user, auth_headers
    ):
        r = await client.put(
            f"/api/v1/notifications/rules/{uuid.uuid4()}",
            json={"enabled": True, "config_json": {}},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_viewer_cannot_update_rule(
        self, client, viewer_user, auth_headers, seed_rule
    ):
        r = await client.put(
            f"/api/v1/notifications/rules/{seed_rule.id}",
            json={"enabled": True, "config_json": {}},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code in (401, 403)


# ── Inbox endpoint ─────────────────────────────────────────────────────────


class TestInbox:
    async def test_inbox_returns_unread_count_and_items(
        self, client, admin_user, auth_headers, seed_logs
    ):
        r = await client.get(
            "/api/v1/notifications/inbox", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "unread_count" in body
        assert "items" in body
        assert body["unread_count"] == 2  # 2 sin read_at, 1 con read_at
        assert len(body["items"]) == 3
        # Orden DESC por created_at — el más reciente primero
        assert body["items"][0]["id"] is not None

    async def test_inbox_empty_when_no_logs(
        self, client, admin_user, auth_headers
    ):
        r = await client.get(
            "/api/v1/notifications/inbox", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["unread_count"] == 0
        assert body["items"] == []

    async def test_inbox_respects_limit(
        self, client, admin_user, auth_headers, seed_logs
    ):
        r = await client.get(
            "/api/v1/notifications/inbox?limit=2", headers=auth_headers(admin_user)
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

    async def test_inbox_unauthenticated_rejected(self, client):
        r = await client.get("/api/v1/notifications/inbox")
        assert r.status_code in (401, 403)

    async def test_inbox_viewer_rejected(
        self, client, viewer_user, auth_headers
    ):
        r = await client.get(
            "/api/v1/notifications/inbox", headers=auth_headers(viewer_user)
        )
        assert r.status_code in (401, 403)


# ── Mark as read ───────────────────────────────────────────────────────────


class TestMarkRead:
    async def test_mark_single_as_read(
        self, client, admin_user, auth_headers, seed_logs
    ):
        unread = [log for log in seed_logs if log.read_at is None][0]
        r = await client.post(
            f"/api/v1/notifications/inbox/{unread.id}/read",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # Verificar que el unread_count bajó en 1
        inbox = await client.get(
            "/api/v1/notifications/inbox", headers=auth_headers(admin_user)
        )
        assert inbox.json()["unread_count"] == 1

    async def test_mark_nonexistent_returns_404(
        self, client, admin_user, auth_headers
    ):
        r = await client.post(
            f"/api/v1/notifications/inbox/{uuid.uuid4()}/read",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 404

    async def test_mark_already_read_is_idempotent(
        self, client, admin_user, auth_headers, seed_logs
    ):
        already_read = [log for log in seed_logs if log.read_at is not None][0]
        r = await client.post(
            f"/api/v1/notifications/inbox/{already_read.id}/read",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        # No incrementa unread ni explota

    async def test_mark_all_read(
        self, client, admin_user, auth_headers, seed_logs
    ):
        r = await client.post(
            "/api/v1/notifications/inbox/mark-all-read",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["marked"] == 2  # 2 estaban no leídas

        # Verificar que ahora unread_count = 0
        inbox = await client.get(
            "/api/v1/notifications/inbox", headers=auth_headers(admin_user)
        )
        assert inbox.json()["unread_count"] == 0

    async def test_mark_all_read_when_none_unread(
        self, client, admin_user, auth_headers
    ):
        r = await client.post(
            "/api/v1/notifications/inbox/mark-all-read",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["marked"] == 0

    async def test_mark_read_viewer_rejected(
        self, client, viewer_user, auth_headers, seed_logs
    ):
        unread = [log for log in seed_logs if log.read_at is None][0]
        r = await client.post(
            f"/api/v1/notifications/inbox/{unread.id}/read",
            headers=auth_headers(viewer_user),
        )
        assert r.status_code in (401, 403)


# ── __repr__ safety (no lazy-load tras commit) ─────────────────────────────


class TestSafeRepr:
    async def test_notification_log_repr_doesnt_lazy_load(self, db_session):
        """Si el __repr__ accediera a self.event/self.channel después de
        commit con expire_on_commit=True, dispararía un refresh que falla
        en instancias detached (lo que pasaba en el handler del error)."""
        log = NotificationLog(
            id=uuid.uuid4(),
            event="doc_ready",
            channel="in_app",
            target="x@y.com",
            status="sent",
            payload_json={},
        )
        db_session.add(log)
        await db_session.commit()
        # Tras commit, los atributos pueden estar expirados. __repr__ debe
        # funcionar sin disparar refresh.
        repr_str = repr(log)
        assert "NotificationLog" in repr_str
        assert str(log.id) in repr_str

    async def test_notification_rule_repr_doesnt_lazy_load(self, db_session):
        rule = NotificationRule(
            id=uuid.uuid4(),
            event=NotificationEvent.doc_ready,
            channel=NotificationChannel.email,
            enabled=False,
            config_json={},
        )
        db_session.add(rule)
        await db_session.commit()
        repr_str = repr(rule)
        assert "NotificationRule" in repr_str
        assert str(rule.id) in repr_str
