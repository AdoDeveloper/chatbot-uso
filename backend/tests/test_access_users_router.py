"""Tests HTTP para app/api/v1/access/users/router.py::reset_user_password.

El resto del router (list/get/update/delete) no tenía tests HTTP tampoco,
pero el foco aquí es el endpoint nuevo POST /users/{id}/reset-password: la
lógica de negocio ya está cubierta en test_users_service.py, este archivo
verifica el contrato HTTP real (RBAC vía require_perm, status codes, shape
de la respuesta), que es justamente la capa que test_users_service.py no
puede probar al llamar el servicio directo.
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def editor_user(make_user):
    return await make_user(role=UserRole.editor)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


class TestResetUserPassword:
    async def test_requires_perm(self, client, viewer_user, auth_headers):
        target = viewer_user
        r = await client.post(f"/api/v1/users/{target.id}/reset-password", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_admin_resets_other_user_password(self, client, admin_user, auth_headers, make_user):
        target = await make_user(role=UserRole.viewer, password="OldPass123!")

        r = await client.post(f"/api/v1/users/{target.id}/reset-password", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert len(body["temp_password"]) >= 8
        assert body["user"]["id"] == str(target.id)
        assert body["user"]["must_change_password"] is True

        # La contraseña temporal devuelta debe funcionar para el login real.
        login = await client.post("/api/v1/auth/login", json={
            "email": target.email, "password": body["temp_password"],
        })
        assert login.status_code == 200

    async def test_cannot_reset_own_password_via_this_endpoint(self, client, admin_user, auth_headers):
        r = await client.post(f"/api/v1/users/{admin_user.id}/reset-password", headers=auth_headers(admin_user))
        assert r.status_code == 400

    async def test_not_found(self, client, admin_user, auth_headers):
        import uuid
        r = await client.post(f"/api/v1/users/{uuid.uuid4()}/reset-password", headers=auth_headers(admin_user))
        assert r.status_code == 404