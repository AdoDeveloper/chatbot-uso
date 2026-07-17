from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_ip, require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.user import User
from app.services.system.audit import log_action
from app.schemas.provider import (
    ProviderCreate, ProviderOut, ProviderReorderRequest, ProviderTestRequest, ProviderTestResult, ProviderUpdate,
    ProviderModelsRequest, ProviderModelsResult, ProviderModelItem,
)
from app.services.system import settings as settings_service
from app.services.ai.llm_gateway import test_connection, fetch_models

router = APIRouter(prefix="/providers", tags=["providers"])

_reader = require_perm(P.BOT_SETTINGS_READ)
_admin  = require_perm(P.BOT_SETTINGS_UPDATE)


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    return await settings_service.list_providers(db)


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    data: ProviderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    provider = await settings_service.create_provider(db, data)
    await log_action(
        db, action="provider.create", resource_type="llm_provider",
        actor_id=current_user.id, resource_id=str(provider.id),
        meta={"provider_type": data.provider_type, "model_name": data.model_name},
        ip=get_client_ip(request),
    )
    await db.commit()
    return provider


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID,
    data: ProviderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    result = await settings_service.update_provider(db, provider_id, data)
    if not result:
        raise NotFoundError("Proveedor no encontrado")
    changed = {k: v for k, v in data.model_dump(exclude_unset=True).items() if k != "api_key"}
    if "api_key" in data.model_dump(exclude_unset=True):
        changed["api_key"] = "***"
    await log_action(
        db, action="provider.update", resource_type="llm_provider",
        actor_id=current_user.id, resource_id=str(provider_id),
        meta={"changes": changed},
        ip=get_client_ip(request),
    )
    await db.commit()
    return result


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    deleted = await settings_service.delete_provider(db, provider_id)
    if not deleted:
        raise NotFoundError("Proveedor no encontrado")
    await log_action(
        db, action="provider.delete", resource_type="llm_provider",
        actor_id=current_user.id, resource_id=str(provider_id),
        ip=get_client_ip(request),
    )
    await db.commit()


@router.post("/models", response_model=ProviderModelsResult)
async def list_provider_models(
    data: ProviderModelsRequest,
    _: User = Depends(_admin),
):
    """Consulta la API del proveedor y devuelve sus modelos disponibles."""
    try:
        items = await fetch_models(
            provider_type=data.provider_type,
            api_key=data.api_key,
            api_base=data.api_base,
        )
        return ProviderModelsResult(models=[ProviderModelItem(**m) for m in items])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/{provider_id}/models", response_model=ProviderModelsResult)
async def list_saved_provider_models(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_admin),
):
    """Consulta modelos usando la API key almacenada del proveedor guardado."""
    row = await settings_service.get_provider_with_key(db, provider_id)
    if not row:
        raise NotFoundError("Proveedor no encontrado")
    provider, api_key = row
    try:
        items = await fetch_models(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base=provider.api_base,
        )
        return ProviderModelsResult(models=[ProviderModelItem(**m) for m in items])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post("/test", response_model=ProviderTestResult)
async def test_provider(
    data: ProviderTestRequest,
    _: User = Depends(_admin),
):
    """Prueba una conexión con credenciales dadas (sin necesidad de guardar el proveedor)."""
    result = await test_connection(
        provider_type=data.provider_type,
        model_name=data.model_name,
        api_key=data.api_key,
        api_base=data.api_base,
    )
    return ProviderTestResult(**result)


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_saved_provider(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_admin),
):
    """Prueba la conexión de un proveedor ya guardado (usa la API key almacenada).

    Persiste el resultado en `llm_providers.last_test_*` para mostrar el estado
    en la UI sin re-pingear cada vez que se carga la página.
    """
    row = await settings_service.get_provider_with_key(db, provider_id)
    if not row:
        raise NotFoundError("Proveedor no encontrado")
    provider, api_key = row
    result = await test_connection(
        provider_type=provider.provider_type,
        model_name=provider.model_name,
        api_key=api_key,
        api_base=provider.api_base,
    )
    await settings_service.record_test_result(
        db, provider_id,
        success=bool(result.get("success")),
        latency_ms=result.get("latency_ms"),
        error=result.get("error"),
    )
    return ProviderTestResult(**result)


@router.post("/reorder", response_model=list[ProviderOut])
async def reorder_providers(
    body: ProviderReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
):
    """Reordena la cadena de prioridad en bulk (drag-and-drop)."""
    items = [(it.id, it.priority) for it in body.items]
    result = await settings_service.reorder_providers(db, items)
    await log_action(
        db, action="provider.reorder", resource_type="llm_provider",
        actor_id=current_user.id, resource_id=None,
        meta={"items": [{"id": str(it.id), "priority": it.priority} for it in body.items]},
        ip=get_client_ip(request),
    )
    await db.commit()
    return result
