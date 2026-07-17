"""Rate limit management endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import since_until
from app.core.deps import require_perm
from app.core.permissions import P
from app.core.rate_limit import (
    get_throttled_ips, reset_ip,
)
from app.db.session import get_db
from app.models.rate_limit_event import RateLimitEvent
from app.schemas.common import OperationStatus

router = APIRouter(prefix="/rate-limits", tags=["system:rate-limits"])
_reader = require_perm(P.SYSTEM_READ)
_admin  = require_perm(P.SYSTEM_MANAGE)


class RateLimitConfig(BaseModel):
    chat_per_min: int = Field(ge=1, le=1000)
    chat_per_hour: int = Field(ge=1, le=100000)


class ThrottledIP(BaseModel):
    ip: str
    current_count: int
    limit: int
    window: str
    ttl_seconds: int


@router.get("/config", response_model=RateLimitConfig)
async def get_config(
    db: AsyncSession = Depends(get_db),
    _=Depends(_reader),
):
    """Devuelve los límites efectivos desde GlobalSetting."""
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    return RateLimitConfig(
        chat_per_min=overrides["rate_limit_chat_per_min"],
        chat_per_hour=overrides["rate_limit_chat_per_hour"],
    )


@router.patch("/config", response_model=OperationStatus)
async def update_config(
    body: RateLimitConfig,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
) -> OperationStatus:
    """Persiste los límites de tasa del chat en GlobalSetting."""
    from app.models.global_setting import GlobalSetting
    from app.services.system.settings import invalidate_runtime_overrides
    await db.merge(GlobalSetting(key="rate_limit_chat_per_min", value=body.chat_per_min))
    await db.merge(GlobalSetting(key="rate_limit_chat_per_hour", value=body.chat_per_hour))
    await db.commit()
    invalidate_runtime_overrides()
    return OperationStatus()


@router.get("/throttled", response_model=list[ThrottledIP])
async def list_throttled(
    db: AsyncSession = Depends(get_db),
    _=Depends(_reader),
):
    from app.services.system.settings import get_runtime_overrides
    overrides = await get_runtime_overrides(db)
    ips = await get_throttled_ips(
        limit_per_min=overrides["rate_limit_chat_per_min"],
        limit_per_hour=overrides["rate_limit_chat_per_hour"],
    )
    return [ThrottledIP(**ip) for ip in ips]


@router.delete("/reset/{ip}", response_model=OperationStatus)
async def unblock_ip(ip: str, _=Depends(_admin)) -> OperationStatus:
    """Limpia los contadores de rate-limit para una IP — la desbloquea de inmediato."""
    await reset_ip(ip)
    return OperationStatus()





class UsagePoint(BaseModel):
    bucket: str         # ISO timestamp del inicio de la hora
    requests: int
    throttles: int


class UsageReport(BaseModel):
    hours: int
    limit_per_min: int
    limit_per_hour: int
    total_requests: int
    total_throttles: int
    points: list[UsagePoint]


@router.get("/usage", response_model=UsageReport)
async def usage_report(
    hours: int = Query(24, ge=1, le=168),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(_reader),
):
    """Tendencia de tráfico vs límite configurado.

    `requests` se calcula desde `chat_messages.created_at` con role=user.
    `throttles` desde `rate_limit_events`.
    Ventana: [since, until] derivada de `date_from`/`date_to`, o de `hours` si no se pasan.
    """
    from app.models.chat_message import ChatMessage
    from app.models.enums import MessageRole
    from app.services.monitoring.analytics import sql_date_format
    from app.services.system.settings import get_runtime_overrides

    overrides = await get_runtime_overrides(db)
    since, until = since_until(date_from, date_to)
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        until = datetime.now(timezone.utc)

    # Buckets por hora como texto ISO, portable MySQL/SQLite.
    _hour_fmt = "%Y-%m-%dT%H:00:00"
    req_q = await db.execute(
        select(
            sql_date_format(db, ChatMessage.created_at, _hour_fmt).label("bucket"),
            func.count(ChatMessage.id).label("n"),
        )
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= since, ChatMessage.created_at <= until)
        .group_by("bucket")
        .order_by("bucket")
    )
    req_by_bucket = {row.bucket: int(row.n) for row in req_q.all()}

    # Conteo de throttles por hora
    thr_q = await db.execute(
        select(
            sql_date_format(db, RateLimitEvent.created_at, _hour_fmt).label("bucket"),
            func.count(RateLimitEvent.id).label("n"),
        )
        .where(RateLimitEvent.created_at >= since, RateLimitEvent.created_at <= until)
        .group_by("bucket")
        .order_by("bucket")
    )
    thr_by_bucket = {row.bucket: int(row.n) for row in thr_q.all()}

    # Construir serie completa con buckets vacíos en cero.
    # Buckets are already ISO strings from DATE_FORMAT — no .isoformat() needed.
    all_buckets = sorted(set(req_by_bucket.keys()) | set(thr_by_bucket.keys()))
    points = [
        UsagePoint(
            bucket=b,
            requests=req_by_bucket.get(b, 0),
            throttles=thr_by_bucket.get(b, 0),
        )
        for b in all_buckets
    ]

    return UsageReport(
        hours=hours,
        limit_per_min=overrides["rate_limit_chat_per_min"],
        limit_per_hour=overrides["rate_limit_chat_per_hour"],
        total_requests=sum(req_by_bucket.values()),
        total_throttles=sum(thr_by_bucket.values()),
        points=points,
    )


