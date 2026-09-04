"""Tests para app/api/v1/access/rbac/router.py.

`my-permissions` alimenta al panel para decidir que acciones muestra, asi que
las pruebas fijan la separacion entre roles: un viewer no debe recibir
permisos de escritura, y el listado de roles queda reservado a quien puede
leer configuracion del sistema.
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


class TestMyPermissions:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/rbac/my-permissions")
        assert r.status_code in (401, 403)

    async def test_admin_receives_its_role_and_permissions(
        self, client, admin_user, auth_headers
    ):
        r = await client.get("/api/v1/rbac/my-permissions", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == UserRole.admin.value
        assert len(body["permissions"]) > 0

    async def test_permissions_are_sorted_and_unique(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rbac/my-permissions", headers=auth_headers(admin_user))
        perms = r.json()["permissions"]
        assert perms == sorted(perms)
        assert len(perms) == len(set(perms))

    async def test_viewer_gets_no_write_permissions(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/rbac/my-permissions", headers=auth_headers(viewer_user))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == UserRole.viewer.value
        escrituras = [
            p for p in body["permissions"]
            if p.split(".")[-1] in {"create", "update", "delete", "manage"}
        ]
        assert escrituras == []

    async def test_viewer_receives_fewer_permissions_than_admin(
        self, client, viewer_user, admin_user, auth_headers
    ):
        del_viewer = await client.get(
            "/api/v1/rbac/my-permissions", headers=auth_headers(viewer_user)
        )
        del_admin = await client.get(
            "/api/v1/rbac/my-permissions", headers=auth_headers(admin_user)
        )
        assert set(del_viewer.json()["permissions"]) < set(del_admin.json()["permissions"])

    async def test_each_role_reports_its_own_permissions(
        self, client, editor_user, viewer_user, auth_headers
    ):
        editor = await client.get(
            "/api/v1/rbac/my-permissions", headers=auth_headers(editor_user)
        )
        viewer = await client.get(
            "/api/v1/rbac/my-permissions", headers=auth_headers(viewer_user)
        )
        assert editor.json()["role"] == UserRole.editor.value
        assert viewer.json()["role"] == UserRole.viewer.value
        assert editor.json()["permissions"] != viewer.json()["permissions"]


class TestListRoles:
    async def test_requires_auth(self, client):
        r = await client.get("/api/v1/rbac/roles")
        assert r.status_code in (401, 403)

    async def test_viewer_cannot_list_roles(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/rbac/roles", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_lists_the_system_roles(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rbac/roles", headers=auth_headers(admin_user))
        assert r.status_code == 200
        nombres = {row["name"] for row in r.json()}
        assert {"admin", "editor", "viewer"} <= nombres

    async def test_system_roles_are_flagged(self, client, admin_user, auth_headers):
        r = await client.get("/api/v1/rbac/roles", headers=auth_headers(admin_user))
        for row in r.json():
            if row["name"] in {"admin", "editor", "viewer"}:
                assert row["is_system"] is True
