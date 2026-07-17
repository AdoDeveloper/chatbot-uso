from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Uuid, func, text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RateLimitEvent(Base):
    """Registra cada vez que el rate limiter rechaza una petición.

    Distinto de `audit_log`:
    - `audit_log` registra acciones administrativas (bloqueo manual, etc.).
    - Aquí se persiste el evento *automático* de throttle por límite de tasa.
    Útil para construir un historial: cuándo se throttleó qué IP, en qué
    dimensión (chat:min, chat:hour, api:min) y qué identificador la disparó
    (ip o session_id).
    """

    __tablename__ = "rate_limit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # "chat:min" | "chat:hour" | "chat:session" | "api:min"
    identifier: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # ip o session_id
    identifier_type: Mapped[str] = mapped_column(String(16), nullable=False, default="ip", server_default=sa_text("('ip')"))  # "ip" | "session" | "user"
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("(0)"))
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )

    def __repr__(self) -> str:
        return f"<RateLimitEvent {self.dimension} {self.identifier_type}={self.identifier}>"
