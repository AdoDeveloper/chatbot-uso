from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.rbac import Role
from app.models.user import User
from app.services.system.audit import log_action


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    email: str,
    full_name: str,
    password: str,
    role: UserRole = UserRole.viewer,
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo electrónico")
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(db, email)
    # Always run bcrypt to prevent email enumeration via timing differences.
    # verify_password on the dummy hash takes the same time as a real check.
    _DUMMY_HASH = "$2b$12$KIXnatB2zMqfZOEbLDwVFOeOS8yh6oq5FzCSRXJAZ8M/J8yXxf7Vy"
    if not user:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def update_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    current_user: User,
    full_name: str | None,
    role: str | None,
    is_active: bool | None,
    ip: str | None,
) -> User:
    user = await get_by_id(db, user_id)
    if not user:
        raise NotFoundError("Usuario no encontrado")

    is_self = user_id == current_user.id
    actor_is_admin = current_user.role == UserRole.admin

    # Guardas anti-escalada (espejan las de delete_user):
    #  - Nadie puede cambiar su propio rol ni desactivarse a sí mismo (evita
    #    auto-promoción a admin y auto-bloqueo accidental del último admin).
    #  - Solo un admin puede otorgar/modificar el rol admin, y un no-admin no
    #    puede modificar a un admin (escalada horizontal/vertical).
    if is_self and role is not None and role != user.role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede cambiar su propio rol")
    if is_self and is_active is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede desactivar su propia cuenta")
    if is_active is False and user.role == UserRole.admin:
        active_admins = await db.scalar(
            select(func.count()).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        if (active_admins or 0) <= 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puede desactivar al último administrador activo del sistema",
            )
    if not actor_is_admin and user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un admin puede modificar a otro admin")
    if role == "admin" and not actor_is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un admin puede otorgar el rol de administrador")

    changes: dict[str, Any] = {}
    if full_name is not None:
        changes["full_name"] = {"from": user.full_name, "to": full_name}
        user.full_name = full_name
    if role is not None:
        role_exists = await db.scalar(select(Role).where(Role.name == role))
        if not role_exists:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"El rol '{role}' no existe")
        changes["role"] = {"from": user.role, "to": role}
        user.role = role
    if is_active is not None:
        changes["is_active"] = {"from": user.is_active, "to": is_active}
        user.is_active = is_active

    await log_action(
        db, action="user.update", resource_type="user",
        actor_id=current_user.id, resource_id=str(user_id),
        meta={"target_email": user.email, "changes": changes},
        ip=ip,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    current_user: User,
    ip: str | None,
) -> None:
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puede eliminar su propia cuenta")
    user = await get_by_id(db, user_id)
    if not user:
        raise NotFoundError("Usuario no encontrado")

    if current_user.role == UserRole.admin and user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Los admin no pueden eliminar a otro admin")

    await log_action(
        db, action="user.delete", resource_type="user",
        actor_id=current_user.id, resource_id=str(user_id),
        meta={"target_email": user.email, "target_role": user.role},
        ip=ip,
    )
    await db.delete(user)
    await db.commit()
