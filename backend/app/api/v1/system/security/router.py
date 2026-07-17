"""
Security observability endpoints.

Aggregates security-relevant events from the audit log and Redis rate-limiting
so the admin can answer:
  - ¿Cuántos intentos de inyección bloqueó el sistema esta semana?
  - ¿Qué IP tiene más intentos de login fallidos?
  - ¿Cuál es el patrón de inyección más frecuente?
  - ¿Qué IPs están siendo throttled ahora?

Everything is read-only; actions (unblock IP, ignore pattern) live elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import since_until
from app.core.deps import require_perm
from app.core.permissions import P
from app.core.rate_limit import get_throttled_ips
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.services.ai.guardrails import get_injection_pattern_defs

log = structlog.get_logger()
router = APIRouter(prefix="/security", tags=["system:security"])
_admin = require_perm(P.AUDIT_READ)



class SecuritySummary(BaseModel):
    days: int
    # Failed auth
    failed_logins: int
    failed_logins_prev: int
    distinct_ips_failing: int
    # Guardrail
    injections_blocked: int
    injections_blocked_prev: int
    # Rate limiting
    throttled_ips_now: int
    # Changes of privilege
    admin_actions: int


class FailedLoginGroup(BaseModel):
    ip: str | None
    attempts: int
    distinct_emails: int
    last_attempt_at: datetime


class InjectionByCategory(BaseModel):
    category: str
    count: int
    sample_label: str | None = None


class InjectionSample(BaseModel):
    id: str
    ip: str | None
    pattern: str | None
    question_preview: str | None
    created_at: datetime



def _period_bounds(
    days: int, date_from: datetime | None = None, date_to: datetime | None = None
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (since, until, prev_since, prev_until) for comparisons.

    Si se pasa `date_from`, la ventana es [since, until] y el período previo
    tiene la misma duración inmediatamente anterior. Si no, se deriva de `days`
    como una ventana relativa terminando ahora.
    """
    custom_since, custom_until = since_until(date_from, date_to)
    if custom_since is not None:
        since, until = custom_since, custom_until
        span = until - since
        prev_until = since
        prev_since = since - span
        return since, until, prev_since, prev_until

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)
    return since, now, prev_since, since


async def _count(db: AsyncSession, action: str, since: datetime, until: datetime | None = None) -> int:
    stmt = select(func.count(AuditLog.id)).where(AuditLog.action == action).where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at < until)
    return (await db.execute(stmt)).scalar_one() or 0



@router.get("/summary", response_model=SecuritySummary)
async def security_summary(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    since, until, prev_since, prev_until = _period_bounds(days, date_from, date_to)

    failed_logins = await _count(db, "auth.login_failed", since, until)
    failed_logins_prev = await _count(db, "auth.login_failed", prev_since, prev_until)

    injections = await _count(db, "guardrails.injection_detected", since, until)
    injections_prev = await _count(db, "guardrails.injection_detected", prev_since, prev_until)

    # Distinct IPs failing in current window
    distinct_ips_q = await db.execute(
        select(func.count(AuditLog.ip.distinct()))
        .where(AuditLog.action == "auth.login_failed")
        .where(AuditLog.created_at >= since, AuditLog.created_at < until)
        .where(AuditLog.ip.is_not(None))
    )
    distinct_ips = distinct_ips_q.scalar_one() or 0

    # Admin actions in window (anything starting with admin. or user.)
    admin_q = await db.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.created_at >= since, AuditLog.created_at < until)
        .where(AuditLog.action.like("user.%"))
    )
    admin_actions = admin_q.scalar_one() or 0

    # Throttled IPs across all envs (live Redis snapshot)
    throttled = 0
    try:
        throttled = len(await get_throttled_ips())
    except Exception:
        pass

    return SecuritySummary(
        days=days,
        failed_logins=failed_logins,
        failed_logins_prev=failed_logins_prev,
        distinct_ips_failing=distinct_ips,
        injections_blocked=injections,
        injections_blocked_prev=injections_prev,
        throttled_ips_now=throttled,
        admin_actions=admin_actions,
    )



@router.get("/login-failures", response_model=list[FailedLoginGroup])
async def login_failures(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Group failed logins by IP, ordered by attempt count desc."""
    since, until, _, _ = _period_bounds(days, date_from, date_to)

    # MySQL JSON path via SQLAlchemy: json_unquote sobre meta_json['attempted_email']
    result = await db.execute(
        select(
            AuditLog.ip.label("ip"),
            func.count(AuditLog.id).label("attempts"),
            func.count(func.json_unquote(AuditLog.meta_json["attempted_email"]).distinct()).label("distinct_emails"),
            func.max(AuditLog.created_at).label("last_attempt_at"),
        )
        .where(AuditLog.action == "auth.login_failed")
        .where(AuditLog.created_at >= since, AuditLog.created_at < until)
        .group_by(AuditLog.ip)
        .order_by(func.count(AuditLog.id).desc())
        .limit(limit)
    )
    return [
        FailedLoginGroup(
            ip=r.ip,
            attempts=int(r.attempts),
            distinct_emails=int(r.distinct_emails or 0),
            last_attempt_at=r.last_attempt_at,
        )
        for r in result.all()
    ]



@router.get("/injections/by-category", response_model=list[InjectionByCategory])
async def injections_by_category(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Group blocked injections by pattern category.

    The audit log stores the matched pattern string in `meta_json.pattern`.
    We resolve it to its human-readable category using the guardrails catalog.
    """
    since, until, _, _ = _period_bounds(days, date_from, date_to)

    # Raw SQL because JSON field references + GROUP BY get tangled in
    # SQLAlchemy's compiled output (duplicate-expression grouping errors).
    result = await db.execute(
        text(
            """
            SELECT meta_json->>'$.pattern' AS pattern, COUNT(*) AS cnt
            FROM audit_logs
            WHERE action = 'guardrails.injection_detected'
              AND created_at >= :since
              AND created_at < :until
            GROUP BY pattern
            """
        ).bindparams(since=since, until=until)
    )

    catalog = get_injection_pattern_defs()
    regex_to_meta: dict[str, tuple[str, str]] = {
        p["regex"]: (p["category"], p["label"]) for p in catalog
    }

    category_counts: dict[str, int] = {}
    category_sample: dict[str, str] = {}
    for row in result.all():
        pat = row.pattern or "unknown"
        category, label = regex_to_meta.get(pat, ("Otro / desconocido", pat[:40] if pat else "—"))
        category_counts[category] = category_counts.get(category, 0) + int(row.cnt)
        if category not in category_sample:
            category_sample[category] = label

    return sorted(
        [
            InjectionByCategory(category=cat, count=cnt, sample_label=category_sample.get(cat))
            for cat, cnt in category_counts.items()
        ],
        key=lambda x: x.count,
        reverse=True,
    )



@router.get("/injections/samples", response_model=list[InjectionSample])
async def injection_samples(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Recent injection attempts with full context (pattern + question preview)."""
    since, until, _, _ = _period_bounds(days, date_from, date_to)

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.action == "guardrails.injection_detected")
        .where(AuditLog.created_at >= since, AuditLog.created_at < until)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()

    samples: list[InjectionSample] = []
    for e in entries:
        meta = e.meta_json or {}
        samples.append(InjectionSample(
            id=str(e.id),
            ip=e.ip,
            pattern=meta.get("pattern"),
            question_preview=meta.get("question_preview"),
            created_at=e.created_at,
        ))
    return samples
