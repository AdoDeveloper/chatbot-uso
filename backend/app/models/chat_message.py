from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import MessageFeedback, MessageRole


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="messagerole", create_type=True), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rag_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback: Mapped[MessageFeedback | None] = mapped_column(
        SAEnum(MessageFeedback, name="messagefeedback", create_type=True), nullable=True
    )
    annotation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    annotation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["ChatConversation"] = relationship(  # noqa: F821
        "ChatConversation", back_populates="messages"
    )

    # Índice compuesto: historial y analytics filtran por conversación + fecha
    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} role={self.role}>"
