from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PLAYGROUND_BROWSERS
from app.models.audit_log import AuditLog
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import ConversationStatus, MessageRole, SourceStatus, UnansweredStatus
from app.models.source import Source
from app.models.unanswered_question import UnansweredQuestion
from app.schemas.analytics import (
    AnalyticsChannels,
    AnalyticsDashboard,
    AnalyticsDevices,
    AnalyticsFeedback,
    AnalyticsHeatmap,
    AnalyticsLatencyTimeSeries,
    AnalyticsPages,
    AnalyticsRoutes,
    AnalyticsSourceQuality,
    AnalyticsTimeSeries,
    AnalyticsTimeline,
    AnalyticsTopics,
    CacheStats,
    ChannelStat,
    DeviceStat,
    FeedbackStat,
    FeedbackTrend,
    HeatmapCell,
    LatencyPoint,
    PageStat,
    PeriodComparison,
    PeriodSnapshot,
    RouteStat,
    SourceQualityStat,
    TimelineEvent,
    TimeSeriesPoint,
    TopicStat,
)


def _percentile(data: list[float], p: float) -> float:
    """Calcula el percentil p (0-1) de una lista ya ordenada ascendentemente.
    """
    if not data:
        return 0.0
    n = len(data)
    k = (n - 1) * p
    lo, hi = int(k), min(int(k) + 1, n - 1)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def sql_date_format(db: AsyncSession, col, fmt: str):
    """Expresión de formato de fecha portable: strftime en SQLite, DATE_FORMAT en MySQL."""
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return func.strftime(fmt, col)
    return func.date_format(col, fmt)


def _source_filter(source: str = "production"):
    """Filter conversations by source: 'production' (widget/API) or 'playground' (test)."""
    if source == "playground":
        return ChatConversation.browser.in_(PLAYGROUND_BROWSERS)
    return or_(
        ChatConversation.browser.is_(None),
        ChatConversation.browser.notin_(PLAYGROUND_BROWSERS),
    )


def _source_sql_where(source: str = "production") -> str:
    if source == "playground":
        return "  AND c.browser IN ('playground', 'panel', 'admin')"
    return "  AND (c.browser IS NULL OR c.browser NOT IN ('playground', 'panel', 'admin'))"


_PROD_SQL_JOIN = "JOIN chat_conversations c ON c.id = m.conversation_id"
# Legacy alias — kept so any existing callers still work
_PROD_SQL_WHERE = _source_sql_where("production")


