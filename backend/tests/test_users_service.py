from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.exceptions import NotFoundError
from app.models.enums import UserRole
from app.services.users import service as user_service

pytestmark = pytest.mark.asyncio


async def test_get_by_email_found_and_not_found(db_session, make_user):
    user = await make_user(email="lookup@example.com")

    found = await user_service.get_by_email(db_session, "lookup@example.com")
    assert found is not None
    assert found.id == user.id

    missing = await user_service.get_by_email(db_session, "nope@example.com")
    assert missing is None


async def test_get_by_id_found_and_not_found(db_session, make_user):
    user = await make_user()

    found = await user_service.get_by_id(db_session, user.id)
    assert found is not None
    assert found.email == user.email

    missing = await user_service.get_by_id(db_session, uuid.uuid4())
    assert missing is None


async def test_create_user_success(db_session):
    user = await user_service.create(
        db_session,
        email="new@example.com",
        full_name="New User",
        password="Secret123!",
        role=UserRole.editor,
    )
    assert user.email == "new@example.com"
    assert user.role == UserRole.editor
    assert user.hashed_password != "Secret123!"

    fetched = await user_service.get_by_email(db_session, "new@example.com")
    assert fetched is not None
    assert fetched.id == user.id


async def test_create_user_duplicate_email_raises_409(db_session):
    await user_service.create(
        db_session, email="dup@example.com", full_name="First", password="Secret123!",
    )
    with pytest.raises(HTTPException) as exc_info:
        await user_service.create(
            db_session, email="dup@example.com", full_name="Second", password="Other123!",
        )
    assert exc_info.value.status_code == 409


async def test_authenticate_success(db_session, make_user):
    user = await make_user(email="auth@example.com", password="CorrectPass1!")

    result = await user_service.authenticate(db_session, "auth@example.com", "CorrectPass1!")
    assert result is not None
    assert result.id == user.id


async def test_authenticate_wrong_password(db_session, make_user):
    await make_user(email="auth2@example.com", password="CorrectPass1!")

    result = await user_service.authenticate(db_session, "auth2@example.com", "WrongPass1!")
    assert result is None


async def test_authenticate_unknown_email(db_session):
    result = await user_service.authenticate(db_session, "ghost@example.com", "whatever")
    assert result is None


# ---------------------------------------------------------------------------
# update_user — bloque más grande sin cobertura (líneas 73-124)
# ---------------------------------------------------------------------------

async def test_update_user_not_found_raises(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    with pytest.raises(NotFoundError):
        await user_service.update_user(
            db_session,
            user_id=uuid.uuid4(),
            current_user=admin,
            full_name="X",
            role=None,
            is_active=None,
            ip=None,
        )


async def test_update_user_cannot_change_own_role(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=admin.id,
            current_user=admin,
            full_name=None,
            role="viewer",
            is_active=None,
            ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "propio rol" in exc_info.value.detail


async def test_update_user_same_role_as_self_is_allowed(db_session, make_user):
    """role == user.role no dispara la guarda anti-auto-escalada (no es un cambio real)."""
    admin = await make_user(role=UserRole.admin, full_name="Old Name")

    updated = await user_service.update_user(
        db_session,
        user_id=admin.id,
        current_user=admin,
        full_name="New Name",
        role="admin",
        is_active=None,
        ip=None,
    )
    assert updated.full_name == "New Name"


async def test_update_user_cannot_deactivate_self(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=admin.id,
            current_user=admin,
            full_name=None,
            role=None,
            is_active=False,
            ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "propia cuenta" in exc_info.value.detail


async def test_update_user_cannot_deactivate_last_active_admin(db_session, make_user):
    actor_admin = await make_user(role=UserRole.admin)
    target_admin = await make_user(role=UserRole.admin)
    # Desactivamos a todos los otros admins salvo target_admin para que sea
    # el ultimo admin activo del sistema (actor_admin y target_admin cuentan
    # como 2 activos hasta que forcemos el escenario).
    from sqlalchemy import update
    from app.models.user import User
    await db_session.execute(
        update(User).where(User.id == actor_admin.id).values(role=UserRole.viewer)
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=target_admin.id,
            current_user=actor_admin,
            full_name=None,
            role=None,
            is_active=False,
            ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "último administrador" in exc_info.value.detail


async def test_update_user_deactivate_admin_when_another_admin_active(db_session, make_user):
    actor_admin = await make_user(role=UserRole.admin)
    target_admin = await make_user(role=UserRole.admin)

    updated = await user_service.update_user(
        db_session,
        user_id=target_admin.id,
        current_user=actor_admin,
        full_name=None,
        role=None,
        is_active=False,
        ip=None,
    )
    assert updated.is_active is False


async def test_update_user_non_admin_cannot_modify_admin(db_session, make_user):
    non_admin_actor = await make_user(role=UserRole.editor)
    target_admin = await make_user(role=UserRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=target_admin.id,
            current_user=non_admin_actor,
            full_name="Hack",
            role=None,
            is_active=None,
            ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "Solo un admin puede modificar" in exc_info.value.detail


async def test_update_user_non_admin_cannot_grant_admin_role(db_session, make_user):
    non_admin_actor = await make_user(role=UserRole.editor)
    target = await make_user(role=UserRole.viewer)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=target.id,
            current_user=non_admin_actor,
            full_name=None,
            role="admin",
            is_active=None,
            ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "otorgar el rol" in exc_info.value.detail


async def test_update_user_role_must_exist(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(
            db_session,
            user_id=target.id,
            current_user=admin,
            full_name=None,
            role="not-a-real-role",
            is_active=None,
            ip=None,
        )
    assert exc_info.value.status_code == 400
    assert "no existe" in exc_info.value.detail


async def test_update_user_full_success_updates_all_fields(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer, full_name="Old Name")

    updated = await user_service.update_user(
        db_session,
        user_id=target.id,
        current_user=admin,
        full_name="Updated Name",
        role="editor",
        is_active=False,
        ip="127.0.0.1",
    )
    assert updated.full_name == "Updated Name"
    assert updated.role == "editor"
    assert updated.is_active is False


async def test_update_user_no_changes_still_succeeds(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer)

    updated = await user_service.update_user(
        db_session,
        user_id=target.id,
        current_user=admin,
        full_name=None,
        role=None,
        is_active=None,
        ip=None,
    )
    assert updated.id == target.id


# ---------------------------------------------------------------------------
# delete_user (líneas 134-150)
# ---------------------------------------------------------------------------

async def test_delete_user_cannot_delete_self(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    with pytest.raises(HTTPException) as exc_info:
        await user_service.delete_user(db_session, user_id=admin.id, current_user=admin, ip=None)
    assert exc_info.value.status_code == 400
    assert "propia cuenta" in exc_info.value.detail


async def test_delete_user_not_found(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    with pytest.raises(NotFoundError):
        await user_service.delete_user(db_session, user_id=uuid.uuid4(), current_user=admin, ip=None)


async def test_delete_user_admin_cannot_delete_admin(db_session, make_user):
    actor_admin = await make_user(role=UserRole.admin)
    target_admin = await make_user(role=UserRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.delete_user(db_session, user_id=target_admin.id, current_user=actor_admin, ip=None)
    assert exc_info.value.status_code == 403
    assert "no pueden eliminar a otro admin" in exc_info.value.detail


async def test_delete_user_success(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer)

    await user_service.delete_user(db_session, user_id=target.id, current_user=admin, ip="127.0.0.1")

    assert await user_service.get_by_id(db_session, target.id) is None
