from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func, text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import JSONList
from app.db.session import Base


def _generate_widget_key() -> str:
    return "wk_" + secrets.token_hex(16)


class WidgetConfig(Base):
    """Singleton — sólo hay una fila; se crea en el seed."""

    __tablename__ = "widget_config"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    api_key: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, default=_generate_widget_key,
        server_default=sa_text("('')"),
    )
    chatbot_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="Asistente",
        server_default=sa_text("('Asistente')"),
    )
    welcome_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="¡Hola! ¿En qué puedo ayudarte?",
        server_default=sa_text("('¡Hola! ¿En qué puedo ayudarte?')"),
    )
    primary_color: Mapped[str] = mapped_column(
        String(16), nullable=False, default="#1C386D",
        server_default=sa_text("('#1C386D')"),
    )
    position: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bottom-right",
        server_default=sa_text("('bottom-right')"),
    )
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_allowlist: Mapped[list[str]] = mapped_column(
        JSONList, default=list, nullable=False, server_default=sa_text("('[]')"),
    )
    show_sources: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    enable_copy_action: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    enable_feedback_icons: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    # Botón de lectura en voz alta (TTS) junto a cada respuesta del bot.
    enable_tts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    enable_accessibility: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    # Si False, el header del chat y las burbujas del bot no muestran el icono
    # SVG. Permite un look minimalista sin branding.
    show_bot_icon: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    suggestions: Mapped[list[str]] = mapped_column(
        JSONList, default=list, nullable=False, server_default=sa_text("('[]')"),
    )
    # Mensaje proactivo flotante sobre el launcher cerrado. Vacío = desactivado.
    proactive_message: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=sa_text("('')"),
    )
    max_chats_per_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_chats_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    show_end_chat_button: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    show_new_chat_button: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    enable_csat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=sa_text("(0)"))
    csat_question: Mapped[str] = mapped_column(
        Text, default="¿Cómo calificarías esta conversación?", nullable=False,
        server_default=sa_text("('¿Cómo calificarías esta conversación?')"),
    )
    enable_escalation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=sa_text("(1)"))
    launcher_label: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=sa_text("('')"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        d = self.__dict__
        return f"<WidgetConfig id={d.get('id', '?')} name={d.get('chatbot_name', '?')!r}>"
