from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogList, AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


_SORT_FIELDS = {
    "created_at": AuditLog.created_at,
    "action": AuditLog.action,
    "resource_type": AuditLog.resource_type,
    "actor_id": AuditLog.actor_id,
    "ip": AuditLog.ip,
}


@router.get("/logs", response_model=AuditLogList)
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    ip: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|action|resource_type|actor_id|ip)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.AUDIT_READ)),
):
    sort_col = _SORT_FIELDS[sort_by]
    order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    q = select(AuditLog).options(selectinload(AuditLog.actor)).order_by(order)
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if ip:
        q = q.where(AuditLog.ip == ip)
    if date_from:
        q = q.where(AuditLog.created_at >= date_from)
    if date_to:
        q = q.where(AuditLog.created_at <= date_to)

    total_q = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_q.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(q.offset(offset).limit(page_size))
    logs = result.scalars().all()

    items = []
    for log_entry in logs:
        out = AuditLogOut.model_validate(log_entry)
        if log_entry.actor:
            out.actor_name = log_entry.actor.full_name
        items.append(out)

    return AuditLogList(logs=items, total=total, page=page, page_size=page_size)


@router.get("/logs/export")
async def export_logs(
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    action: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.AUDIT_READ)),
):
    from app.services.ingestion.export import excel_response, pdf_response

    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if date_from:
        q = q.where(AuditLog.created_at >= date_from)
    if date_to:
        q = q.where(AuditLog.created_at <= date_to)

    result = await db.execute(q.limit(5000))
    logs = result.scalars().all()

    rows = [
        {
            "Fecha": str(log.created_at)[:19],
            "Acción": log.action,
            "Tipo recurso": log.resource_type,
            "ID recurso": log.resource_id or "",
            "Actor ID": str(log.actor_id) if log.actor_id else "",
            "IP": log.ip or "",
        }
        for log in logs
    ]

    if format == "pdf":
        return pdf_response(rows, "auditoria", title="Registros de Auditoría")
    return excel_response(rows, "auditoria", sheet_name="Auditoría")


@router.get("/logs/{log_id}", response_model=AuditLogOut)
async def get_log_detail(
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.AUDIT_READ)),
):
    """Detalle completo del log para drill-down: meta_json + actor."""
    result = await db.execute(
        select(AuditLog).options(selectinload(AuditLog.actor)).where(AuditLog.id == log_id)
    )
    log_entry = result.scalar_one_or_none()
    if not log_entry:
        raise NotFoundError("Log no encontrado")
    out = AuditLogOut.model_validate(log_entry)
    if log_entry.actor:
        out.actor_name = log_entry.actor.full_name
    return out


@router.get("/actors", response_model=list[dict])
async def list_actors(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.AUDIT_READ)),
):
    """Lista de actores únicos que han generado logs (para el filtro)."""
    result = await db.execute(
        select(AuditLog.actor_id, User.full_name)
        .join(User, AuditLog.actor_id == User.id, isouter=True)
        .where(AuditLog.actor_id.is_not(None))
        .group_by(AuditLog.actor_id, User.full_name)
        .order_by(User.full_name.asc())
    )
    return [{"id": str(row[0]), "name": row[1] or "—"} for row in result.all()]
