from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ChunkEdit(Base):
    """
    Audit trail for chunk content edits.

    Chunks live in Qdrant (not a SQL table), so this audit lives independently
    and references the point by its string UUID. Every edit stores the previous
    and new content so the admin can see the history or roll back if needed.
    """
    __tablename__ = "chunk_edits"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    # Qdrant point id (UUID string). No FK — we can't constrain against a vector DB.
    chunk_point_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_content: Mapped[str] = mapped_column(Text, nullable=False)
    new_content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False, index=True
    )

    edited_by: Mapped["User | None"] = relationship("User", foreign_keys=[edited_by_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<ChunkEdit id={self.id} chunk={self.chunk_point_id[:8]} by={self.edited_by_id}>"
