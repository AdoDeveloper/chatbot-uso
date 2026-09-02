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
    """Una notificación en el inbox (target enmascarado). `summary` es el
    dato distintivo de este disparo (documento, pregunta, servicio, etc.)."""
    id: str
    event: str
    channel: str
    target: str | None = None
    status: str
    error_message: str | None = None
    created_at: str
    read_at: str | None = None
    summary: str | None = None


class InboxOut(BaseModel):
    """Respuesta de GET /notifications/inbox - últimas N + count no leídas."""
    unread_count: int
    items: list[NotificationItemOut]


class ChannelDeliveryOut(BaseModel):
    """Estado de entrega de un canal dentro de un disparo agrupado.
    `recipients` cuenta las filas de ese canal en el trigger; `target`
    solo aplica al canal email."""
    channel: str
    status: str
    recipients: int
    target: str | None = None
    error_message: str | None = None


class NotificationTriggerOut(BaseModel):
    """Un disparo agrupado por trigger_id, con un ChannelDeliveryOut por
    canal. `own_log_id`/`own_read_at` son la entrega in_app del usuario
    actual (si tuvo una), para marcarla leída sin afectar a otros admins."""
    id: str  # trigger_id
    event: str
    created_at: str
    channels: list[ChannelDeliveryOut]
    summary: str | None = None
    own_log_id: str | None = None
    own_read_at: str | None = None


class NotificationListOut(BaseModel):
    """Respuesta paginada de GET /notifications. `items` son disparos
    agrupados, no filas crudas de NotificationLog."""
    items: list[NotificationTriggerOut]
    total: int
    page: int
    page_size: int


class MarkReadOut(BaseModel):
    """Respuesta de marcar-notificaciones-como-leídas."""
    ok: bool = True
    marked: int = 0



