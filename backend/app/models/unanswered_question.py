from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import UnansweredStatus


class UnansweredQuestion(Base):
    __tablename__ = "unanswered_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    detected_topic: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[UnansweredStatus] = mapped_column(
        SAEnum(UnansweredStatus, name="unansweredstatus", create_type=True),
        nullable=False,
        default=UnansweredStatus.open,
        index=True,
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["ChatConversation | None"] = relationship(  # noqa: F821
        "ChatConversation", foreign_keys=[conversation_id]
    )
    resolved_by: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[resolved_by_id]
    )

    def __repr__(self) -> str:
        return f"<UnansweredQuestion id={self.id} topic={self.detected_topic!r}>"
