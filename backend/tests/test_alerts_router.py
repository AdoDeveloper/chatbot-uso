"""Tests para app/api/v1/system/alerts/router.py — no tenía ningún test.

Cubre POST /api/v1/alerts/run: auth, permiso system.manage, caso sin nada que
disparar, y los dos checks reales (service_down, rate_limit_threshold)
disparando de punta a punta contra la BD (sin mockear run_all_checks).

app/services/monitoring/alerts.py hace `from app.core.redis import get_redis`
(import directo) igual que semantic_cache.py — el fixture `client` parchea
`app.core.redis.get_redis`, pero ese binding ya quedó resuelto al importar el
módulo. Reapuntamos alerts.get_redis al mismo get_redis ya parcheado para que
el cooldown use el mismo FakeRedis que el resto del test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import NotificationChannel, NotificationEvent, UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


@pytest.fixture(autouse=True)
def _patch_alerts_svc_redis(client, monkeypatch):
    from app.core import redis as redis_mod
    from app.services.monitoring import alerts as alerts_svc

    monkeypatch.setattr(alerts_svc, "get_redis", redis_mod.get_redis)


async def _add_snapshot(db_session, *, service: str, is_ok: bool, recorded_at, error: str | None = None):
    from app.models.health_snapshot import HealthSnapshot

    snap = HealthSnapshot(
        service_name=service,
        is_ok=is_ok,
        recorded_at=recorded_at,
        error=error,
    )
    db_session.add(snap)
    await db_session.commit()
    return snap


async def _enable_rule(db_session, *, event: NotificationEvent, channel: NotificationChannel = NotificationChannel.in_app):
    from app.models.notification_rule import NotificationRule

    rule = NotificationRule(event=event, channel=channel, enabled=True)
    db_session.add(rule)
    await db_session.commit()
    return rule


async def _make_conversation(db_session):
    from app.models.chat_conversation import ChatConversation

    conv = ChatConversation(session_id="sess-alerts-test")
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


class TestRunProactiveChecks:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/alerts/run")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.post("/api/v1/alerts/run", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_zero_counts_when_nothing_to_check(self, client, admin_user, auth_headers):
        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["fired_by_check"] == {
            "service_down": 0,
            "rate_limit_threshold": 0,
        }
        assert body["total_fired"] == 0

    async def test_service_down_fires_when_last_two_snapshots_failed(
        self, client, admin_user, auth_headers, db_session,
    ):
        now = datetime.now(timezone.utc)
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now - timedelta(minutes=1), error="timeout")
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now, error="timeout")
        await _enable_rule(db_session, event=NotificationEvent.service_down)

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["fired_by_check"]["service_down"] == 1
        assert body["total_fired"] == 1

    async def test_service_down_does_not_fire_when_last_snapshot_is_ok(
        self, client, admin_user, auth_headers, db_session,
    ):
        now = datetime.now(timezone.utc)
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now - timedelta(minutes=1), error="timeout")
        await _add_snapshot(db_session, service="qdrant", is_ok=True, recorded_at=now)
        await _enable_rule(db_session, event=NotificationEvent.service_down)

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["fired_by_check"]["service_down"] == 0

    async def test_service_down_does_not_fire_with_only_one_snapshot(
        self, client, admin_user, auth_headers, db_session,
    ):
        now = datetime.now(timezone.utc)
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now, error="timeout")
        await _enable_rule(db_session, event=NotificationEvent.service_down)

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["fired_by_check"]["service_down"] == 0

    async def test_service_down_respects_cooldown_on_second_run(
        self, client, admin_user, auth_headers, db_session,
    ):
        now = datetime.now(timezone.utc)
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now - timedelta(minutes=1), error="timeout")
        await _add_snapshot(db_session, service="qdrant", is_ok=False, recorded_at=now, error="timeout")
        await _enable_rule(db_session, event=NotificationEvent.service_down)

        r1 = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r1.json()["fired_by_check"]["service_down"] == 1

        r2 = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r2.json()["fired_by_check"]["service_down"] == 0

    async def test_rate_limit_threshold_fires_when_usage_over_ratio(
        self, client, admin_user, auth_headers, db_session,
    ):
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        r_upd = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 10, "chat_per_hour": 10},
            headers=auth_headers(admin_user),
        )
        assert r_upd.status_code == 200

        await _enable_rule(db_session, event=NotificationEvent.rate_limit_threshold)
        conv = await _make_conversation(db_session)

        now = datetime.now(timezone.utc)
        for _ in range(9):
            db_session.add(ChatMessage(conversation_id=conv.id, role=MessageRole.user, content="hola", created_at=now))
        await db_session.commit()

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["fired_by_check"]["rate_limit_threshold"] == 1
        assert body["total_fired"] == 1

    async def test_rate_limit_threshold_does_not_fire_when_under_ratio(
        self, client, admin_user, auth_headers, db_session,
    ):
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        r_upd = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 10, "chat_per_hour": 100},
            headers=auth_headers(admin_user),
        )
        assert r_upd.status_code == 200

        await _enable_rule(db_session, event=NotificationEvent.rate_limit_threshold)
        conv = await _make_conversation(db_session)

        now = datetime.now(timezone.utc)
        db_session.add(ChatMessage(conversation_id=conv.id, role=MessageRole.user, content="hola", created_at=now))
        await db_session.commit()

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["fired_by_check"]["rate_limit_threshold"] == 0

    async def test_rate_limit_threshold_disabled_when_limit_not_configured(
        self, client, admin_user, auth_headers, db_session,
    ):
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole
        from app.models.global_setting import GlobalSetting
        from app.services.system.settings import invalidate_runtime_overrides

        await db_session.merge(GlobalSetting(key="rate_limit_chat_per_hour", value=0))
        await db_session.commit()
        invalidate_runtime_overrides()

        conv = await _make_conversation(db_session)
        now = datetime.now(timezone.utc)
        for _ in range(50):
            db_session.add(ChatMessage(conversation_id=conv.id, role=MessageRole.user, content="hola", created_at=now))
        await db_session.commit()

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["fired_by_check"]["rate_limit_threshold"] == 0

    async def test_both_checks_can_fire_in_same_run(
        self, client, admin_user, auth_headers, db_session,
    ):
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        now = datetime.now(timezone.utc)
        await _add_snapshot(db_session, service="redis", is_ok=False, recorded_at=now - timedelta(minutes=1), error="conn refused")
        await _add_snapshot(db_session, service="redis", is_ok=False, recorded_at=now, error="conn refused")
        await _enable_rule(db_session, event=NotificationEvent.service_down)

        await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 10, "chat_per_hour": 10},
            headers=auth_headers(admin_user),
        )
        await _enable_rule(db_session, event=NotificationEvent.rate_limit_threshold)
        conv = await _make_conversation(db_session)

        for _ in range(9):
            db_session.add(ChatMessage(conversation_id=conv.id, role=MessageRole.user, content="hola", created_at=now))
        await db_session.commit()

        r = await client.post("/api/v1/alerts/run", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["fired_by_check"]["service_down"] == 1
        assert body["fired_by_check"]["rate_limit_threshold"] == 1
        assert body["total_fired"] == 2
