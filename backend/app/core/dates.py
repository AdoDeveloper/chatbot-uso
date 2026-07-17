"""Helpers para normalizar rangos de fecha de query params en endpoints de reporting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def since_until(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Normaliza un rango de fechas personalizado a (since, until) con tz UTC.

    Si no se pasa `date_from`, ambos quedan en None y el caller usa su
    ventana relativa por defecto (`hours`/`days`).
    """
    if date_from is None:
        return None, None
    since = date_from.replace(tzinfo=timezone.utc) if date_from.tzinfo is None else date_from
    if date_to is None:
        until = datetime.now(timezone.utc)
    else:
        end = date_to.replace(tzinfo=timezone.utc) if date_to.tzinfo is None else date_to
        # `date_to` llega como inicio del día (00:00) desde un <input type="date">;
        # se extiende al final del día para incluirlo completo en el rango.
        until = end + timedelta(days=1) - timedelta(microseconds=1)
    return since, until
