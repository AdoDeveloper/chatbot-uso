from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_type_catalog import ProviderTypeCatalog
from app.schemas.provider_type_catalog import (
    ProviderTypeCatalogCreate,
    ProviderTypeCatalogOut,
    ProviderTypeCatalogUpdate,
)

log = structlog.get_logger()


def _to_out(row: ProviderTypeCatalog) -> ProviderTypeCatalogOut:
    return ProviderTypeCatalogOut.model_validate(row)


async def list_types(db: AsyncSession) -> list[ProviderTypeCatalogOut]:
    result = await db.execute(
        select(ProviderTypeCatalog).order_by(ProviderTypeCatalog.display_name.asc())
    )
    return [_to_out(r) for r in result.scalars().all()]


async def get_type_by_key(db: AsyncSession, type_key: str) -> ProviderTypeCatalog | None:
    result = await db.execute(
        select(ProviderTypeCatalog).where(ProviderTypeCatalog.type_key == type_key)
    )
    return result.scalars().first()


async def create_type(db: AsyncSession, data: ProviderTypeCatalogCreate) -> ProviderTypeCatalogOut:
    row = ProviderTypeCatalog(
        type_key=data.type_key,
        display_name=data.display_name,
        default_api_base=data.default_api_base,
        default_headers=data.default_headers,
        models_endpoint_path=data.models_endpoint_path,
        notes=data.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"Ya existe un tipo de proveedor con la clave '{data.type_key}'.") from exc
    await db.refresh(row)
    log.info("provider_type_catalog.created", id=str(row.id), type_key=row.type_key)
    return _to_out(row)


async def update_type(
    db: AsyncSession, catalog_id: uuid.UUID, data: ProviderTypeCatalogUpdate,
) -> ProviderTypeCatalogOut | None:
    row = await db.get(ProviderTypeCatalog, catalog_id)
    if not row:
        return None

    if data.type_key is not None:
        row.type_key = data.type_key
    if data.display_name is not None:
        row.display_name = data.display_name
    if "default_api_base" in data.model_fields_set:
        row.default_api_base = data.default_api_base or None
    if data.default_headers is not None:
        row.default_headers = data.default_headers
    if data.models_endpoint_path is not None:
        row.models_endpoint_path = data.models_endpoint_path
    if "notes" in data.model_fields_set:
        row.notes = data.notes or None

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"Ya existe un tipo de proveedor con la clave '{data.type_key}'.") from exc
    await db.refresh(row)
    log.info("provider_type_catalog.updated", id=str(row.id))
    return _to_out(row)


async def delete_type(db: AsyncSession, catalog_id: uuid.UUID) -> bool:
    row = await db.get(ProviderTypeCatalog, catalog_id)
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    log.info("provider_type_catalog.deleted", id=str(catalog_id))
    return True