async def get_dashboard(db: AsyncSession, source: str = "production") -> AnalyticsDashboard:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=7)
    prev_week_start = week_start - timedelta(days=7)

    pf = _source_filter(source)

    q_today = await db.execute(
        select(func.count(ChatMessage.id))
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= today_start)
        .where(pf)
    )
    queries_today = q_today.scalar_one() or 0

    q_yesterday = await db.execute(
        select(func.count(ChatMessage.id))
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= yesterday_start)
        .where(ChatMessage.created_at < today_start)
        .where(pf)
    )
    queries_yesterday = q_yesterday.scalar_one() or 1

    queries_delta = round((queries_today - queries_yesterday) / queries_yesterday * 100, 1)

    total_conv_q = await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.started_at >= week_start)
        .where(pf)
    )
    total_conv = total_conv_q.scalar_one() or 1

    unresolved_q = await db.execute(
        select(func.count(UnansweredQuestion.id))
        .join(ChatConversation, UnansweredQuestion.conversation_id == ChatConversation.id, isouter=True)
        .where(UnansweredQuestion.created_at >= week_start)
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .where(pf)
    )
    unresolved = unresolved_q.scalar_one() or 0
    resolution_rate = round(max(0, (total_conv - unresolved) / total_conv * 100), 1)

    prev_unresolved_q = await db.execute(
        select(func.count(UnansweredQuestion.id))
        .join(ChatConversation, UnansweredQuestion.conversation_id == ChatConversation.id, isouter=True)
        .where(UnansweredQuestion.created_at >= prev_week_start)
        .where(UnansweredQuestion.created_at < week_start)
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .where(pf)
    )
    prev_unresolved = prev_unresolved_q.scalar_one() or 0
    prev_total_q = await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.started_at >= prev_week_start)
        .where(ChatConversation.started_at < week_start)
        .where(pf)
    )
    prev_total = prev_total_q.scalar_one() or 1
    prev_resolution = max(0, (prev_total - prev_unresolved) / prev_total * 100)
    resolution_delta = round(resolution_rate - prev_resolution, 1)

    unique_q = await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.started_at >= today_start)
        .where(pf)
    )
    unique_users_today = unique_q.scalar_one() or 0

    lat_q = await db.execute(
        select(func.avg(ChatMessage.latency_ms))
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= week_start)
        .where(pf)
    )
    avg_latency = round(float(lat_q.scalar_one() or 0) / 1000, 2)

    _lat_vals_q = await db.execute(
        select(ChatMessage.latency_ms)
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= week_start)
        .where(pf)
        .order_by(ChatMessage.latency_ms)
    )
    p95_latency_ms = float(_percentile([v for v in _lat_vals_q.scalars().all() if v is not None], 0.95))

    queries_week_q = await db.execute(
        select(func.count(ChatMessage.id))
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= week_start)
        .where(pf)
    )
    queries_week = int(queries_week_q.scalar_one() or 0)

    lat_prev_q = await db.execute(
        select(func.avg(ChatMessage.latency_ms))
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= prev_week_start)
        .where(ChatMessage.created_at < week_start)
        .where(pf)
    )
    prev_latency = float(lat_prev_q.scalar_one() or 0) / 1000
    latency_delta = round(avg_latency - prev_latency, 2)

    src_q = await db.execute(
        select(func.count(Source.id))
        .where(Source.status == SourceStatus.ready)
        .where(Source.deleted_at.is_(None))
    )
    active_sources = src_q.scalar_one() or 0

    unan_q = await db.execute(
        select(func.count(UnansweredQuestion.id))
        .join(ChatConversation, UnansweredQuestion.conversation_id == ChatConversation.id, isouter=True)
        .where(UnansweredQuestion.status == UnansweredStatus.open)
        .where(pf)
    )
    unanswered_pending = unan_q.scalar_one() or 0

    return AnalyticsDashboard(
        queries_today=queries_today,
        queries_today_delta=queries_delta,
        queries_yesterday=int(queries_yesterday),
        queries_week=queries_week,
        resolution_rate=resolution_rate,
        resolution_rate_delta=resolution_delta,
        unique_users_today=unique_users_today,
        avg_latency_ms=avg_latency * 1000,
        avg_latency_delta=latency_delta * 1000,
        p95_latency_ms=p95_latency_ms,
        active_sources=active_sources,
        unanswered_pending=unanswered_pending,
    )


async def get_topics(
    db: AsyncSession, days: int = 7, source: str = "production",
    until: datetime | None = None,
) -> AnalyticsTopics:
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)
    pf = _source_filter(source)
    result = await db.execute(
        select(
            UnansweredQuestion.detected_topic,
            func.count(UnansweredQuestion.id).label("cnt"),
        )
        .join(ChatConversation, UnansweredQuestion.conversation_id == ChatConversation.id, isouter=True)
        .where(UnansweredQuestion.created_at >= since)
        .where(UnansweredQuestion.created_at < _until)
        .where(UnansweredQuestion.detected_topic.is_not(None))
        .where(pf)
        .group_by(UnansweredQuestion.detected_topic)
        .order_by(func.count(UnansweredQuestion.id).desc())
        .limit(10)
    )
    rows = result.all()

    # Conteo de resueltos por tema en UNA sola query agrupada (evita N+1:
    # antes se ejecutaba 1 SELECT COUNT por cada tema del loop anterior).
    resolved_res = await db.execute(
        select(
            UnansweredQuestion.detected_topic,
            func.count(UnansweredQuestion.id).label("cnt"),
        )
        .join(ChatConversation, UnansweredQuestion.conversation_id == ChatConversation.id, isouter=True)
        .where(UnansweredQuestion.created_at >= since)
        .where(UnansweredQuestion.created_at < _until)
        .where(UnansweredQuestion.detected_topic.is_not(None))
        .where(UnansweredQuestion.status == UnansweredStatus.resolved)
        .where(pf)
        .group_by(UnansweredQuestion.detected_topic)
    )
    resolved_by_topic = {r.detected_topic: r.cnt for r in resolved_res.all()}

    topics = []
    for row in rows:
        total = row.cnt
        resolved_count = resolved_by_topic.get(row.detected_topic, 0)
        resolution_rate = round(resolved_count / total * 100, 1) if total else 0
        topics.append(TopicStat(topic=row.detected_topic, count=total, resolution_rate=resolution_rate))

    return AnalyticsTopics(topics=topics, days=days)


