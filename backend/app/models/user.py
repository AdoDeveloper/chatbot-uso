from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("roles.name", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
        default=UserRole.viewer,
        server_default="viewer",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())
    onboarding_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
