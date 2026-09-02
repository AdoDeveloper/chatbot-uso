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
# update_user - bloque más grande sin cobertura (líneas 73-124)
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


async def test_delete_user_last_active_admin_blocked_even_for_non_admin_actor(db_session, make_user):
    """Mismo espíritu que la guarda de update_user (líneas 88-93): sin esto,
    un actor no-admin con el permiso users.delete (p. ej. vía un rol
    dinámico personalizado, que el sistema RBAC ya soporta) podría eliminar
    al único admin del sistema. La guarda de update_user existente
    ('admin no puede eliminar a otro admin') no cubre este caso porque el
    actor de esta prueba no es admin."""
    from sqlalchemy import update
    from app.models.user import User

    only_admin = await make_user(role=UserRole.admin)
    non_admin_actor = await make_user(role=UserRole.editor)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.delete_user(
            db_session, user_id=only_admin.id, current_user=non_admin_actor, ip=None
        )
    assert exc_info.value.status_code == 403
    assert "último administrador" in exc_info.value.detail

    # Sigue existiendo - no se llegó a borrar.
    assert await user_service.get_by_id(db_session, only_admin.id) is not None


async def test_delete_user_admin_when_another_admin_active_allowed(db_session, make_user):
    """Con dos admins activos, eliminar uno (por un actor no-admin con
    permiso) debe seguir funcionando - la guarda no debe bloquear de más."""
    first_admin = await make_user(role=UserRole.admin)
    second_admin = await make_user(role=UserRole.admin)
    non_admin_actor = await make_user(role=UserRole.editor)

    await user_service.delete_user(
        db_session, user_id=second_admin.id, current_user=non_admin_actor, ip=None
    )
    assert await user_service.get_by_id(db_session, second_admin.id) is None
    assert await user_service.get_by_id(db_session, first_admin.id) is not None


async def test_delete_user_success(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer)

    await user_service.delete_user(db_session, user_id=target.id, current_user=admin, ip="127.0.0.1")

    assert await user_service.get_by_id(db_session, target.id) is None


async def test_reset_password_success_sets_temp_password_and_forces_change(db_session, make_user):
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer, password="OldPass123!")

    user, temp_password = await user_service.reset_password(
        db_session, user_id=target.id, current_user=admin, ip="127.0.0.1",
    )

    assert user.must_change_password is True
    assert user.tokens_valid_after is not None
    # La contraseña vieja ya no debe funcionar; la temporal sí.
    assert await user_service.authenticate(db_session, target.email, "OldPass123!") is None
    authenticated = await user_service.authenticate(db_session, target.email, temp_password)
    assert authenticated is not None
    assert authenticated.id == target.id


async def test_reset_password_temp_password_meets_min_length(db_session, make_user):
    """ChangePasswordRequest exige min_length=8 - la temporal generada debe
    cumplirlo siempre, o un admin podría generar una contraseña que el
    propio backend rechazaría en el próximo cambio forzado."""
    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.viewer)

    _, temp_password = await user_service.reset_password(
        db_session, user_id=target.id, current_user=admin, ip=None,
    )
    assert len(temp_password) >= 8
    assert any(c.islower() for c in temp_password)
    assert any(c.isupper() for c in temp_password)
    assert any(c.isdigit() for c in temp_password)


async def test_reset_password_cannot_reset_self(db_session, make_user):
    admin = await make_user(role=UserRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.reset_password(
            db_session, user_id=admin.id, current_user=admin, ip=None,
        )
    assert exc_info.value.status_code == 400
    assert "Cambiar contraseña" in exc_info.value.detail


async def test_reset_password_not_found(db_session, make_user):
    admin = await make_user(role=UserRole.admin)

    with pytest.raises(NotFoundError):
        await user_service.reset_password(
            db_session, user_id=uuid.uuid4(), current_user=admin, ip=None,
        )


async def test_reset_password_non_admin_cannot_reset_admin(db_session, make_user):
    non_admin_actor = await make_user(role=UserRole.editor)
    target_admin = await make_user(role=UserRole.admin)

    with pytest.raises(HTTPException) as exc_info:
        await user_service.reset_password(
            db_session, user_id=target_admin.id, current_user=non_admin_actor, ip=None,
        )
    assert exc_info.value.status_code == 403
    assert "Solo un admin puede resetear" in exc_info.value.detail


async def test_reset_password_non_admin_can_reset_non_admin(db_session, make_user):
    """La guarda solo protege a admins - un actor no-admin con el permiso
    users.manage sí puede resetear a un usuario de menor rango."""
    non_admin_actor = await make_user(role=UserRole.editor)
    target = await make_user(role=UserRole.viewer)

    user, temp_password = await user_service.reset_password(
        db_session, user_id=target.id, current_user=non_admin_actor, ip=None,
    )
    assert user.must_change_password is True
    assert temp_password