async def get_heatmap(db: AsyncSession, window: str = "week") -> AnalyticsHeatmap:
    """Activity heatmap, in 4 time granularities.

    - day:   24 hourly buckets covering the last 24 h
    - week:  7 × 24 grid aggregating the last 30 days (default)
    - month: 30 daily buckets (last 30 days)
    - year:  365 daily buckets (last 365 days)
    """
    now = datetime.now(timezone.utc)

    # SQLite (suite de tests) no tiene HOUR()/DAYOFWEEK(); strftime('%w') y
    # DAYOFWEEK()-1 coinciden en la convención 0=domingo…6=sábado.
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        hour_expr = "CAST(strftime('%H', m.created_at) AS INTEGER)"
        dow_expr = "CAST(strftime('%w', m.created_at) AS INTEGER)"
    else:
        hour_expr = "HOUR(m.created_at)"
        dow_expr = "DAYOFWEEK(m.created_at) - 1"

    if window == "day":
        since = now - timedelta(hours=24)
        result = await db.execute(
            text(
                f"""
                SELECT {hour_expr} AS hour,
                       COUNT(*) AS cnt
                FROM chat_messages m
                JOIN chat_conversations c ON c.id = m.conversation_id
                WHERE m.role = 'user' AND m.created_at >= :since
                  AND (c.browser IS NULL OR c.browser NOT IN ('playground', 'panel', 'admin'))
                GROUP BY hour
                ORDER BY hour
                """
            ).bindparams(since=since)
        )
        cells = [HeatmapCell(hour=r.hour, count=r.cnt) for r in result]
        return AnalyticsHeatmap(
            cells=cells, window="day",
            range_start=since.date().isoformat(),
            range_end=now.date().isoformat(),
        )

    if window == "week":
        since = now - timedelta(days=30)
        result = await db.execute(
            text(
                f"""
                SELECT {hour_expr} AS hour,
                       {dow_expr} AS day,
                       COUNT(*) AS cnt
                FROM chat_messages m
                JOIN chat_conversations c ON c.id = m.conversation_id
                WHERE m.role = 'user' AND m.created_at >= :since
                  AND (c.browser IS NULL OR c.browser NOT IN ('playground', 'panel', 'admin'))
                GROUP BY hour, day
                """
            ).bindparams(since=since)
        )
        cells = [HeatmapCell(hour=r.hour, day=r.day, count=r.cnt) for r in result]
        return AnalyticsHeatmap(
            cells=cells, window="week",
            range_start=since.date().isoformat(),
            range_end=now.date().isoformat(),
        )

    days = 30 if window == "month" else 365
    since = now - timedelta(days=days)
    result = await db.execute(
        text(
            """
            SELECT DATE(m.created_at) AS day, COUNT(*) AS cnt
            FROM chat_messages m
            JOIN chat_conversations c ON c.id = m.conversation_id
            WHERE m.role = 'user' AND m.created_at >= :since
              AND (c.browser IS NULL OR c.browser NOT IN ('playground', 'panel', 'admin'))
            GROUP BY day
            """
        ).bindparams(since=since)
    )
    cells = [HeatmapCell(date=str(r.day), count=r.cnt) for r in result]
    return AnalyticsHeatmap(
        cells=cells, window=window,  # type: ignore[arg-type]
        range_start=since.date().isoformat(),
        range_end=now.date().isoformat(),
    )


async def get_devices(
    db: AsyncSession, days: int = 30, source: str = "production",
    until: datetime | None = None,
) -> AnalyticsDevices:
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)
    result = await db.execute(
        select(
            ChatConversation.device,
            func.count(ChatConversation.id).label("cnt"),
        )
        .where(ChatConversation.started_at >= since)
        .where(ChatConversation.started_at < _until)
        .where(ChatConversation.device.is_not(None))
        .where(_source_filter(source))
        .group_by(ChatConversation.device)
        .order_by(func.count(ChatConversation.id).desc())
    )
    rows = result.all()
    total = sum(r.cnt for r in rows) or 1
    devices = [
        DeviceStat(device=r.device or "Unknown", count=r.cnt, percentage=round(r.cnt / total * 100, 1))
        for r in rows
    ]
    return AnalyticsDevices(devices=devices)


