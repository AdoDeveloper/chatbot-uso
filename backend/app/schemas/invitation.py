from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.viewer
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    token: str
    created_by_id: uuid.UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    is_active: bool
    created_at: datetime
    invite_url: str | None = None  # construido en el router

    model_config = {"from_attributes": True}


class InvitationAcceptRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=100)


class InvitationPublicResponse(BaseModel):
    """Datos públicos del token (sin exponer info sensible)."""
    email: str
    role: UserRole
    expires_at: datetime
    is_usable: bool
