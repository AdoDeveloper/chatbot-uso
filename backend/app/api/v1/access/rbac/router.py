"""Admin RBAC API — permisos del usuario autenticado y listado de roles."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_perm
from app.core.permissions import P
from app.models.user import User
from app.schemas.auth import MyPermissionsOut, RoleSummaryOut
from app.services.system import rbac as rbac_service

router = APIRouter(prefix="/rbac", tags=["access:rbac"])
_reader = require_perm(P.SYSTEM_READ)


@router.get("/my-permissions", response_model=MyPermissionsOut)
async def my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve los permisos del usuario autenticado como lista 'modulo.accion'."""
    perms = await rbac_service.get_role_permissions(db, current_user.role)
    return MyPermissionsOut(role=current_user.role, permissions=sorted(perms))


@router.get("/roles", response_model=list[RoleSummaryOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    """Lista todos los roles del sistema."""
    roles = await rbac_service.get_all_roles(db)
    return [
        RoleSummaryOut(
            name=r.name,
            display_name=r.display_name,
            description=r.description,
            is_system=r.is_system,
            created_at=r.created_at,
        )
        for r in roles
    ]
