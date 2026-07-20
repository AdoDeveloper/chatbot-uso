from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Uuid, func, text as sa_text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ConfigVersion(Base):
    """Whole-system snapshot for versioning and rollback."""
    __tablename__ = "config_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("(0)"))
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default=sa_text("('')"))
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=sa_text("('{}')"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=sa_text("(0)"))
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    change_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("config_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )

    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<ConfigVersion v{self.version_number} active={self.is_active}>"
