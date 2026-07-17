from __future__ import annotations



class TestLiveness:
    async def test_liveness_returns_ok(self, client):
        r = await client.get("/api/v1/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_liveness_no_auth_required(self, client):
        r = await client.get("/api/v1/health/live")
        assert r.status_code == 200


class TestReadiness:
    async def test_readiness_checks_dependencies(self, client):
        r = await client.get("/api/v1/health/ready")
        assert r.status_code in (200, 503)
        body = r.json()
        assert "checks" in body
        assert "mysql" in body["checks"]
        assert "redis" in body["checks"]


class TestDetailed:
    async def test_detailed_requires_auth(self, client):
        r = await client.get("/api/v1/health/detailed")
        assert r.status_code == 401

    async def test_detailed_returns_services(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/health/detailed",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert "services" in body
        assert "version" in body
        assert body["environment"] in ("development", "staging", "production")


class TestSnapshot:
    async def test_snapshot_requires_auth(self, client):
        r = await client.post("/api/v1/health/snapshot")
        assert r.status_code == 401

    async def test_snapshot_collects_and_returns(self, client, admin_user, auth_headers, db_session):
        r = await client.post(
            "/api/v1/health/snapshot",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert "services" in body
        assert len(body["services"]) > 0


class TestHistory:
    async def test_history_requires_auth(self, client):
        r = await client.get("/api/v1/health/history")
        assert r.status_code == 401

    async def test_history_returns_list(self, client, admin_user, auth_headers, db_session):
        r = await client.get(
            "/api/v1/health/history",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestUptime:
    async def test_uptime_requires_auth(self, client):
        r = await client.get("/api/v1/health/uptime")
        assert r.status_code == 401

    async def test_uptime_returns_summary(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/health/uptime",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestIncidents:
    async def test_incidents_requires_auth(self, client):
        r = await client.get("/api/v1/health/incidents")
        assert r.status_code == 401

    async def test_incidents_returns_list(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/health/incidents",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)
