from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.types import JSONList
from app.db.session import Base
from app.models.enums import ConversationStatus


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(ConversationStatus, name="conversationstatus", create_type=True),
        nullable=False,
        default=ConversationStatus.active,
    )
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    csat_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5
    csat_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Escalamiento pendiente de consentimiento del usuario
    escalation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    escalation_trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[list[str]] = mapped_column(JSONList, default=list, server_default="[]", nullable=False)

    user: Mapped["User | None"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    assignee: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_to_user_id])  # noqa: F821
    resolver: Mapped["User | None"] = relationship("User", foreign_keys=[resolved_by_user_id])  # noqa: F821
    messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage", back_populates="conversation", order_by="ChatMessage.created_at"
    )
    escalation_events: Mapped[list["EscalationEvent"]] = relationship(  # noqa: F821
        "EscalationEvent", back_populates="conversation",
        order_by="EscalationEvent.created_at", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChatConversation id={self.id} session={self.session_id}>"
