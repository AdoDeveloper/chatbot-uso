"""Helpers para normalizar rangos de fecha de query params en endpoints de reporting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.timezone import PROJECT_TIMEZONE


def since_until(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Normaliza un rango a (since, until) en UTC; las fechas sin zona son días de El Salvador."""
    if date_from is None:
        return None, None
    local = date_from.replace(tzinfo=PROJECT_TIMEZONE) if date_from.tzinfo is None else date_from
    since = local.astimezone(timezone.utc)
    if date_to is None:
        until = datetime.now(timezone.utc)
    else:
        end = date_to.replace(tzinfo=PROJECT_TIMEZONE) if date_to.tzinfo is None else date_to
        until = (end + timedelta(days=1) - timedelta(microseconds=1)).astimezone(timezone.utc)
    return since, until
