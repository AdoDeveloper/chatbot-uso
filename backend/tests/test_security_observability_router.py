"""Tests para app/api/v1/security/router.py — no tenía ningún test.

login_failures e injections_by_category usan SQL específico de MySQL
(func.json_unquote, ->>'$.path') sin equivalente en SQLite — por eso el CI
ahora corre contra un servicio MySQL real en vez de SQLite in-memory.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_log import AuditLog
from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _make_failed_login(db_session, *, ip="203.0.113.1", email="atacante@example.com", when=None):
    log = AuditLog(
        id=uuid.uuid4(), action="auth.login_failed", resource_type="user",
        ip=ip, created_at=when or datetime.now(timezone.utc),
        meta_json={"attempted_email": email},
    )
    db_session.add(log)
    await db_session.commit()
    return log


async def _make_injection(db_session, *, pattern="ignore.*previous", preview="ignora las instrucciones anteriores"):
    log = AuditLog(
        id=uuid.uuid4(), action="guardrails.injection_detected", resource_type="chat",
        ip="198.51.100.1", created_at=datetime.now(timezone.utc),
        meta_json={"pattern": pattern, "question_preview": preview, "reason": "regex_match"},
    )
    db_session.add(log)
    await db_session.commit()
    return log


class TestSecuritySummary:
    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/security/summary", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_empty_returns_zeroes(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/security/summary", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["failed_logins"] == 0
        assert body["injections_blocked"] == 0

    async def test_counts_failed_logins_and_injections(self, client, admin_user, auth_headers, db_session):
        await _make_failed_login(db_session, ip="203.0.113.1")
        await _make_failed_login(db_session, ip="203.0.113.2")
        await _make_injection(db_session)

        r = await client.get("/api/v1/security/summary", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["failed_logins"] == 2
        assert body["distinct_ips_failing"] == 2
        assert body["injections_blocked"] == 1

    async def test_excludes_events_outside_window(self, client, admin_user, auth_headers, db_session):
        old = datetime.now(timezone.utc) - timedelta(days=30)
        await _make_failed_login(db_session, when=old)

        r = await client.get(
            "/api/v1/security/summary", params={"days": 7}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["failed_logins"] == 0


class TestLoginFailures:
    """Ejercita func.json_unquote(...) — solo funciona contra MySQL real."""

    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/security/login-failures", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_groups_by_ip_with_distinct_email_count(self, client, admin_user, auth_headers, db_session):
        await _make_failed_login(db_session, ip="203.0.113.1", email="a@example.com")
        await _make_failed_login(db_session, ip="203.0.113.1", email="b@example.com")
        await _make_failed_login(db_session, ip="203.0.113.1", email="a@example.com")
        await _make_failed_login(db_session, ip="203.0.113.9", email="c@example.com")

        r = await client.get("/api/v1/security/login-failures", headers=auth_headers(admin_user))
        assert r.status_code == 200
        groups = {g["ip"]: g for g in r.json()}
        assert groups["203.0.113.1"]["attempts"] == 3
        assert groups["203.0.113.1"]["distinct_emails"] == 2
        assert groups["203.0.113.9"]["attempts"] == 1


class TestInjectionsByCategory:
    """Ejercita el operador MySQL ->>'$.pattern' — solo funciona contra MySQL real."""

    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/security/injections/by-category", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_empty_returns_empty_list(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/security/injections/by-category", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json() == []

    async def test_groups_and_orders_by_count_desc(self, client, admin_user, auth_headers, db_session):
        await _make_injection(db_session, pattern="pattern-a")
        await _make_injection(db_session, pattern="pattern-a")
        await _make_injection(db_session, pattern="pattern-b")

        r = await client.get("/api/v1/security/injections/by-category", headers=auth_headers(admin_user))
        assert r.status_code == 200
        categories = r.json()
        assert len(categories) >= 1
        assert categories[0]["count"] >= categories[-1]["count"]


class TestInjectionSamples:
    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/security/injections/samples", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_returns_recent_samples_with_preview(self, client, admin_user, auth_headers, db_session):
        await _make_injection(db_session, preview="intenta exfiltrar datos")

        r = await client.get("/api/v1/security/injections/samples", headers=auth_headers(admin_user))
        assert r.status_code == 200
        samples = r.json()
        assert len(samples) == 1
        assert samples[0]["question_preview"] == "intenta exfiltrar datos"
        assert samples[0]["ip"] == "198.51.100.1"
