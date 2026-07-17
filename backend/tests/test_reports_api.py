from __future__ import annotations

from datetime import date, timedelta

REPORT_TYPES = ("ejecutivo", "uso", "escalamientos", "conocimiento")


def _range(days: int = 30) -> str:
    hoy = date.today()
    desde = hoy - timedelta(days=days - 1)
    return f"date_from={desde.isoformat()}&date_to={hoy.isoformat()}"


class TestReportsAuth:
    async def test_requires_auth(self, client):
        r = await client.post(f"/api/v1/analytics/reports?report_type=ejecutivo&{_range()}")
        assert r.status_code == 401


class TestReportsGeneration:
    async def test_all_types_return_pdf(self, client, admin_user, auth_headers):
        headers = auth_headers(admin_user)
        for rtype in REPORT_TYPES:
            r = await client.post(
                f"/api/v1/analytics/reports?report_type={rtype}&{_range()}",
                headers=headers,
            )
            assert r.status_code == 200, f"{rtype}: {r.status_code} {r.text[:200]}"
            assert r.headers["content-type"] == "application/pdf"
            assert r.content.startswith(b"%PDF")

    async def test_banned_wording_absent(self, client, admin_user, auth_headers):
        r = await client.post(
            f"/api/v1/analytics/reports?report_type=ejecutivo&{_range()}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert "Asistente virtual institucional".encode() not in r.content


class TestReportsValidation:
    async def test_inverted_range_is_rejected(self, client, admin_user, auth_headers):
        hoy = date.today()
        r = await client.post(
            f"/api/v1/analytics/reports?report_type=uso"
            f"&date_from={hoy.isoformat()}&date_to={(hoy - timedelta(days=5)).isoformat()}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_range_over_a_year_is_rejected(self, client, admin_user, auth_headers):
        hoy = date.today()
        r = await client.post(
            f"/api/v1/analytics/reports?report_type=uso"
            f"&date_from={(hoy - timedelta(days=400)).isoformat()}&date_to={hoy.isoformat()}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_unknown_type_is_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            f"/api/v1/analytics/reports?report_type=inexistente&{_range()}",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422
