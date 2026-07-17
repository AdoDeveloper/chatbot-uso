from __future__ import annotations



class TestAnalyticsDashboard:
    async def test_dashboard_requires_auth(self, client):
        r = await client.get("/api/v1/analytics/dashboard")
        assert r.status_code == 401

    async def test_dashboard_returns_metrics(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/dashboard",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert "queries_today" in body
        assert "resolution_rate" in body


class TestAnalyticsTimeSeries:
    async def test_timeseries_requires_auth(self, client):
        r = await client.get("/api/v1/analytics/timeseries")
        assert r.status_code == 401

    async def test_timeseries_returns_data(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/timeseries",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert "points" in body
        assert isinstance(body["points"], list)


class TestAnalyticsTopics:
    async def test_topics_requires_auth(self, client):
        r = await client.get("/api/v1/analytics/topics")
        assert r.status_code == 401

    async def test_topics_returns_data(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/topics",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200


class TestAnalyticsHeatmap:
    async def test_heatmap_requires_auth(self, client):
        r = await client.get("/api/v1/analytics/heatmap")
        assert r.status_code == 401

    async def test_heatmap_returns_data(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/heatmap",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        body = r.json()
        assert "cells" in body
        assert isinstance(body["cells"], list)