async def get_timeseries(
    db: AsyncSession, days: int = 30, source: str = "production",
    until: datetime | None = None,
) -> AnalyticsTimeSeries:
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)
    result = await db.execute(
        text(
            f"""
            SELECT DATE(m.created_at) AS day, COUNT(*) AS cnt
            FROM chat_messages m
            {_PROD_SQL_JOIN}
            WHERE m.role = 'user' AND m.created_at >= :since AND m.created_at < :until
            {_source_sql_where(source)}
            GROUP BY day
            ORDER BY day
            """
        ).bindparams(since=since, until=_until)
    )
    points = [TimeSeriesPoint(date=str(r.day), count=r.cnt) for r in result]
    return AnalyticsTimeSeries(points=points, days=days)


async def get_route_distribution(db: AsyncSession, days: int = 30, source: str = "production") -> AnalyticsRoutes:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            ChatMessage.rag_route,
            func.count(ChatMessage.id).label("cnt"),
        )
        .join(ChatConversation)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.rag_route.is_not(None))
        .where(ChatMessage.created_at >= since)
        .where(_source_filter(source))
        .group_by(ChatMessage.rag_route)
        .order_by(func.count(ChatMessage.id).desc())
    )
    rows = result.all()
    total = sum(r.cnt for r in rows) or 1
    routes = [
        RouteStat(
            route=r.rag_route or "unknown",
            count=r.cnt,
            percentage=round(r.cnt / total * 100, 1),
        )
        for r in rows
    ]
    return AnalyticsRoutes(routes=routes, days=days)


async def get_latency_timeseries(db: AsyncSession, days: int = 30) -> AnalyticsLatencyTimeSeries:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    day_fmt = sql_date_format(db, ChatMessage.created_at, "%Y-%m-%d")
    result = await db.execute(
        select(
            day_fmt.label("day"),
            ChatMessage.latency_ms,
        )
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= since)
        .where(
            or_(
                ChatConversation.browser.is_(None),
                ChatConversation.browser.notin_(PLAYGROUND_BROWSERS),
            )
        )
        .order_by(day_fmt)
    )
    from collections import defaultdict
    day_latencies: dict[str, list[float]] = defaultdict(list)
    for row in result.all():
        day_latencies[row.day].append(float(row.latency_ms))

    points = []
    for day_str, latencies in sorted(day_latencies.items()):
        latencies.sort()
        points.append(LatencyPoint(
            date=day_str,
            avg_ms=round(sum(latencies) / len(latencies), 1),
            p95_ms=round(_percentile(latencies, 0.95), 1),
        ))
    return AnalyticsLatencyTimeSeries(points=points, days=days)


_AUDIT_EVENT_MAP: dict[str, tuple[str, str]] = {
    "guardrails.injection_detected": ("guardrail_block", "Guardrail bloqueó una inyección"),
    "cache.cleared":                  ("cache_cleared", "Caché semántico limpiado"),
    "auth.login":                     ("user_login", "Inicio de sesión"),
    "source.upload":                  ("source_ingested", "Fuente subida"),
    "version.snapshot":               ("version_snapshot", "Snapshot de versión creado"),
    "provider.failure":               ("provider_error", "Falla de proveedor LLM"),
}


