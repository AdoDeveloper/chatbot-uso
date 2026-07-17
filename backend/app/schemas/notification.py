from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import NotificationChannel, NotificationEvent


class NotificationRuleOut(BaseModel):
    id: uuid.UUID
    event: NotificationEvent
    channel: NotificationChannel
    enabled: bool
    target: str | None
    config_json: dict[str, Any]
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationRuleUpdate(BaseModel):
    enabled: bool
    target: str | None = None
    config_json: dict[str, Any] = {}


class ChannelToggleIn(BaseModel):
    """Cuerpo del toggle masivo de un canal (p.ej. activar/desactivar correos)."""
    enabled: bool


class NotificationItemOut(BaseModel):
    """Una notificación en el inbox / historial (target enmascarado)."""
    id: str
    event: str
    channel: str
    target: str | None = None
    status: str
    error_message: str | None = None
    created_at: str
    read_at: str | None = None


class InboxOut(BaseModel):
    """Respuesta de GET /notifications/inbox — últimas N + count no leídas."""
    unread_count: int
    items: list[NotificationItemOut]


class NotificationListOut(BaseModel):
    """Respuesta paginada de GET /notifications — mismo formato que el resto
    de listas del panel (items / total / page / page_size)."""
    items: list[NotificationItemOut]
    total: int
    page: int
    page_size: int


class MarkReadOut(BaseModel):
    """Respuesta de marcar-notificaciones-como-leídas."""
    ok: bool = True
    marked: int = 0



