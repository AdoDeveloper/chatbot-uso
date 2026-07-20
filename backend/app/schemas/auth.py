from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str          # nombre del rol dinámico (ej. "superadmin", "moderador")
    is_active: bool
    must_change_password: bool = False
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class RoleSummaryOut(BaseModel):
    """Respuesta de GET /rbac/roles — resumen de un rol del sistema."""
    name: str
    display_name: str
    description: str | None = None
    is_system: bool = False
    created_at: datetime


class MyPermissionsOut(BaseModel):
    """Respuesta de GET /rbac/my-permissions — permisos del usuario autenticado."""
    role: str
    permissions: list[str]