async def get_timeline(
    db: AsyncSession,
    days: int = 7,
    limit: int = 50,
) -> AnalyticsTimeline:
    from sqlalchemy.orm import selectinload

    since = datetime.now(timezone.utc) - timedelta(days=days)
    events: list[TimelineEvent] = []

    audit_rows = await db.execute(
        select(AuditLog)
        .options(selectinload(AuditLog.actor))
        .where(AuditLog.created_at >= since)
        .where(AuditLog.action.in_(list(_AUDIT_EVENT_MAP.keys())))
        .order_by(AuditLog.created_at.desc())
        .limit(limit * 2)
    )
    for a in audit_rows.scalars().all():
        etype, title = _AUDIT_EVENT_MAP.get(a.action, ("other", a.action))
        meta = a.meta_json or {}
        detail: str | None = None
        href: str | None = None
        if etype == "guardrail_block":
            detail = f"IP {a.ip or 'desconocida'} · motivo: {(meta.get('reason') or '')[:60]}"
        elif etype == "source_ingested":
            detail = meta.get("name")
            if a.resource_id:
                href = f"/dashboard/sources/{a.resource_id}/chunks"
        actor_name = a.actor.full_name if a.actor else None
        events.append(TimelineEvent(
            id=f"audit:{a.id}",
            type=etype,  # type: ignore[arg-type]
            title=title,
            detail=detail,
            created_at=a.created_at,
            actor_name=actor_name,
            href=href,
        ))

    escal_rows = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.status == ConversationStatus.escalated)
        .where(ChatConversation.last_message_at >= since)
        .order_by(ChatConversation.last_message_at.desc())
        .limit(limit)
    )
    for c in escal_rows.scalars().all():
        events.append(TimelineEvent(
            id=f"escalation:{c.id}",
            type="escalation",
            title="Conversación escalada a humano",
            detail=f"Sesión {c.session_id[:12]}" if c.session_id else None,
            created_at=c.last_message_at,
            actor_name=None,
            href=f"/dashboard/history/{c.id}",
        ))

    src_rows = await db.execute(
        select(Source)
        .where(Source.status == SourceStatus.ready)
        .where(Source.updated_at >= since)
        .where(Source.deleted_at.is_(None))
        .order_by(Source.updated_at.desc())
        .limit(limit)
    )
    for s in src_rows.scalars().all():
        events.append(TimelineEvent(
            id=f"source_ready:{s.id}",
            type="source_ingested",
            title=f"Fuente lista: {s.name}",
            detail=f"{s.chunk_count} chunks indexados",
            created_at=s.updated_at,
            actor_name=None,
            href=f"/dashboard/sources/{s.id}/chunks",
        ))

    events.sort(key=lambda e: e.created_at, reverse=True)
    return AnalyticsTimeline(events=events[:limit], days=days)


