from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_ip, require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.user import User
from app.schemas.provider_type_catalog import (
    ProviderTypeCatalogCreate,
    ProviderTypeCatalogOut,
    ProviderTypeCatalogUpdate,
)
from app.services.system import provider_catalog as svc
from app.services.system.audit import log_action

router = APIRouter(prefix="/provider-types", tags=["provider-types"])

_reader = require_perm(P.BOT_SETTINGS_READ)
_admin = require_perm(P.BOT_SETTINGS_UPDATE)


@router.get("", response_model=list[ProviderTypeCatalogOut])
async def list_provider_types(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    return await svc.list_types(db)


@router.post("", response_model=ProviderTypeCatalogOut, status_code=status.HTTP_201_CREATED)
async def create_provider_type(
    data: ProviderTypeCatalogCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    try:
        row = await svc.create_type(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await log_action(
        db, action="provider_type.create", resource_type="provider_type_catalog",
        actor_id=current_user.id, resource_id=str(row.id),
        meta={"type_key": data.type_key}, ip=get_client_ip(request),
    )
    await db.commit()
    return row


@router.patch("/{catalog_id}", response_model=ProviderTypeCatalogOut)
async def update_provider_type(
    catalog_id: uuid.UUID,
    data: ProviderTypeCatalogUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    try:
        row = await svc.update_type(db, catalog_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if not row:
        raise NotFoundError("Tipo de proveedor no encontrado")
    await log_action(
        db, action="provider_type.update", resource_type="provider_type_catalog",
        actor_id=current_user.id, resource_id=str(catalog_id),
        meta={"changes": data.model_dump(exclude_unset=True)}, ip=get_client_ip(request),
    )
    await db.commit()
    return row


@router.delete("/{catalog_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_type(
    catalog_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    deleted = await svc.delete_type(db, catalog_id)
    if not deleted:
        raise NotFoundError("Tipo de proveedor no encontrado")
    await log_action(
        db, action="provider_type.delete", resource_type="provider_type_catalog",
        actor_id=current_user.id, resource_id=str(catalog_id),
        ip=get_client_ip(request),
    )
    await db.commit()
