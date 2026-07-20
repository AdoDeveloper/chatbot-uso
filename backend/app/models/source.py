from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func, text as sa_text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ReviewStatus, SourceStatus, SourceType


class Source(Base):
    __tablename__ = "sources"

    __table_args__ = (
        Index("ix_sources_name_fulltext", "name", mysql_prefix="FULLTEXT"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, name="sourcetype", create_type=True), nullable=False
    )
    status: Mapped[SourceStatus] = mapped_column(
        SAEnum(SourceStatus, name="sourcestatus", create_type=True),
        nullable=False,
        default=SourceStatus.pending,
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="reviewstatus", create_type=False),
        nullable=False,
        default=ReviewStatus.procesando,
        server_default=ReviewStatus.procesando.value,
        index=True,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=sa_text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default=sa_text("('{}')") )

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )

    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821
    reviewed_by: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by_id])  # noqa: F821

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<Source id={self.id} name={self.name!r} type={self.type} status={self.status}>"
