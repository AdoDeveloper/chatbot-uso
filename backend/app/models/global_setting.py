from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GlobalSetting(Base):
    """
    Almacén key-value para configuración del chatbot.
    Claves predefinidas: system_prompt, welcome_message, chatbot_name,
    top_k, score_threshold, temperature, max_tokens, use_corrective_rag.
    """
    __tablename__ = "global_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool] = mapped_column(
        JSON, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<GlobalSetting key={self.key!r} value={self.value!r}>"
