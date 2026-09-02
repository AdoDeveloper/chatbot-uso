"""Tests para app/api/v1/invitations/router.py - no tenía ningún test.

Cubre el flujo completo: listar/crear/revocar invitaciones (admin), y el
flujo público de aceptación (get_invitation_info + accept_invitation). Este
es el endpoint donde se corrigieron hoy dos bugs reales (last_login_at no se
actualizaba al aceptar, FRONTEND_URL mal derivado) - estos tests fijan el
contrato para que no vuelvan a pasar desapercibidos.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import UserRole
from app.models.invitation import Invitation


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


@pytest.fixture
async def viewer_user(make_user):
    return await make_user(role=UserRole.viewer)


async def _make_invitation(db_session, *, email="nuevo@example.com", active=True, expired=False, accepted=False):
    inv = Invitation(
        id=uuid.uuid4(), email=email, role=UserRole.viewer.value,
        token=f"tok-{uuid.uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + (timedelta(days=-1) if expired else timedelta(days=7)),
        is_active=active,
        accepted_at=datetime.now(timezone.utc) if accepted else None,
    )
    db_session.add(inv)
    await db_session.commit()
    await db_session.refresh(inv)
    return inv


class TestListInvitations:
    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.get("/api/v1/users/invitations", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_lists_with_invite_url(self, client, admin_user, auth_headers, db_session):
        await _make_invitation(db_session)
        r = await client.get("/api/v1/users/invitations", headers=auth_headers(admin_user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["invite_url"].endswith(f"/api/v1/auth/invite/{body['items'][0]['token']}")

    async def test_active_only_filter(self, client, admin_user, auth_headers, db_session):
        await _make_invitation(db_session, email="activa@example.com", active=True)
        await _make_invitation(db_session, email="revocada@example.com", active=False)

        r = await client.get(
            "/api/v1/users/invitations", params={"active_only": True}, headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        assert r.json()["total"] == 1

    async def test_without_active_only_includes_expired_and_revoked(self, client, admin_user, auth_headers, db_session):
        await _make_invitation(db_session, email="activa@example.com", active=True)
        await _make_invitation(db_session, email="revocada@example.com", active=False)
        await _make_invitation(db_session, email="expirada@example.com", active=True, expired=True)

        r = await client.get("/api/v1/users/invitations", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["total"] == 3


class TestCreateInvitation:
    async def test_requires_perm(self, client, viewer_user, auth_headers):
        r = await client.post(
            "/api/v1/users/invitations",
            json={"email": "x@example.com", "role": "viewer"},
            headers=auth_headers(viewer_user),
        )
        assert r.status_code == 403

    async def test_creates_invitation(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/users/invitations",
            json={"email": "nuevo@example.com", "role": "editor"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["email"] == "nuevo@example.com"
        assert body["role"] == "editor"
        assert body["is_active"] is True

    async def test_rejects_after_max_active_invitations_for_same_email(
        self, client, admin_user, auth_headers, db_session,
    ):
        for _ in range(3):
            await _make_invitation(db_session, email="repetido@example.com")

        r = await client.post(
            "/api/v1/users/invitations",
            json={"email": "repetido@example.com", "role": "viewer"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 409

    async def test_admin_can_invite_as_admin(self, client, admin_user, auth_headers):
        r = await client.post(
            "/api/v1/users/invitations",
            json={"email": "otro-admin@example.com", "role": "admin"},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201
        assert r.json()["role"] == "admin"

    async def test_non_admin_actor_cannot_invite_as_admin(self, make_user, db_session):
        """Misma guarda anti-escalada que update_user (service.py:98-99):
        solo un admin puede otorgar el rol admin. Se prueba a nivel de
        servicio porque el vector real (rol dinámico con users.manage sin
        ser admin) requiere infraestructura RBAC que hoy no tiene endpoint
        de creación - la guarda debe existir de todos modos, no depender de
        que ese endpoint nunca se construya."""
        from fastapi import HTTPException
        from app.models.enums import UserRole
        from app.services.users import invitation as invitation_service

        non_admin_actor = await make_user(role=UserRole.editor)
        with pytest.raises(HTTPException) as exc_info:
            await invitation_service.create_invitation(
                db_session, email="escalada@example.com",
                role=UserRole.admin, created_by=non_admin_actor,
            )
        assert exc_info.value.status_code == 403


class TestRevokeInvitation:
    async def test_requires_perm(self, client, viewer_user, auth_headers, db_session):
        inv = await _make_invitation(db_session)
        r = await client.delete(f"/api/v1/users/invitations/{inv.id}", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.delete(f"/api/v1/users/invitations/{uuid.uuid4()}", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_revokes_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session)
        r = await client.delete(f"/api/v1/users/invitations/{inv.id}", headers=auth_headers(admin_user))
        assert r.status_code == 204

        await db_session.refresh(inv)
        assert inv.is_active is False


class TestDeleteInvitation:
    """Borrado físico (DELETE .../permanent) - distinto de TestRevokeInvitation
    (soft-delete vía DELETE .../{id}). Restringido a invitaciones ya no
    usables para no borrar por error un enlace que un usuario real todavía
    podría estar por usar."""

    async def test_requires_perm(self, client, viewer_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=False)
        r = await client.delete(f"/api/v1/users/invitations/{inv.id}/permanent", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.delete(f"/api/v1/users/invitations/{uuid.uuid4()}/permanent", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_deletes_revoked_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=False)
        inv_id = inv.id
        r = await client.delete(f"/api/v1/users/invitations/{inv_id}/permanent", headers=auth_headers(admin_user))
        assert r.status_code == 204

        # El DELETE HTTP usa su propia sesión; expire_all() fuerza una lectura fresca en vez del identity map local de db_session.
        db_session.expire_all()
        result = await db_session.get(Invitation, inv_id)
        assert result is None

    async def test_deletes_expired_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=True, expired=True)
        inv_id = inv.id
        r = await client.delete(f"/api/v1/users/invitations/{inv_id}/permanent", headers=auth_headers(admin_user))
        assert r.status_code == 204

        db_session.expire_all()
        result = await db_session.get(Invitation, inv_id)
        assert result is None

    async def test_deletes_accepted_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=True, accepted=True)
        inv_id = inv.id
        r = await client.delete(f"/api/v1/users/invitations/{inv_id}/permanent", headers=auth_headers(admin_user))
        assert r.status_code == 204

        db_session.expire_all()
        result = await db_session.get(Invitation, inv_id)
        assert result is None

    async def test_rejects_deleting_active_usable_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=True, expired=False, accepted=False)
        r = await client.delete(f"/api/v1/users/invitations/{inv.id}/permanent", headers=auth_headers(admin_user))
        assert r.status_code == 409

        result = await db_session.get(Invitation, inv.id)
        assert result is not None


class TestResendInvitation:
    async def test_requires_perm(self, client, viewer_user, auth_headers, db_session):
        inv = await _make_invitation(db_session)
        r = await client.post(f"/api/v1/users/invitations/{inv.id}/resend", headers=auth_headers(viewer_user))
        assert r.status_code == 403

    async def test_not_found_returns_404(self, client, admin_user, auth_headers):
        r = await client.post(f"/api/v1/users/invitations/{uuid.uuid4()}/resend", headers=auth_headers(admin_user))
        assert r.status_code == 404

    async def test_generates_new_token_and_extends_expiration(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, expired=True)
        old_token = inv.token

        r = await client.post(f"/api/v1/users/invitations/{inv.id}/resend", headers=auth_headers(admin_user))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token"] != old_token

        await db_session.refresh(inv)
        assert inv.token != old_token
        expires_at = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
        assert expires_at > datetime.now(timezone.utc)

    async def test_reactivates_expired_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, expired=True, active=True)
        r = await client.post(f"/api/v1/users/invitations/{inv.id}/resend", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["is_active"] is True

        await db_session.refresh(inv)
        assert inv.is_expired is False

    async def test_reactivates_revoked_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, active=False)
        r = await client.post(f"/api/v1/users/invitations/{inv.id}/resend", headers=auth_headers(admin_user))
        assert r.status_code == 200
        assert r.json()["is_active"] is True

    async def test_rejects_already_accepted_invitation(self, client, admin_user, auth_headers, db_session):
        inv = await _make_invitation(db_session, accepted=True, active=False)
        r = await client.post(f"/api/v1/users/invitations/{inv.id}/resend", headers=auth_headers(admin_user))
        assert r.status_code == 409


class TestGetInvitationInfo:
    async def test_unknown_token_returns_404(self, client):
        r = await client.get("/api/v1/auth/invite/no-existe-token")
        assert r.status_code == 404

    async def test_returns_public_fields_only(self, client, db_session):
        inv = await _make_invitation(db_session, email="candidato@example.com")
        r = await client.get(f"/api/v1/auth/invite/{inv.token}")
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "candidato@example.com"
        assert body["is_usable"] is True
        assert "token" not in body


class TestAcceptInvitation:
    async def test_unknown_token_returns_404(self, client):
        r = await client.post(
            "/api/v1/auth/invite/no-existe/accept",
            json={"full_name": "Ana Pérez", "password": "ClaveSegura123"},
        )
        assert r.status_code == 404

    async def test_expired_invitation_rejected(self, client, db_session):
        inv = await _make_invitation(db_session, expired=True)
        r = await client.post(
            f"/api/v1/auth/invite/{inv.token}/accept",
            json={"full_name": "Ana Pérez", "password": "ClaveSegura123"},
        )
        assert r.status_code == 400

    async def test_already_accepted_invitation_rejected(self, client, db_session):
        inv = await _make_invitation(db_session, accepted=True, active=False)
        r = await client.post(
            f"/api/v1/auth/invite/{inv.token}/accept",
            json={"full_name": "Ana Pérez", "password": "ClaveSegura123"},
        )
        assert r.status_code == 400

    async def test_email_already_has_account_rejected(self, client, db_session, make_user):
        existing = await make_user(email="ya-existe@example.com")
        inv = await _make_invitation(db_session, email=existing.email)
        r = await client.post(
            f"/api/v1/auth/invite/{inv.token}/accept",
            json={"full_name": "Ana Pérez", "password": "ClaveSegura123"},
        )
        assert r.status_code == 409

    async def test_success_creates_user_and_updates_last_login(self, client, db_session):
        inv = await _make_invitation(db_session, email="acepta@example.com")
        r = await client.post(
            f"/api/v1/auth/invite/{inv.token}/accept",
            json={"full_name": "Ana Pérez", "password": "ClaveSegura123"},
        )
        assert r.status_code == 201
        body = r.json()
        assert "access_token" in body
        assert body["user"]["email"] == "acepta@example.com"

        from app.services.users.service import get_by_email
        user = await get_by_email(db_session, "acepta@example.com")
        assert user is not None
        assert user.last_login_at is not None

        await db_session.refresh(inv)
        assert inv.is_active is False
        assert inv.accepted_at is not None
