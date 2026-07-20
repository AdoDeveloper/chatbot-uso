"""Tests para app/api/v1/system/rate_limits/router.py — no tenía ningún test.

Cubre config (get/patch), listado de IPs limitadas, reset de IP y el reporte
de uso (usage). Usa el Redis fake (fakeredis) inyectado por el fixture
`client` para poblar contadores reales vía app.core.rate_limit, sin mockear
los endpoints. RBAC real vía require_perm: viewer sin permiso recibe 403 real.
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _bump_counter(client_fixture, key: str, count: int, window_seconds: int) -> None:
    """Incrementa un contador de rate-limit real en el Redis fake usado por el cliente."""
    from app.core import redis as redis_mod

    redis = redis_mod.get_redis()
    for _ in range(count):
        await redis.incr(key)
    await redis.expire(key, window_seconds)


class TestGetConfig:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/rate-limits/config")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        # viewer no tiene system.read por defecto en el seed RBAC.
        r = await client.get("/api/v1/rate-limits/config", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_defaults(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rate-limits/config", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["chat_per_min"] == 10
        assert body["chat_per_hour"] == 100


class TestUpdateConfig:
    async def test_requires_auth(self, client):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 20, "chat_per_hour": 200},
        )
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 20, "chat_per_hour": 200},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_updates_persist_and_are_reflected_in_get(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 25, "chat_per_hour": 500},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        got = await client.get("/api/v1/rate-limits/config", headers=auth_headers(admin_user))
        assert got.status_code == 200
        body = got.json()
        assert body["chat_per_min"] == 25
        assert body["chat_per_hour"] == 500

    async def test_rejects_chat_per_min_below_minimum(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 0, "chat_per_hour": 100},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_chat_per_min_above_maximum(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 1001, "chat_per_hour": 100},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_chat_per_hour_above_maximum(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 10, "chat_per_hour": 100001},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_missing_fields(self, client, admin_user, auth_headers):
        r = await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 10},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422


class TestListThrottled:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/rate-limits/throttled")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_empty_list_when_no_activity(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_returns_ip_near_per_min_limit(self, client, admin_user, auth_headers):
        # Default chat_per_min=10 -> threshold = 10 // 2 = 5.
        await _bump_counter(client, "rl:chat:min:1.2.3.4:60", count=6, window_seconds=60)

        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["ip"] == "1.2.3.4"
        assert body[0]["current_count"] == 6
        assert body[0]["limit"] == 10
        assert body[0]["window"] == "per_min"
        assert body[0]["ttl_seconds"] >= 0

    async def test_does_not_return_ip_below_threshold(self, client, admin_user, auth_headers):
        # threshold = 5; con conteo 2 no debe aparecer.
        await _bump_counter(client, "rl:chat:min:9.9.9.9:60", count=2, window_seconds=60)

        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_returns_ip_near_per_hour_limit(self, client, admin_user, auth_headers):
        # Default chat_per_hour=100 -> threshold = 50.
        await _bump_counter(client, "rl:chat:hour:5.6.7.8:3600", count=60, window_seconds=3600)

        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["ip"] == "5.6.7.8"
        assert body[0]["window"] == "per_hour"
        assert body[0]["limit"] == 100

    async def test_reflects_updated_config_limits(self, client, admin_user, auth_headers):
        # Con un límite per_min menor, el mismo conteo debe superar el threshold.
        await client.patch(
            "/api/v1/rate-limits/config",
            json={"chat_per_min": 4, "chat_per_hour": 100},
            headers=auth_headers(admin_user),
        )
        await _bump_counter(client, "rl:chat:min:2.2.2.2:60", count=3, window_seconds=60)

        r = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["limit"] == 4


class TestUnblockIp:
    async def test_requires_auth(self, client):
        r = await client.delete("/api/v1/rate-limits/reset/1.2.3.4")
        assert r.status_code == 401

    async def test_requires_manage_perm(self, client, viewer_user, auth_headers):
        r = await client.delete(
            "/api/v1/rate-limits/reset/1.2.3.4", headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_clears_counters_for_ip(self, client, admin_user, auth_headers):
        await _bump_counter(client, "rl:chat:min:8.8.8.8:60", count=6, window_seconds=60)

        listed = await client.get("/api/v1/rate-limits/throttled", headers=auth_headers(admin_user))
        assert len(listed.json()) == 1

        r = await client.delete(
            "/api/v1/rate-limits/reset/8.8.8.8", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        listed_after = await client.get(
            "/api/v1/rate-limits/throttled", headers=auth_headers(admin_user),
        )
        assert listed_after.json() == []

    async def test_reset_of_ip_with_no_activity_is_a_noop_success(self, client, admin_user, auth_headers):
        r = await client.delete(
            "/api/v1/rate-limits/reset/0.0.0.0", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_does_not_clear_counters_for_other_ips(self, client, admin_user, auth_headers):
        await _bump_counter(client, "rl:chat:min:1.1.1.1:60", count=6, window_seconds=60)
        await _bump_counter(client, "rl:chat:min:2.2.2.2:60", count=6, window_seconds=60)

        r = await client.delete(
            "/api/v1/rate-limits/reset/1.1.1.1", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        listed = await client.get(
            "/api/v1/rate-limits/throttled", headers=auth_headers(admin_user),
        )
        ips = [row["ip"] for row in listed.json()]
        assert ips == ["2.2.2.2"]


class TestUsageReport:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/rate-limits/usage")
        assert r.status_code == 401

    async def test_requires_read_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/rate-limits/usage", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_empty_report_when_no_data(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rate-limits/usage", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["hours"] == 24
        assert body["limit_per_min"] == 10
        assert body["limit_per_hour"] == 100
        assert body["total_requests"] == 0
        assert body["total_throttles"] == 0
        assert body["points"] == []

    async def test_counts_user_chat_messages_as_requests(self, client, admin_user, auth_headers, db_session):
        import uuid as uuid_mod

        from app.models.chat_conversation import ChatConversation
        from app.models.chat_message import ChatMessage
        from app.models.enums import MessageRole

        conversation = ChatConversation(session_id=f"sess-{uuid_mod.uuid4().hex[:8]}", user_id=admin_user.id)
        db_session.add(conversation)
        await db_session.commit()
        await db_session.refresh(conversation)

        db_session.add(ChatMessage(conversation_id=conversation.id, role=MessageRole.user, content="hola"))
        db_session.add(ChatMessage(conversation_id=conversation.id, role=MessageRole.assistant, content="hola de vuelta"))
        await db_session.commit()

        r = await client.get("/api/v1/rate-limits/usage", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        # Solo el mensaje con role=user cuenta como request.
        assert body["total_requests"] == 1
        assert len(body["points"]) == 1

    async def test_counts_rate_limit_events_as_throttles(self, client, admin_user, auth_headers, db_session):
        from app.models.rate_limit_event import RateLimitEvent

        db_session.add(RateLimitEvent(
            dimension="chat:min",
            identifier="3.3.3.3",
            identifier_type="ip",
            limit_value=10,
            retry_after_seconds=30,
        ))
        await db_session.commit()

        r = await client.get("/api/v1/rate-limits/usage", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total_throttles"] == 1
        assert len(body["points"]) == 1
        assert body["points"][0]["throttles"] == 1

    async def test_rejects_hours_below_minimum(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/rate-limits/usage?hours=0", headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_rejects_hours_above_maximum(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/rate-limits/usage?hours=169", headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_accepts_custom_hours_window(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/rate-limits/usage?hours=48", headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["hours"] == 48

    async def test_accepts_explicit_date_range(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/rate-limits/usage"
            "?date_from=2020-01-01T00:00:00&date_to=2020-01-02T00:00:00",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total_requests"] == 0
        assert body["total_throttles"] == 0
