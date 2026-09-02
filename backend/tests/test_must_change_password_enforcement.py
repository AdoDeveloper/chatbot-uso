"""must_change_password solo se aplicaba en el frontend (redirect tras leer
el flag del login): un cliente HTTP directo con una contraseña temporal
podía usar el access token para llamar cualquier endpoint protegido sin
jamás cambiarla. require_permission ahora bloquea con 403 mientras el flag
siga activo; /auth/me y /auth/change-password siguen accesibles porque el
usuario necesita poder leer su estado y cambiar la contraseña.
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def user_must_change_password(make_user, db_session):
    user = await make_user(role=UserRole.admin)
    user.must_change_password = True
    await db_session.commit()
    await db_session.refresh(user)
    return user


pytestmark = pytest.mark.asyncio


class TestMustChangePasswordEnforcement:
    async def test_permission_gated_endpoint_returns_403(
        self, client, user_must_change_password, auth_headers
    ):
        r = await client.get(
            "/api/v1/widget/config", headers=auth_headers(user_must_change_password)
        )
        assert r.status_code == 403
        assert "contraseña" in r.json()["detail"].lower()

    async def test_me_endpoint_still_accessible(
        self, client, user_must_change_password, auth_headers
    ):
        r = await client.get(
            "/api/v1/auth/me", headers=auth_headers(user_must_change_password)
        )
        assert r.status_code == 200

    async def test_change_password_endpoint_still_accessible(
        self, client, user_must_change_password, auth_headers
    ):
        r = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Test1234!", "new_password": "NuevaClave5678!"},
            headers=auth_headers(user_must_change_password),
        )
        assert r.status_code == 200

    async def test_permission_gated_endpoint_works_after_password_change(
        self, client, user_must_change_password, auth_headers
    ):
        await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Test1234!", "new_password": "NuevaClave5678!"},
            headers=auth_headers(user_must_change_password),
        )
        r = await client.get(
            "/api/v1/widget/config", headers=auth_headers(user_must_change_password)
        )
        assert r.status_code == 200

    async def test_normal_user_not_affected(self, client, make_user, auth_headers):
        user = await make_user(role=UserRole.admin)
        r = await client.get("/api/v1/widget/config", headers=auth_headers(user))
        assert r.status_code == 200
