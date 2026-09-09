from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ProviderTypeCatalog(Base):
    """Catálogo editable de tipos de proveedor LLM conocidos (URL base +
    headers por defecto). Reemplaza el dict hardcodeado que antes vivía en
    llm_gateway.py - un LLMProvider sin api_base propio resuelve contra
    esta tabla en tiempo de petición (mismo patrón que api_base hoy)."""

    __tablename__ = "provider_type_catalog"
    __table_args__ = (UniqueConstraint("type_key", name="uq_provider_type_catalog_type_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    type_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    default_api_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Ruta del endpoint de listado de modelos, relativa a default_api_base o
    # al api_base del proveedor instanciado. La mayoría sigue "/models"
    # (spec OpenAI), pero algunos difieren (ej. Together AI: /serverless-models).
    models_endpoint_path: Mapped[str] = mapped_column(
        String(120), nullable=False, default="/models"
    )

    # Sembrado vs. creado por el admin - solo cosmético, no bloquea edición/borrado.
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ProviderTypeCatalog id={self.id} type_key={self.type_key!r}>"
