from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, JSON, String, Text, Uuid, func, text as sa_text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import EscalationTrigger


class EscalationRule(Base):
    __tablename__ = "escalation_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, server_default=sa_text("('')"))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=sa_text("('')"))
    trigger_type: Mapped[EscalationTrigger] = mapped_column(
        SAEnum(EscalationTrigger, name="escalationtrigger", create_type=True),
        nullable=False,
    )
    trigger_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default=sa_text("('{}')"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<EscalationRule id={self.id} name={self.name!r} trigger={self.trigger_type}>"