async def get_source_quality(db: AsyncSession, days: int = 30) -> AnalyticsSourceQuality:
    """Analyze which sources appear most in chat responses via sources_json."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(ChatMessage.sources_json)
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.created_at >= since)
        .where(ChatMessage.sources_json.is_not(None))
        .where(
            or_(
                ChatConversation.browser.is_(None),
                ChatConversation.browser.notin_(PLAYGROUND_BROWSERS),
            )
        )
    )
    from collections import defaultdict
    counts: dict[str, int] = defaultdict(int)
    scores: dict[str, list[float]] = defaultdict(list)
    names: dict[str, str] = {}
    for (sources_json,) in result.all():
        if not isinstance(sources_json, list):
            continue
        for s in sources_json:
            sid = s.get("source_id") or ""
            if not sid:
                continue
            counts[sid] += 1
            names[sid] = s.get("source_name") or "Unknown"
            try:
                scores[sid].append(float(s.get("score") or 0))
            except (TypeError, ValueError):
                pass

    source_list = sorted(
        [
            SourceQualityStat(
                source_id=sid,
                source_name=names[sid],
                retrieval_count=counts[sid],
                avg_score=round(sum(scores[sid]) / len(scores[sid]), 4) if scores[sid] else 0.0,
            )
            for sid in counts
        ],
        key=lambda x: x.retrieval_count,
        reverse=True,
    )[:20]
    return AnalyticsSourceQuality(sources=source_list, days=days)


async def _snapshot_for_range(
    db: AsyncSession, *, range_start: datetime, range_end: datetime, source: str = "production",
) -> PeriodSnapshot:
    """Calcula KPIs agregados de un rango."""
    pf = _source_filter(source)

    queries_q = await db.execute(
        select(func.count(ChatMessage.id))
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.user)
        .where(ChatMessage.created_at >= range_start)
        .where(ChatMessage.created_at < range_end)
        .where(pf)
    )
    queries = int(queries_q.scalar_one() or 0)

    sessions_q = await db.execute(
        select(func.count(ChatConversation.id.distinct()))
        .where(ChatConversation.started_at >= range_start)
        .where(ChatConversation.started_at < range_end)
        .where(pf)
    )
    sessions = int(sessions_q.scalar_one() or 0)

    escalated_q = await db.execute(
        select(func.count(ChatConversation.id))
        .where(ChatConversation.started_at >= range_start)
        .where(ChatConversation.started_at < range_end)
        .where(ChatConversation.status.in_(
            (ConversationStatus.escalated, ConversationStatus.resolved)
        ))
        .where(ChatConversation.escalated_at.is_not(None))
        .where(pf)
    )
    escalated = int(escalated_q.scalar_one() or 0)
    resolution_rate = round(max(0.0, (sessions - escalated) / max(1, sessions) * 100), 2) if sessions else 0.0

    avg_q = await db.execute(
        select(func.avg(ChatMessage.latency_ms))
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= range_start)
        .where(ChatMessage.created_at < range_end)
        .where(pf)
    )
    avg_latency = float(avg_q.scalar_one() or 0)

    _lat_vals2_q = await db.execute(
        select(ChatMessage.latency_ms)
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.latency_ms.is_not(None))
        .where(ChatMessage.created_at >= range_start)
        .where(ChatMessage.created_at < range_end)
        .where(pf)
        .order_by(ChatMessage.latency_ms)
    )
    p95_latency = float(_percentile([v for v in _lat_vals2_q.scalars().all() if v is not None], 0.95))

    return PeriodSnapshot(
        range_start=range_start.date().isoformat(),
        range_end=(range_end - timedelta(seconds=1)).date().isoformat(),
        queries=queries,
        unique_sessions=sessions,
        resolution_rate=resolution_rate,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
    )


async def get_period_comparison(
    db: AsyncSession, *, days: int = 7, source: str = "production",
    until: datetime | None = None,
) -> PeriodComparison:
    """Compara la ventana de N días con los N días anteriores."""
    anchor = until or datetime.now(timezone.utc)
    end = anchor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    cur_start = end - timedelta(days=days)
    prev_end = cur_start
    prev_start = prev_end - timedelta(days=days)

    current = await _snapshot_for_range(db, range_start=cur_start, range_end=end, source=source)
    previous = await _snapshot_for_range(db, range_start=prev_start, range_end=prev_end, source=source)

    def _delta(a: float, b: float) -> float:
        if b <= 0:
            return 0.0
        return round((a - b) / b * 100, 2)

    deltas = {
        "queries": _delta(current.queries, previous.queries),
        "unique_sessions": _delta(current.unique_sessions, previous.unique_sessions),
        "resolution_rate": round(current.resolution_rate - previous.resolution_rate, 2),
        "avg_latency_ms": _delta(current.avg_latency_ms, previous.avg_latency_ms),
        "p95_latency_ms": _delta(current.p95_latency_ms, previous.p95_latency_ms),
    }

    return PeriodComparison(current=current, previous=previous, deltas=deltas)


def _classify_channel(origin_url: str | None, browser: str | None) -> str:
    """Clasifica el canal de entrada de una conversación."""
    if (browser or "").lower() in PLAYGROUND_BROWSERS:
        return "playground"
    if not origin_url:
        return "api"  # sin origin → API directa
    return "widget"


async def get_channels(
    db: AsyncSession, days: int = 7, until: datetime | None = None,
) -> AnalyticsChannels:
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)
    result = await db.execute(
        select(ChatConversation.origin_url, ChatConversation.browser)
        .where(ChatConversation.started_at >= since)
        .where(ChatConversation.started_at < _until)
    )
    counts: dict[str, int] = {}
    total = 0
    for origin, browser in result.all():
        ch = _classify_channel(origin, browser)
        counts[ch] = counts.get(ch, 0) + 1
        total += 1

    channels = sorted(
        [
            ChannelStat(
                channel=k, count=v,
                percentage=round(v / total * 100, 1) if total else 0.0,
            )
            for k, v in counts.items()
        ],
        key=lambda x: -x.count,
    )
    return AnalyticsChannels(channels=channels, days=days)


async def get_cache_stats(db: AsyncSession, days: int = 7) -> CacheStats:
    """Cuenta hits/misses de cache semántica desde `chat_messages.rag_route`.

    Convenios actuales:
    - rag_route LIKE 'cache_%' → hit
    - cualquier otro valor de rag_route → miss
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    hits_q = await db.execute(
        select(func.count(ChatMessage.id))
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.created_at >= since)
        .where(ChatMessage.rag_route.like("cache_%"))
    )
    hits = int(hits_q.scalar_one() or 0)

    misses_q = await db.execute(
        select(func.count(ChatMessage.id))
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.created_at >= since)
        .where(ChatMessage.rag_route.is_not(None))
        .where(~ChatMessage.rag_route.like("cache_%"))
    )
    misses = int(misses_q.scalar_one() or 0)

    total = hits + misses
    hit_rate = round(hits / total * 100, 2) if total else 0.0
    return CacheStats(hits=hits, misses=misses, hit_rate=hit_rate, days=days)


