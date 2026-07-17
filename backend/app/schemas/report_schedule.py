from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

DEFAULT_REPORT_SCHEDULE: dict = {
    "unit": "daily",
    "hour": 8,
    "minute": 0,
    "days_of_week": None,
    "day_of_month": None,
    "month": None,
}


class ReportSchedule(BaseModel):
    """Cadencia del reporte de preguntas sin responder (unanswered_daily).

    `hour`/`minute` se interpretan en la zona de El Salvador (UTC-6). El
    scheduler los convierte a UTC al momento de disparar. `days_of_week` usa
    0=Lun … 6=Dom (solo para `unit="weekly"`). `day_of_month` para
    monthly/yearly; `month` solo para yearly.
    """

    unit: str = Field("daily")
    hour: int = Field(8, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    days_of_week: list[int] | None = Field(default=None)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ReportSchedule":
        if self.unit not in ("daily", "weekly", "monthly", "yearly"):
            raise ValueError("unit debe ser daily|weekly|monthly|yearly")
        if self.unit == "weekly" and not self.days_of_week:
            raise ValueError("weekly requiere days_of_week")
        if self.unit in ("monthly", "yearly") and self.day_of_month is None:
            raise ValueError("monthly/yearly requiere day_of_month")
        if self.unit == "yearly" and self.month is None:
            raise ValueError("yearly requiere month")
        return self
