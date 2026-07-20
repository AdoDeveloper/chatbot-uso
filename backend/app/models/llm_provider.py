from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Familia de API: "openai", "anthropic", "groq", "gemini", "deepseek",
    # "openrouter", "ollama", "mistral", "together", "xai", "fireworks", etc.
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # API key encriptada con Fernet (nula para proveedores sin clave, ej. Ollama local)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Para endpoints personalizados: Ollama, Azure, proxies, etc.
    api_base: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # URL del dashboard del proveedor (opcional). Solo se usa para mostrar
    # un botón de acceso rápido en el panel; nunca se envía al LLM.
    dashboard_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")

    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LLMProvider id={self.id} name={self.name!r} type={self.provider_type} priority={self.priority}>"