async def get_pages(db: AsyncSession, days: int = 30, source: str = "production") -> AnalyticsPages:
    """Top pages where the widget was opened, grouped by domain + path."""
    from urllib.parse import urlparse

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(ChatConversation.origin_url, func.count(ChatConversation.id).label("cnt"))
        .where(ChatConversation.started_at >= since)
        .where(ChatConversation.origin_url.is_not(None))
        .where(_source_filter(source))
        .group_by(ChatConversation.origin_url)
        .order_by(func.count(ChatConversation.id).desc())
        .limit(100)
    )

    # Collapse by (scheme + netloc + path) to merge query-string variants
    page_counts: dict[str, int] = {}
    for row in result.all():
        raw_url: str = row.origin_url or ""
        try:
            parsed = urlparse(raw_url)
            page = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") or raw_url
        except Exception:
            page = raw_url
        page_counts[page] = page_counts.get(page, 0) + int(row.cnt)

    # Re-sort after collapsing and keep top 20
    sorted_pages = sorted(page_counts.items(), key=lambda x: -x[1])[:20]
    total = sum(c for _, c in sorted_pages)

    pages = [
        PageStat(page=p, count=c, percentage=round(c / total * 100, 1) if total else 0.0)
        for p, c in sorted_pages
    ]
    return AnalyticsPages(pages=pages, days=days)


async def get_feedback(
    db: AsyncSession, *, days: int = 30, source: str = "production",
    until: datetime | None = None,
) -> AnalyticsFeedback:
    """Cuenta likes/dislikes dados a mensajes del asistente."""
    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)
    pf = _source_filter(source)

    result = await db.execute(
        select(ChatMessage.feedback, func.count(ChatMessage.id).label("cnt"))
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.feedback.is_not(None))
        .where(ChatMessage.created_at >= since)
        .where(ChatMessage.created_at < _until)
        .where(pf)
        .group_by(ChatMessage.feedback)
    )
    counts: dict[str, int] = {}
    for row in result.all():
        counts[str(row.feedback.value if row.feedback else row.feedback)] = int(row.cnt)

    positive = counts.get("positive", 0)
    negative = counts.get("negative", 0)
    total = positive + negative
    positive_rate = round(positive / total * 100, 1) if total else 0.0

    summary = FeedbackStat(
        positive=positive,
        negative=negative,
        total=total,
        positive_rate=positive_rate,
        days=days,
    )

    day_fmt = sql_date_format(db, ChatMessage.created_at, "%Y-%m-%d")
    trend_result = await db.execute(
        select(
            day_fmt.label("day"),
            ChatMessage.feedback,
            func.count(ChatMessage.id).label("cnt"),
        )
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatMessage.role == MessageRole.assistant)
        .where(ChatMessage.feedback.is_not(None))
        .where(ChatMessage.created_at >= since)
        .where(ChatMessage.created_at < _until)
        .where(pf)
        .group_by(day_fmt, ChatMessage.feedback)
        .order_by(day_fmt)
    )

    trend_map: dict[str, dict[str, int]] = {}
    for row in trend_result.all():
        day_str = row.day  # already "YYYY-MM-DD" string from date_format
        if day_str not in trend_map:
            trend_map[day_str] = {"positive": 0, "negative": 0}
        fb_val = str(row.feedback.value if row.feedback else row.feedback)
        if fb_val in ("positive", "negative"):
            trend_map[day_str][fb_val] += int(row.cnt)

    trend = [
        FeedbackTrend(date=d, positive=v["positive"], negative=v["negative"])
        for d, v in sorted(trend_map.items())
    ]
    return AnalyticsFeedback(summary=summary, trend=trend)
