from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ChunkEdit(Base):
    """
    Registro de auditoría para ediciones de contenido de chunks.

    Los chunks viven en Qdrant (no en una tabla SQL), así que esta auditoría
    existe de forma independiente y referencia el punto por su UUID en texto.
    Cada edición guarda el contenido anterior y el nuevo para poder ver el
    historial o revertir si hace falta.
    """
    __tablename__ = "chunk_edits"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    # Id del punto en Qdrant (UUID en texto). Sin FK: no se puede restringir contra una BD vectorial.
    chunk_point_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_content: Mapped[str] = mapped_column(Text, nullable=False)
    new_content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        server_default=func.now(), nullable=False, index=True
    )

    edited_by: Mapped["User | None"] = relationship("User", foreign_keys=[edited_by_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<ChunkEdit id={self.id} chunk={self.chunk_point_id[:8]} by={self.edited_by_id}>"
