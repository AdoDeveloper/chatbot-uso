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
from app.models.enums import NotificationChannel
from app.models.notification_log import NotificationLog
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.schemas.notification import (
    ChannelDeliveryOut,
    ChannelToggleIn,
    InboxOut,
    MarkReadOut,
    NotificationItemOut,
    NotificationListOut,
    NotificationRuleOut,
    NotificationRuleUpdate,
    NotificationTriggerOut,
)
from app.schemas.report_schedule import ReportSchedule
from app.services.notifications.audience import visible_events as _visible_events
from app.services.system.report_schedule import (
    get_report_schedule as load_report_schedule,
)
from app.services.system.report_schedule import (
    upsert_report_schedule,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _mask_target(target: str | None) -> str | None:
    """Oculta la parte sensible del destino (email/número) en la respuesta."""
    if not target:
        return None
    if "@" in target:
        local, domain = target.split("@", 1)
        return local[:2] + "***@" + domain
    return target[:3] + "***"


_SUMMARY_MAX_LEN = 80


def _truncate(text: str, max_len: int = _SUMMARY_MAX_LEN) -> str:
    text = text.strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _summarize_payload(event: str, payload: dict) -> str | None:
    """Extrae el dato distintivo de un disparo según su tipo de evento."""
    if not payload:
        return None

    if event in ("doc_ready", "doc_error"):
        name = payload.get("source_name")
        return _truncate(str(name)) if name else None

    if event == "escalation":
        question = payload.get("question")
        return _truncate(str(question)) if question else None

    if event == "service_down":
        service = payload.get("service")
        return f"Servicio: {service}" if service else None

    if event == "provider_down":
        providers = payload.get("providers")
        return _truncate(str(providers)) if providers else None

    if event == "rate_limit_threshold":
        percent = payload.get("percent")
        return f"{percent}% del límite alcanzado" if percent is not None else None

    if event == "unanswered_digest":
        total = payload.get("total_open")
        if total is None:
            return None
        return f"{total} pregunta{'s' if total != 1 else ''} sin responder" if total else "Sin pendientes"

    return None


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
    smtp_configured: bool


@router.get("/rules/email/status", response_model=EmailStatusOut)
async def email_status(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.NOTIFICATIONS_READ)),
):
    from app.services.notifications.smtp import get_smtp_config

    count = await db.scalar(
        select(func.count())
        .select_from(NotificationRule)
        .where(NotificationRule.channel == NotificationChannel.email, NotificationRule.enabled.is_(True))
    )
    cfg = await get_smtp_config()
    return EmailStatusOut(email_enabled=bool(count), smtp_configured=cfg is not None)


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
    """Últimas N notificaciones in-app de ESTE usuario + count de no leídas.
    """
    visible = await _visible_events(db, current_user.role)
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.user_id == current_user.id)
        .where(NotificationLog.event.in_(visible))
        .order_by(NotificationLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    unread_q = await db.execute(
        select(func.count(NotificationLog.id))
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.user_id == current_user.id)
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
                summary=_summarize_payload(log.event, log.payload_json),
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
    """Historial de notificaciones, agrupado por disparo (trigger_id)."""
    visible = await _visible_events(db, current_user.role)

    trigger_ts = func.max(NotificationLog.created_at).label("trigger_ts")
    total = await db.scalar(
        select(func.count(func.distinct(NotificationLog.trigger_id)))
        .where(NotificationLog.event.in_(visible))
    ) or 0
    page_triggers_result = await db.execute(
        select(NotificationLog.trigger_id, trigger_ts)
        .where(NotificationLog.event.in_(visible))
        .group_by(NotificationLog.trigger_id)
        .order_by(trigger_ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    page_trigger_ids = [row[0] for row in page_triggers_result.all()]
    if not page_trigger_ids:
        return NotificationListOut(items=[], total=total, page=page, page_size=page_size)

    logs_result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.trigger_id.in_(page_trigger_ids))
        .order_by(NotificationLog.created_at.desc())
    )
    logs = logs_result.scalars().all()

    by_trigger: dict[uuid.UUID, list[NotificationLog]] = {}
    for log_row in logs:
        by_trigger.setdefault(log_row.trigger_id, []).append(log_row)

    items = []
    for trigger_id in page_trigger_ids:
        rows = by_trigger.get(trigger_id, [])
        if not rows:
            continue
        channels: dict[str, list[NotificationLog]] = {}
        for row in rows:
            channels.setdefault(row.channel, []).append(row)

        channel_items = []
        for channel_name, channel_rows in channels.items():
            failed = [r for r in channel_rows if r.status == "failed"]
            status = "failed" if failed else "sent"
            error_message = failed[0].error_message if failed else None
            target = (
                _mask_target(channel_rows[0].target)
                if channel_name == NotificationChannel.email.value
                else None
            )
            channel_items.append(ChannelDeliveryOut(
                channel=channel_name,
                status=status,
                recipients=len(channel_rows),
                target=target,
                error_message=error_message,
            ))

        own_row = next(
            (r for r in rows if r.channel == NotificationChannel.in_app.value and r.user_id == current_user.id),
            None,
        )

        items.append(NotificationTriggerOut(
            id=str(trigger_id),
            event=rows[0].event,
            created_at=str(max(r.created_at for r in rows)),
            channels=channel_items,
            summary=_summarize_payload(rows[0].event, rows[0].payload_json),
            own_log_id=str(own_row.id) if own_row else None,
            own_read_at=str(own_row.read_at) if own_row and own_row.read_at else None,
        ))

    return NotificationListOut(items=items, total=total, page=page, page_size=page_size)


@router.post("/inbox/mark-all-read", response_model=MarkReadOut)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    from datetime import datetime, timezone

    from sqlalchemy import update
    now = datetime.now(timezone.utc)
    visible = await _visible_events(db, current_user.role)
    res = await db.execute(
        update(NotificationLog)
        .where(NotificationLog.channel == NotificationChannel.in_app.value)
        .where(NotificationLog.user_id == current_user.id)
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
    current_user: User = Depends(require_perm(P.NOTIFICATIONS_UPDATE)),
):
    from datetime import datetime, timezone
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.id == notification_id)
        .where(NotificationLog.user_id == current_user.id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise NotFoundError("Notificación no encontrada")
    if log.read_at is None:
        log.read_at = datetime.now(timezone.utc)
        await db.commit()
    return MarkReadOut(ok=True)
