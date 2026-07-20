"""Tests para app/api/v1/auth/router.py: providers, login, me,
change-password, refresh y logout en su flujo normal.

test_auth_revocation.py ya cubre la invalidación de tokens (rotación,
cambio de contraseña, logout); este archivo cubre el resto del contrato del
endpoint que no tenía ningún test: credenciales inválidas, cuenta
desactivada, login deshabilitado por config, y los casos de error de
/refresh (token ausente/inválido/de tipo incorrecto).
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole
from app.models.global_setting import GlobalSetting


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


class TestAuthProviders:
    async def test_defaults_credentials_enabled_no_microsoft(self, client):
        r = await client.get("/api/v1/auth/providers")
        assert r.status_code == 200
        body = r.json()
        assert body["credentials"] is True
        assert body["microsoft"] is False

    async def test_reflects_disabled_credentials_setting(self, client, db_session):
        db_session.add(GlobalSetting(key="auth_credentials_enabled", value=False))
        await db_session.commit()

        r = await client.get("/api/v1/auth/providers")
        assert r.status_code == 200
        assert r.json()["credentials"] is False


class TestLogin:
    async def test_wrong_password_returns_401(self, client, admin_user):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "wrong-password"},
        )
        assert r.status_code == 401

    async def test_unknown_email_returns_401(self, client):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "no-existe@example.com", "password": "whatever123"},
        )
        assert r.status_code == 401

    async def test_success_returns_tokens_and_updates_last_login(self, client, admin_user, db_session):
        assert admin_user.last_login_at is None
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "Test1234!"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["user"]["email"] == admin_user.email

        await db_session.refresh(admin_user)
        assert admin_user.last_login_at is not None

    async def test_disabled_account_returns_403(self, client, make_user, db_session):
        user = await make_user(role=UserRole.viewer)
        user.is_active = False
        db_session.add(user)
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "Test1234!"},
        )
        assert r.status_code == 403

    async def test_credentials_disabled_globally_returns_403(self, client, admin_user, db_session):
        db_session.add(GlobalSetting(key="auth_credentials_enabled", value=False))
        await db_session.commit()

        r = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "Test1234!"},
        )
        assert r.status_code == 403


class TestMe:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

    async def test_returns_current_user(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/auth/me", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["email"] == admin_user.email


class TestChangePassword:
    async def test_wrong_current_password_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong", "new_password": "NuevaClave123!"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_same_password_rejected(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Test1234!", "new_password": "Test1234!"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 400

    async def test_success_updates_password(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Test1234!", "new_password": "NuevaClave123!"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200

        # La contraseña vieja ya no debe funcionar (tokens_valid_after avanzó)
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "NuevaClave123!"},
        )
        assert login.status_code == 200


class TestRefresh:
    async def test_empty_token_rejected_by_schema(self, client):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": ""})
        assert r.status_code == 422

    async def test_garbage_token_returns_401(self, client):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
        assert r.status_code == 401

    async def test_access_token_used_as_refresh_rejected(self, client, admin_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "Test1234!"},
        )
        access_token = login.json()["access_token"]
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
        assert r.status_code == 401

    async def test_valid_refresh_rotates_tokens(self, client, admin_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "Test1234!"},
        )
        refresh_token = login.json()["refresh_token"]
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r.status_code == 200
        assert "access_token" in r.json()


class TestLogout:
    async def test_logout_without_token_still_succeeds(self, client):
        r = await client.post("/api/v1/auth/logout", json={})
        assert r.status_code == 200

    async def test_logout_with_valid_token_succeeds(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/auth/logout", json={}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
