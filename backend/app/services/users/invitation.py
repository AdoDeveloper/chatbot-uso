from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import UserRole
from app.models.invitation import Invitation
from app.models.user import User
from app.services.users import service as user_service


_MAX_ACTIVE_INVITATIONS_PER_EMAIL = 3

async def create_invitation(
    db: AsyncSession,
    email: str,
    role: UserRole,
    created_by: User,
    expires_in_days: int = 7,
) -> Invitation:
    from fastapi import HTTPException
    active_count = await db.scalar(
        select(func.count()).where(
            Invitation.email == email,
            Invitation.is_active.is_(True),
        )
    )
    if (active_count or 0) >= _MAX_ACTIVE_INVITATIONS_PER_EMAIL:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existen {_MAX_ACTIVE_INVITATIONS_PER_EMAIL} invitaciones activas para ese correo. Revócalas antes de crear una nueva.",
        )
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    inv = Invitation(
        email=email,
        role=role,
        token=token,
        created_by_id=created_by.id,
        expires_at=expires_at,
    )
    db.add(inv)
    await db.flush()
    await db.refresh(inv, ["created_by"])
    return inv


async def get_by_token(db: AsyncSession, token: str) -> Invitation | None:
    result = await db.execute(
        select(Invitation)
        .options(selectinload(Invitation.created_by))
        .where(Invitation.token == token)
    )
    return result.scalar_one_or_none()


async def list_invitations(
    db: AsyncSession,
    active_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Invitation], int]:
    q = select(Invitation).options(selectinload(Invitation.created_by))
    count_q = select(func.count()).select_from(Invitation)
    if active_only:
        q = q.where(Invitation.is_active.is_(True))
        count_q = count_q.where(Invitation.is_active.is_(True))
    total = await db.scalar(count_q) or 0
    q = q.order_by(Invitation.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return list(result.scalars().all()), total


async def revoke_invitation(db: AsyncSession, invitation: Invitation) -> Invitation:
    invitation.is_active = False
    await db.flush()
    return invitation


async def accept_invitation(
    db: AsyncSession,
    invitation: Invitation,
    full_name: str,
    password: str,
) -> User:
    """Crea el usuario con el rol de la invitación y marca la invitación como aceptada."""
    user = await user_service.create(
        db,
        email=invitation.email,
        full_name=full_name,
        password=password,
        role=invitation.role,
    )
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.is_active = False
    await db.flush()
    return user
