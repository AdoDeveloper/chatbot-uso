from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ServiceStatus(BaseModel):
    name: str
    status: str
    latency_ms: int | None = None
    detail: str | None = None


class ComputeDevice(BaseModel):
    embedding: str       # "cuda" | "cpu"
    reranker: str        # "cuda" | "cpu"
    gpu_available: bool


class HealthDetailed(BaseModel):
    status: str
    services: list[ServiceStatus]
    version: str
    environment: str
    compute: ComputeDevice | None = None


class HealthSnapshotResult(BaseModel):
    """Resultado de un snapshot bajo demanda (POST /health/snapshot)."""
    services: dict[str, Any]
    cpu_percent: float | None = None
    mem_percent: float | None = None
    disk_percent: float | None = None
    recorded_at: str | None = None


class HealthHistoryEntry(BaseModel):
    """Una entrada de la serie temporal de salud."""
    service_name: str
    is_ok: bool
    latency_ms: int | None = None
    recorded_at: datetime
    cpu_percent: float | None = None
    mem_percent: float | None = None
    disk_percent: float | None = None
    error: str | None = None


class UptimeSummary(BaseModel):
    """Resumen de uptime + percentiles de latencia por servicio."""
    service_name: str
    uptime_pct: float
    samples: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    last_ok: bool | None = None
    last_latency_ms: int | None = None
    last_recorded_at: datetime | None = None


class IncidentEntry(BaseModel):
    """Una racha de downtime de un servicio."""
    service_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    samples: int = 0
    last_error: str | None = None
