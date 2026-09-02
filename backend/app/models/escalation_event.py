from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import EscalationEventType


class EscalationEvent(Base):
    """Registro de auditoría del ciclo de vida de una conversación escalada.

    Cada fila registra una transición (escalado, resuelto, etc.).
    Consultar esta tabla da la línea de tiempo completa de un caso.
    """

    __tablename__ = "escalation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[EscalationEventType] = mapped_column(
        SAEnum(EscalationEventType, name="escalationeventtype", create_type=True),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default=sa_text("('{}')"))
    trigger_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False,
    )

    conversation: Mapped[ChatConversation] = relationship(  # noqa: F821
        "ChatConversation", back_populates="escalation_events",
    )
    actor: Mapped[User | None] = relationship("User", foreign_keys=[actor_user_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<EscalationEvent {self.event_type} conv={self.conversation_id}>"
