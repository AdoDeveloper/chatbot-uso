"""Configuration version management — list, create, diff, rollback, deploy."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.config_version import ConfigVersion
from app.models.enums import ReviewStatus, SourceStatus
from app.models.source import Source
from app.models.user import User
from app.services.monitoring import versions as svc

router = APIRouter(prefix="/versions", tags=["versions"])
_reader = require_perm(P.BOT_SETTINGS_READ)
_admin  = require_perm(P.BOT_SETTINGS_UPDATE)


class VersionOut(BaseModel):
    id: str
    version_number: int
    description: str
    change_summary: str | None = None
    trigger_source: str | None = None
    snapshot_schema_version: int = 1
    is_active: bool
    created_by_name: str | None = None
    created_at: datetime


class VersionDetailOut(VersionOut):
    config_snapshot: dict


class VersionCreate(BaseModel):
    description: str = ""


class VersionListOut(BaseModel):
    versions: list[VersionOut]
    total: int
    page: int
    page_size: int


class RollbackResult(BaseModel):
    version: VersionOut
    warnings: list[str]


class DeployResult(BaseModel):
    version: VersionOut
    pending_sources: int


class DeployStatus(BaseModel):
    last_deployed_at: datetime | None = None
    last_deployed_version: int | None = None
    pending_sources: int
    config_changed_since_deploy: bool
    never_deployed: bool = False


class VersionDiff(BaseModel):
    """Diferencias entre la versión solicitada y su padre.

    `sections` es un mapping `{seccion: [cambios...]}` agrupado por sección
    de configuración (proveedores, prompts, guardrails, etc.). El shape
    exacto lo decide el servicio `system_version_service.compute_diff`.
    """
    version_number: int
    change_summary: str | None = None
    sections: dict[str, list[dict]]


def _to_out(v: ConfigVersion, include_snapshot: bool = False) -> VersionOut | VersionDetailOut:
    base = {
        "id": str(v.id),
        "version_number": v.version_number,
        "description": v.description,
        "change_summary": v.change_summary,
        "trigger_source": v.trigger_source,
        "snapshot_schema_version": v.snapshot_schema_version,
        "is_active": v.is_active,
        "created_by_name": v.created_by.full_name if v.created_by else None,
        "created_at": v.created_at,
    }
    if include_snapshot:
        return VersionDetailOut(**base, config_snapshot=v.config_snapshot)
    return VersionOut(**base)


@router.get("", response_model=VersionListOut)
async def list_versions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    total_q = await db.execute(select(sa_func.count(ConfigVersion.id)))
    total = total_q.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(ConfigVersion)
        .options(selectinload(ConfigVersion.created_by))
        .order_by(ConfigVersion.version_number.desc())
        .offset(offset)
        .limit(page_size)
    )
    versions = result.scalars().all()

    return VersionListOut(
        versions=[_to_out(v) for v in versions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def create_version(
    body: VersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    version = await svc.capture_snapshot(
        db,
        user_id=user.id,
        description=body.description or "Snapshot manual",
        trigger_source="manual",
    )
    if not version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sin cambios desde la última versión")
    await db.commit()
    await db.refresh(version, ["created_by"])
    return _to_out(version)


@router.get("/deploy/status", response_model=DeployStatus)
async def deploy_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    """Returns what's pending since the last production deploy."""
    last_deploy = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    deployed = last_deploy.scalar_one_or_none()

    pending_q = await db.execute(
        select(sa_func.count(Source.id))
        .where(Source.status == SourceStatus.ready)
        .where(Source.review_status == ReviewStatus.pendiente_revision)
        .where(Source.deleted_at.is_(None))
    )
    pending_sources = int(pending_q.scalar_one() or 0)

    if deployed:
        config_changed = await svc.has_config_changed_since(db, deployed.config_snapshot)
    else:
        config_changed = True

    return DeployStatus(
        last_deployed_at=deployed.created_at if deployed else None,
        last_deployed_version=deployed.version_number if deployed else None,
        pending_sources=pending_sources,
        config_changed_since_deploy=config_changed,
        never_deployed=deployed is None,
    )


@router.get("/deploy/config")
async def deploy_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    """Returns the widget_config section from the last deployed snapshot.

    Used by the playground to show the true published widget appearance when
    in 'Publicado' mode, instead of the current draft widget config.
    Returns {} if nothing has been deployed yet (falls back to draft in UI).
    """
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        return {}
    snapshot = version.config_snapshot or {}
    sections = snapshot.get("sections", {})
    widget = sections.get("widget_config") or snapshot.get("widget_config") or {}
    return widget


@router.get("/{version_id}", response_model=VersionDetailOut)
async def get_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
):
    version = await db.get(ConfigVersion, version_id)
    if not version:
        raise NotFoundError("Versión no encontrada")
    await db.refresh(version, ["created_by"])
    return _to_out(version, include_snapshot=True)


@router.get("/{version_id}/diff", response_model=VersionDiff)
async def diff_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_reader),
) -> VersionDiff:
    """Compara la versión con su padre (o la versión inmediatamente anterior si no
    tiene parent_version_id explícito) y devuelve los cambios sección por sección.

    Útil para que el admin entienda qué se modificó antes de hacer un rollback.
    """
    version = await db.get(ConfigVersion, version_id)
    if not version:
        raise NotFoundError("Versión no encontrada")

    parent_snapshot = None
    if version.parent_version_id:
        parent = await db.get(ConfigVersion, version.parent_version_id)
        if parent:
            parent_snapshot = parent.config_snapshot
    else:
        prev_result = await db.execute(
            select(ConfigVersion)
            .where(ConfigVersion.version_number < version.version_number)
            .order_by(ConfigVersion.version_number.desc())
            .limit(1)
        )
        prev = prev_result.scalar_one_or_none()
        if prev:
            parent_snapshot = prev.config_snapshot

    diff = svc.compute_diff(parent_snapshot, version.config_snapshot)
    return VersionDiff(
        version_number=version.version_number,
        change_summary=version.change_summary,
        sections=diff,
    )


@router.post("/deploy", response_model=DeployResult, status_code=status.HTTP_201_CREATED)
async def deploy(
    body: VersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    """Publish current draft config as the new production version.

    Creates a ConfigVersion snapshot tagged 'deploy'.  From this point,
    production chat requests will use this config; playground keeps using
    the live global_settings (draft).
    """
    pending_q = await db.execute(
        select(sa_func.count(Source.id))
        .where(Source.status == SourceStatus.ready)
        .where(Source.review_status == ReviewStatus.pendiente_revision)
        .where(Source.deleted_at.is_(None))
    )
    pending_sources = int(pending_q.scalar_one() or 0)

    last_deploy_q = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    last_deployed = last_deploy_q.scalar_one_or_none()
    if last_deployed and not await svc.has_config_changed_since(db, last_deployed.config_snapshot):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sin cambios de configuración desde el último despliegue",
        )

    version = await svc.capture_snapshot(
        db,
        user_id=user.id,
        description=body.description or "Publicación a producción",
        trigger_source="deploy",
        force=True,
    )
    if not version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo crear la versión de despliegue",
        )
    await db.commit()
    await db.refresh(version)
    await db.refresh(version, ["created_by"])
    return DeployResult(version=_to_out(version), pending_sources=pending_sources)


@router.post("/{version_id}/rollback", response_model=RollbackResult)
async def rollback_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    try:
        rollback_version, warnings = await svc.restore_snapshot(
            db, version_id=version_id, user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    await db.commit()
    await db.refresh(rollback_version, ["created_by"])
    return RollbackResult(
        version=_to_out(rollback_version),
        warnings=warnings,
    )
