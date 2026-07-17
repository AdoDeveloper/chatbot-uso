from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_ip, require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import UserResponse
from app.services.users import service as user_service

router = APIRouter(prefix="/users", tags=["access:users"])


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class UsersSummary(BaseModel):
    total_members: int
    active: int
    no_access_yet: int
    admins: int


@router.get("", response_model=dict)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_READ)),
):
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = [UserResponse.model_validate(u).model_dump(mode="json") for u in result.scalars().all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/summary", response_model=UsersSummary)
async def users_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_READ)),
):
    """Conteos agregados del equipo completo, independientes de la paginación
    de GET /users — mismo patrón que /security/summary."""
    total_members = await db.scalar(select(func.count()).select_from(User)) or 0
    active = await db.scalar(select(func.count()).where(User.is_active.is_(True))) or 0
    no_access_yet = await db.scalar(
        select(func.count()).where(User.last_login_at.is_(None), User.is_active.is_(True))
    ) or 0
    admins = await db.scalar(select(func.count()).where(User.role == UserRole.admin)) or 0
    return UsersSummary(
        total_members=total_members, active=active, no_access_yet=no_access_yet, admins=admins,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_READ)),
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise NotFoundError("Usuario no encontrado")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.USERS_UPDATE)),
):
    user = await user_service.update_user(
        db,
        user_id=user_id,
        current_user=current_user,
        full_name=body.full_name,
        role=body.role,
        is_active=body.is_active,
        ip=get_client_ip(request),
    )
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.USERS_DELETE)),
):
    await user_service.delete_user(
        db,
        user_id=user_id,
        current_user=current_user,
        ip=get_client_ip(request),
    )
