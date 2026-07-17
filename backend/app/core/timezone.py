"""Zona horaria fija del proyecto: El Salvador (UTC-6, sin horario de verano).

El sistema guarda todos los timestamps en UTC en la base de datos (esto no
cambia), pero la *interpretación* de horarios configurados por el usuario
(por ej. la hora del reporte diario) y la *visualización* se hacen en la
zona de El Salvador, que es donde opera el negocio.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PROJECT_TIMEZONE = ZoneInfo("America/El_Salvador")

# Offset fijo de El Salvador respecto a UTC (UTC-6, sin DST).
UTC_OFFSET_HOURS = -6


def now_sv() -> datetime:
    """Fecha/hora actual expresada en la zona de El Salvador (con tzinfo)."""
    return datetime.now(PROJECT_TIMEZONE)


def utc_to_sv(dt: datetime) -> datetime:
    """Convierte un datetime (UTC o naive) a la zona de El Salvador."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PROJECT_TIMEZONE)


def sv_to_utc(dt: datetime) -> datetime:
    """Convierte un datetime de El Salvador a UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PROJECT_TIMEZONE)
    return dt.astimezone(timezone.utc)
