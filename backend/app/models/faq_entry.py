from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import text as sa_text

from app.db.types import JSONList
from app.db.session import Base


class FAQEntry(Base):
    __tablename__ = "faq_entries"

    __table_args__ = (
        Index("ix_faq_question_fulltext", "question", mysql_prefix="FULLTEXT"),
        Index("ix_faq_answer_fulltext", "answer", mysql_prefix="FULLTEXT"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONList, default=list, server_default=sa_text("('[]')"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("sources.id", ondelete="SET NULL"),
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )

    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<FAQEntry id={self.id} question={self.question[:40]!r}>"
