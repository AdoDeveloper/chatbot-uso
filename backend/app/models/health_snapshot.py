from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class HealthSnapshot(Base):
    """Muestra periódica del estado de un servicio.

    Una fila por (service_name, recorded_at). El admin recolector escribe
    una entrada cada N segundos por servicio (mysql, redis, qdrant, embedding).
    Una caída produce un incidente: la primera entrada con `is_ok=False` tras
    una racha de OK abre el incidente; la primera entrada `is_ok=True` lo cierra.

    Latencia se guarda en `latency_ms` (NULL si el servicio falló por completo).
    P95/P99 se calculan en Python sobre la columna `latency_ms` filtrada por
    `is_ok=True` en una ventana temporal.
    """

    __tablename__ = "health_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )

    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<HealthSnapshot {self.service_name} ok={self.is_ok} {self.recorded_at}>"
