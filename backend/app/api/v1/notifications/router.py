from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.notification_log import NotificationLog
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.schemas.notification import (
    ChannelToggleIn,
    InboxOut,
    MarkReadOut,
    NotificationListOut,
    NotificationRuleOut,
    NotificationItemOut,
    NotificationRuleUpdate,
)
from app.schemas.report_schedule import ReportSchedule
from app.services.system.report_schedule import (
    get_report_schedule as load_report_schedule,
    upsert_report_schedule,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


_EVENT_INAPP_AUDIENCE: dict[NotificationEvent, set[UserRole]] = {
    NotificationEvent.doc_ready: {UserRole.admin, UserRole.editor},
    NotificationEvent.doc_error: {UserRole.admin, UserRole.editor},
    NotificationEvent.escalation: {UserRole.admin, UserRole.editor},
    NotificationEvent.unanswered_daily: {UserRole.admin, UserRole.editor},
    NotificationEvent.provider_down: {UserRole.admin, UserRole.editor, UserRole.viewer},
    NotificationEvent.service_down: {UserRole.admin, UserRole.editor, UserRole.viewer},
    NotificationEvent.rate_limit_threshold: {UserRole.admin, UserRole.editor, UserRole.viewer},
}


def _visible_events(role: UserRole) -> list[str]:
    return [
        ev.value for ev in NotificationEvent
        if role in (_EVENT_INAPP_AUDIENCE.get(ev) or set())
    ]


def _mask_target(target: str | None) -> str | None:
    """Oculta la parte sensible del destino (email/número) en la respuesta."""
    if not target:
        return None
    if "@" in target:
        local, domain = target.split("@", 1)
        return local[:2] + "***@" + domain
    return target[:3] + "***"


@router.get("/rules", response_model=list[NotificationRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    result = await db.execute(
        select(NotificationRule).order_by(NotificationRule.event, NotificationRule.channel)
    )
    return list(result.scalars().all())


class EmailStatusOut(BaseModel):
    """Estado agregado del canal email: true si AL MENOS una regla está activa."""
    email_enabled: bool


@router.get("/rules/email/status", response_model=EmailStatusOut)
async def email_status(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    count = await db.scalar(
        select(func.count())
        .select_from(NotificationRule)
        .where(NotificationRule.channel == NotificationChannel.email, NotificationRule.enabled.is_(True))
    )
    return EmailStatusOut(email_enabled=bool(count))


@router.get("/report-schedule", response_model=ReportSchedule)
async def get_report_schedule_config(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    """Cadencia actual del reporte de preguntas sin responder (default si no se ha configurado)."""
    return await load_report_schedule(db)


@router.put("/report-schedule", response_model=ReportSchedule)
async def update_report_schedule_config(
    body: ReportSchedule,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    """Configura la cadencia del reporte (unidad + día/mes + hora UTC)."""
    return await upsert_report_schedule(db, body)


@router.put("/rules/{rule_id}", response_model=NotificationRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: NotificationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    result = await db.execute(select(NotificationRule).where(NotificationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Regla no encontrada")
    rule.enabled = body.enabled
    if body.target is not None:
        rule.target = body.target
    rule.config_json = body.config_json
    await db.commit()
    refreshed = await db.execute(
        select(NotificationRule)
        .where(NotificationRule.id == rule_id)
        .execution_options(populate_existing=True)
    )
    return refreshed.scalar_one()


class EmailToggleOut(BaseModel):
    """Estado resultante del canal email tras el cambio masivo."""
    enabled: bool
    affected: int


@router.put("/rules/email/toggle", response_model=EmailToggleOut)
async def toggle_email_channel(
    body: ChannelToggleIn,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    """Activa o desactiva el canal email para TODOS los eventos a la vez.

    Útil como un único interruptor "Correos" en la UI: el canal in_app queda
    intacto (siempre activo para alertas en la app). Devuelve el estado
    resultante y cuántas reglas email se modificaron.
    """
    result = await db.execute(
        select(NotificationRule).where(NotificationRule.channel == NotificationChannel.email)
    )
    rules = list(result.scalars().all())
    for rule in rules:
        rule.enabled = body.enabled
    await db.commit()
    return EmailToggleOut(enabled=body.enabled, affected=len(rules))


@router.get("/inbox", response_model=InboxOut)
async def notifications_inbox(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    """Últimas N notificaciones in-app visibles para el rol + count de no leídas."""
    visible = _visible_events(current_user.role)
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.event.in_(visible))
        .order_by(NotificationLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    unread_q = await db.execute(
        select(func.count(NotificationLog.id))
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.event.in_(visible))
        .where(NotificationLog.read_at.is_(None))
    )
    unread = int(unread_q.scalar_one())

    return InboxOut(
        unread_count=unread,
        items=[
            NotificationItemOut(
                id=str(log.id),
                event=log.event,
                channel=log.channel,
                target=_mask_target(log.target),
                status=log.status,
                error_message=log.error_message,
                created_at=str(log.created_at),
                read_at=str(log.read_at) if log.read_at else None,
            )
            for log in logs
        ],
    )


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    """Historial de notificaciones in-app visibles para el rol, paginado."""
    visible = _visible_events(current_user.role)
    total = await db.scalar(
        select(func.count()).select_from(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.event.in_(visible))
    ) or 0
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.event.in_(visible))
        .order_by(NotificationLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = result.scalars().all()

    items = [
        NotificationItemOut(
            id=str(log.id),
            event=log.event,
            channel=log.channel,
            target=_mask_target(log.target),
            status=log.status,
            error_message=log.error_message,
            created_at=str(log.created_at),
            read_at=str(log.read_at) if log.read_at else None,
        )
        for log in logs
    ]
    return NotificationListOut(items=items, total=total, page=page, page_size=page_size)


@router.post("/inbox/mark-all-read", response_model=MarkReadOut)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    from sqlalchemy import update
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    visible = _visible_events(current_user.role)
    res = await db.execute(
        update(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.event.in_(visible))
        .where(NotificationLog.read_at.is_(None))
        .values(read_at=now)
    )
    await db.commit()
    return MarkReadOut(ok=True, marked=res.rowcount or 0)


@router.post("/inbox/{notification_id}/read", response_model=MarkReadOut)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    from datetime import datetime, timezone
    result = await db.execute(
        select(NotificationLog).where(NotificationLog.id == notification_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise NotFoundError("Notificación no encontrada")
    if log.read_at is None:
        log.read_at = datetime.now(timezone.utc)
        await db.commit()
    return MarkReadOut(ok=True)
