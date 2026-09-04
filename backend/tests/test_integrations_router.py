"""Tests para app/api/v1/integrations/router.py.

El router expone la configuracion de SMTP y OAuth, de modo que las pruebas
fijan dos garantias: que las respuestas describen el estado con banderas y
nunca devuelven la contrasena ni el secreto, y que solo escribe quien tiene
permiso de actualizacion.
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


@pytest.fixture
async def editor_user(make_user):
    return await make_user(role=UserRole.editor)


class TestGetSMTP:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/integrations/smtp")
        assert r.status_code in (401, 403)

    async def test_returns_state_without_the_password(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.core.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "SMTP_HOST", "smtp.example.com", raising=False)
        monkeypatch.setattr(s, "SMTP_USER", "buzon@example.com", raising=False)
        monkeypatch.setattr(s, "SMTP_PASSWORD", "secreto-no-publicable", raising=False)

        r = await client.get("/api/v1/integrations/smtp", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert "password" not in body
        assert "secreto-no-publicable" not in r.text

    async def test_reports_not_configured_without_password(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.core.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "SMTP_HOST", "smtp.example.com", raising=False)
        monkeypatch.setattr(s, "SMTP_USER", "buzon@example.com", raising=False)
        monkeypatch.setattr(s, "SMTP_PASSWORD", "", raising=False)

        r = await client.get("/api/v1/integrations/smtp", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["configured"] is False


class TestAuthMethods:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/integrations/auth-methods")
        assert r.status_code in (401, 403)

    async def test_defaults_to_enabled(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/integrations/auth-methods", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["credentials_enabled"] is True

    async def test_editor_cannot_update(self, client, editor_user, auth_headers):
        r = await client.put(
            "/api/v1/integrations/auth-methods",
            json={"credentials_enabled": False},
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_update_persists(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/integrations/auth-methods",
            json={"credentials_enabled": False},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["credentials_enabled"] is False

        again = await client.get(
            "/api/v1/integrations/auth-methods", headers=auth_headers(admin_user)
        )
        assert again.json()["credentials_enabled"] is False


class TestOAuth:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/integrations/oauth")
        assert r.status_code in (401, 403)

    async def test_returns_flags_without_the_secret(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.core.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "MICROSOFT_CLIENT_ID", "id-publico", raising=False)
        monkeypatch.setattr(s, "MICROSOFT_CLIENT_SECRET", "secreto-no-publicable", raising=False)
        monkeypatch.setattr(s, "MICROSOFT_TENANT_ID", "tenant-1", raising=False)

        r = await client.get("/api/v1/integrations/oauth", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["has_client_secret"] is True
        assert body["configured"] is True
        assert "client_secret" not in body
        assert "secreto-no-publicable" not in r.text

    async def test_editor_cannot_update(self, client, editor_user, auth_headers):
        r = await client.put(
            "/api/v1/integrations/oauth",
            json={"allowed_domains": ["example.com"], "is_active": True},
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_update_persists_domains(self, client, admin_user, auth_headers):
        r = await client.put(
            "/api/v1/integrations/oauth",
            json={"allowed_domains": ["udesonsonate.edu.sv"], "is_active": True},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["allowed_domains"] == ["udesonsonate.edu.sv"]

        again = await client.get("/api/v1/integrations/oauth", headers=auth_headers(admin_user))
        assert again.json()["allowed_domains"] == ["udesonsonate.edu.sv"]
        assert again.json()["is_active"] is True


class TestSMTPTest:
    async def test_requires_auth(self, client):
        r = await client.post("/api/v1/integrations/smtp/test", json={"to": "a@example.com"})
        assert r.status_code in (401, 403)

    async def test_editor_cannot_send(self, client, editor_user, auth_headers):
        r = await client.post(
            "/api/v1/integrations/smtp/test",
            json={"to": "a@example.com"},
            headers=auth_headers(editor_user),
        )
        assert r.status_code == 403

    async def test_rejects_a_malformed_recipient(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/integrations/smtp/test",
            json={"to": "no-es-un-correo"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 422

    async def test_reports_when_smtp_is_not_configured(
        self, client, admin_user, auth_headers, monkeypatch
    ):
        from app.services.notifications import smtp

        async def _sin_config():
            return None

        monkeypatch.setattr(smtp, "get_smtp_config", _sin_config)

        r = await client.post(
            "/api/v1/integrations/smtp/test",
            json={"to": "destino@example.com"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["success"] is False

    async def test_is_rate_limited(self, client, admin_user, auth_headers, monkeypatch):
        """El destinatario es libre: el ritmo de envio debe estar acotado."""
        from app.services.notifications import smtp

        async def _sin_config():
            return None

        monkeypatch.setattr(smtp, "get_smtp_config", _sin_config)

        codigos = []
        for _ in range(7):
            r = await client.post(
                "/api/v1/integrations/smtp/test",
                json={"to": "destino@example.com"},
                headers=auth_headers(admin_user),
            )
            codigos.append(r.status_code)

        assert 429 in codigos
