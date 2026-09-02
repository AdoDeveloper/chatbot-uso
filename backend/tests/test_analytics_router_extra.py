"""Tests para los endpoints de app/api/v1/analytics/router.py sin cobertura.

/dashboard, /topics, /heatmap, /timeseries y /timeline ya tienen tests
dedicados (test_analytics_api.py, test_analytics_timeline.py). Este archivo
cubre el resto: son capas finas (auth + query params -> svc.get_*), así que
se verifican con un smoke test paramétrico (401 sin auth, 200 con estructura
esperada) en vez de un test dedicado por endpoint - la lógica de agregación
real vive en app/services/monitoring/analytics.py, no en el router.
"""
from __future__ import annotations

import pytest

import uuid

from app.models.chat_conversation import ChatConversation
from app.models.enums import ConversationStatus, UserRole

# (ruta, campo esperado en la respuesta) para cada endpoint GET simple.
_SIMPLE_ENDPOINTS = [
    ("/api/v1/analytics/routes", "routes"),
    ("/api/v1/analytics/latency/timeseries", "points"),
    ("/api/v1/analytics/sources/quality", "sources"),
    ("/api/v1/analytics/comparison", "current"),
    ("/api/v1/analytics/channels", "channels"),
    ("/api/v1/analytics/pages", "pages"),
    ("/api/v1/analytics/feedback", "summary"),
    ("/api/v1/analytics/cache", "hit_rate"),
    ("/api/v1/analytics/csat", "distribution"),
]


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


class TestAnalyticsSimpleEndpointsRequireAuth:
    @pytest.mark.parametrize("path,_field", _SIMPLE_ENDPOINTS)
    async def test_requires_auth(self, client, path, _field):
        r = await client.get(path)
        assert r.status_code == 401, path


class TestAnalyticsSimpleEndpointsReturnData:
    @pytest.mark.parametrize("path,field", _SIMPLE_ENDPOINTS)
    async def test_returns_expected_shape(self, client, admin_user, auth_headers, path, field):
        r = await client.get(path, headers=auth_headers(admin_user))
        assert r.status_code == 200, (path, r.text)
        assert field in r.json(), (path, r.json())


class TestCsatAggregation:

    async def test_aggregates_real_csat_scores(self, client, admin_user, auth_headers, db_session):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        convs = [
            ChatConversation(
                id=uuid.uuid4(), session_id=str(uuid.uuid4()),
                status=ConversationStatus.resolved, csat_score=score, created_at=now,
            )
            for score in (4, 4, 2)
        ]
        db_session.add_all(convs)
        await db_session.commit()

        r = await client.get("/api/v1/analytics/csat?days=30", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert body["distribution"]["4"] == 2
        assert body["distribution"]["2"] == 1
        assert body["avg_score"] == round((4 + 4 + 2) / 3, 2)

    async def test_excludes_conversations_outside_date_range(self, client, admin_user, auth_headers, db_session):
        from datetime import datetime, timedelta, timezone

        old = datetime.now(timezone.utc) - timedelta(days=60)
        conv = ChatConversation(
            id=uuid.uuid4(), session_id=str(uuid.uuid4()),
            status=ConversationStatus.resolved, csat_score=5, created_at=old,
        )
        db_session.add(conv)
        await db_session.commit()

        r = await client.get("/api/v1/analytics/csat?days=30", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["total"] == 0


class TestEffectiveDaysDateRange:
    """El resto de endpoints ya prueba el caso `days=N`; este cubre el otro
    modo de la misma función interna (_effective_days): date_from/date_to
    explícitos en vez de un entero de días."""

    async def test_topics_with_explicit_date_range(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/topics",
            params={"date_from": "2026-01-01T00:00:00Z", "date_to": "2026-01-07T00:00:00Z"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

    async def test_topics_date_from_without_date_to_uses_now(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/analytics/topics",
            params={"date_from": "2026-01-01T00:00:00Z"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200


class TestAnalyticsExport:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/analytics/export", json={"rows": []})
        assert r.status_code == 401

    async def test_export_xlsx_returns_file(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/analytics/export",
            params={"format": "xlsx"},
            json={"rows": [{"Métrica": "Consultas", "Valor": 10}]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert "spreadsheet" in r.headers["content-type"]

    async def test_export_pdf_returns_file(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/analytics/export",
            params={"format": "pdf"},
            json={"rows": [{"Métrica": "Consultas", "Valor": 10}]},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert "pdf" in r.headers["content-type"]


class TestGenerateReport:
    _params = {"report_type": "ejecutivo", "date_from": "2026-01-01", "date_to": "2026-01-07"}

    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/analytics/reports", params=self._params)
        assert r.status_code == 401

    async def test_generates_pdf(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/analytics/reports", params=self._params, headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert "pdf" in r.headers["content-type"]

    async def test_inverted_date_range_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/analytics/reports",
            params={"report_type": "ejecutivo", "date_from": "2026-01-07", "date_to": "2026-01-01"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_range_over_a_year_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/analytics/reports",
            params={"report_type": "ejecutivo", "date_from": "2024-01-01", "date_to": "2026-06-01"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422
