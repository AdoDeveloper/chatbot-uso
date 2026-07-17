from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class TopicStat(BaseModel):
    topic: str
    count: int
    resolution_rate: float


class HeatmapCell(BaseModel):
    # Populated for window='day' and 'week' (0-23)
    hour: int | None = None
    # Populated for window='week' (0=Sun..6=Sat, vía MySQL DAYOFWEEK()-1)
    day: int | None = None
    # Populated for window='month' and 'year' (YYYY-MM-DD)
    date: str | None = None
    count: int

HeatmapWindow = Literal["day", "week", "month", "year"]


class DeviceStat(BaseModel):
    device: str
    count: int
    percentage: float


class TimeSeriesPoint(BaseModel):
    date: str
    count: int


class AnalyticsDashboard(BaseModel):
    queries_today: int
    queries_today_delta: float
    queries_yesterday: int = 0
    queries_week: int = 0                  # últimos 7 días
    resolution_rate: float                 # tasa de resolución sin escalar (hoy)
    resolution_rate_delta: float
    unique_users_today: int
    avg_latency_ms: float                  # P50 (alias mantenido por retrocompat)
    avg_latency_delta: float
    p95_latency_ms: float = 0              # P95
    active_sources: int
    unanswered_pending: int


class AnalyticsTopics(BaseModel):
    topics: list[TopicStat]
    days: int


class AnalyticsHeatmap(BaseModel):
    cells: list[HeatmapCell]
    window: HeatmapWindow = "week"
    range_start: str | None = None
    range_end: str | None = None


class AnalyticsDevices(BaseModel):
    devices: list[DeviceStat]


class AnalyticsTimeSeries(BaseModel):
    points: list[TimeSeriesPoint]
    days: int


class RouteStat(BaseModel):
    route: str
    count: int
    percentage: float


class AnalyticsRoutes(BaseModel):
    routes: list[RouteStat]
    days: int


class LatencyPoint(BaseModel):
    date: str
    avg_ms: float
    p95_ms: float


class AnalyticsLatencyTimeSeries(BaseModel):
    points: list[LatencyPoint]
    days: int


class SourceQualityStat(BaseModel):
    source_id: str
    source_name: str
    retrieval_count: int
    avg_score: float


class AnalyticsSourceQuality(BaseModel):
    sources: list[SourceQualityStat]
    days: int


TimelineEventType = Literal[
    "source_ingested",
    "source_promoted",
    "guardrail_block",
    "escalation",
    "provider_error",
    "cache_cleared",
    "user_login",
    "version_snapshot",
    "unanswered_spike",
    "other",
]


class TimelineEvent(BaseModel):
    id: str                          # source-uniqued id (eg. audit:xxx, escalation:xxx)
    type: TimelineEventType
    title: str                       # "Fuente aprobada: admisiones-2026"
    detail: str | None = None        # optional extra context
    created_at: datetime
    actor_name: str | None = None    # who triggered it (if applicable)
    href: str | None = None          # optional link to inspect


class AnalyticsTimeline(BaseModel):
    events: list[TimelineEvent]
    days: int


class PeriodSnapshot(BaseModel):
    """Métricas agregadas para un rango específico."""
    range_start: str
    range_end: str
    queries: int
    unique_sessions: int
    resolution_rate: float
    avg_latency_ms: float
    p95_latency_ms: float


class PeriodComparison(BaseModel):
    """Compara dos rangos: el actual vs el anterior de igual longitud."""
    current: PeriodSnapshot
    previous: PeriodSnapshot
    deltas: dict[str, float]  # campo → delta porcentual ((curr - prev) / prev * 100)


class ChannelStat(BaseModel):
    channel: str         # "widget" | "api" | "playground" | "unknown"
    count: int
    percentage: float


class AnalyticsChannels(BaseModel):
    channels: list[ChannelStat]
    days: int


class CacheStats(BaseModel):
    hits: int
    misses: int
    hit_rate: float
    days: int


class PageStat(BaseModel):
    page: str          # domain + path, without query string
    count: int
    percentage: float


class AnalyticsPages(BaseModel):
    pages: list[PageStat]
    days: int


class FeedbackStat(BaseModel):
    positive: int
    negative: int
    total: int
    positive_rate: float    # 0–100
    days: int


class FeedbackTrend(BaseModel):
    date: str
    positive: int
    negative: int


class AnalyticsFeedback(BaseModel):
    summary: FeedbackStat
    trend: list[FeedbackTrend]
