from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, Uuid, false, func
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.types import JSONList
from app.db.session import Base
from app.models.enums import ConversationStatus


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_chat_conversations_status_last_message_at", "status", "last_message_at"),
    )

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
        server_default="active",
    )
    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    csat_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5
    csat_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Motivos predefinidos seleccionados junto a la estrella (ver CSAT_REASONS
    # en app/schemas/widget.py). Lista vacía si el usuario no marcó ninguno.
    csat_reasons: Mapped[list[str]] = mapped_column(JSONList, default=list, server_default=sa_text("('[]')"), nullable=False)

    # Escalamiento pendiente de consentimiento del usuario
    escalation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    escalation_trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[list[str]] = mapped_column(JSONList, default=list, server_default=sa_text("('[]')"), nullable=False)

    user: Mapped["User | None"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    resolver: Mapped["User | None"] = relationship("User", foreign_keys=[resolved_by_user_id])  # noqa: F821
    messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage", back_populates="conversation", order_by="ChatMessage.created_at",
        passive_deletes=True,
    )
    escalation_events: Mapped[list["EscalationEvent"]] = relationship(  # noqa: F821
        "EscalationEvent", back_populates="conversation",
        order_by="EscalationEvent.created_at", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ChatConversation id={self.id} session={self.session_id}>"
