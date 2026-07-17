from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.global_setting import GlobalSetting
from app.schemas.report_schedule import DEFAULT_REPORT_SCHEDULE, ReportSchedule

log = structlog.get_logger()

_KEY = "report_schedule"


async def get_report_schedule(db: AsyncSession) -> ReportSchedule:
    """Lee el agenda del reporte; devuelve el default si falta o es inválida."""
    try:
        row = await db.get(GlobalSetting, _KEY)
        if row is None or row.value is None:
            return ReportSchedule(**DEFAULT_REPORT_SCHEDULE)
        return ReportSchedule(**row.value)
    except Exception as exc:
        log.warning("report_schedule.load_failed", error=str(exc))
        return ReportSchedule(**DEFAULT_REPORT_SCHEDULE)


async def upsert_report_schedule(db: AsyncSession, schedule: ReportSchedule) -> ReportSchedule:
    """Persiste el agenda del reporte (crea o actualiza la fila global_settings)."""
    row = await db.get(GlobalSetting, _KEY)
    if row is None:
        row = GlobalSetting(key=_KEY, value=schedule.model_dump())
        db.add(row)
    else:
        row.value = schedule.model_dump()
    await db.commit()
    return schedule
