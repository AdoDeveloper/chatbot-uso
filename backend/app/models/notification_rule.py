from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, JSON, Text, UniqueConstraint, Uuid, func, text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import NotificationChannel, NotificationEvent


class NotificationRule(Base):
    __tablename__ = "notification_rules"
    # 1 regla por (evento, canal) — el frontend asume esta cardinalidad.
    __table_args__ = (
        UniqueConstraint("event", "channel", name="uq_notification_rules_event_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    event: Mapped[NotificationEvent] = mapped_column(
        SAEnum(NotificationEvent, name="notificationevent", create_type=True),
        nullable=False,
        index=True,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notificationchannel", create_type=True),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=sa_text("(0)"))
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default=sa_text("('{}')"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        # Usa __dict__.get para no disparar lazy-loads cuando la instancia
        # está detached (p.ej. dentro de un error handler tras commit).
        d = self.__dict__
        return f"<NotificationRule id={d.get('id')}>"
