"""Tests de revocación de JWT y guardas anti-escalada.

Cubre las correcciones de seguridad:
  - C-1: update_user no permite auto-promoción de rol ni auto-desactivación,
    ni que un no-admin modifique a un admin.
  - C-2: logout revoca el token (denylist), refresh rota e invalida el anterior,
    y change_password invalida todas las sesiones previas (tokens_valid_after).
"""
from __future__ import annotations


import pytest

from app.models.enums import UserRole


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin, email="admin@example.com")



async def test_user_cannot_promote_own_role(client, admin_user, auth_headers):
    """Un usuario no puede cambiar su propio rol (auto-promoción)."""
    resp = await client.patch(
        f"/api/v1/users/{admin_user.id}",
        json={"role": "viewer"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 403
    assert "propio rol" in resp.json()["detail"].lower()


async def test_user_cannot_deactivate_self(client, admin_user, auth_headers):
    """Un usuario no puede desactivar su propia cuenta vía update."""
    resp = await client.patch(
        f"/api/v1/users/{admin_user.id}",
        json={"is_active": False},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 403


async def test_non_admin_cannot_modify_admin(client, make_user, auth_headers):
    """Un editor (con users.update) no puede modificar a un admin."""
    admin = await make_user(role=UserRole.admin, email="theadmin@example.com")
    editor = await make_user(role=UserRole.editor, email="editor@example.com")
    resp = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"full_name": "Hacked"},
        headers=auth_headers(editor),
    )
    # 403 por la guarda anti-escalada (o por falta de permiso users.update,
    # que también es un rechazo correcto). Lo que importa: NO 200.
    assert resp.status_code == 403


async def test_non_admin_cannot_grant_admin_role(client, make_user, auth_headers):
    """Un editor no puede otorgar el rol admin a otra cuenta."""
    editor = await make_user(role=UserRole.editor, email="editor2@example.com")
    target = await make_user(role=UserRole.viewer, email="target@example.com")
    resp = await client.patch(
        f"/api/v1/users/{target.id}",
        json={"role": "admin"},
        headers=auth_headers(editor),
    )
    assert resp.status_code == 403


async def test_admin_can_update_other_user(client, admin_user, make_user, auth_headers):
    """Caso feliz: un admin sí puede actualizar a otro usuario."""
    target = await make_user(role=UserRole.viewer, email="normal@example.com")
    resp = await client.patch(
        f"/api/v1/users/{target.id}",
        json={"full_name": "Nombre Nuevo"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Nombre Nuevo"



async def test_logout_revokes_access_token(client, admin_user, auth_headers):
    """Tras logout, el access token deja de ser válido (denylist)."""
    headers = auth_headers(admin_user)
    # Antes del logout: /me responde 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    # Logout
    assert (await client.post("/api/v1/auth/logout", json={}, headers=headers)).status_code == 200
    # Después: el mismo token es rechazado
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_refresh_rotation_invalidates_old_token(client, admin_user):
    """Un refresh ya usado no puede reutilizarse (detección de reuso)."""
    from app.core.security import create_refresh_token

    rt = create_refresh_token(str(admin_user.id))
    # Primer uso: ok
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r1.status_code == 200
    # Segundo uso del mismo refresh: rechazado
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code == 401


async def test_change_password_invalidates_prior_tokens(client, admin_user, auth_headers, db_session):
    """change_password fija tokens_valid_after; tokens viejos quedan obsoletos."""
    import asyncio

    old_headers = auth_headers(admin_user)
    # Esperar 1s para que el nuevo cutoff sea estrictamente posterior al iat.
    await asyncio.sleep(1.1)
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Test1234!", "new_password": "NewPass5678!"},
        headers=old_headers,
    )
    assert resp.status_code == 200
    # El token emitido antes del cambio ahora es stale → 401
    assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 401
