from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    action: str
    resource_type: str
    resource_id: str | None
    meta_json: dict[str, Any]
    ip: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogList(BaseModel):
    logs: list[AuditLogOut]
    total: int
    page: int
    page_size: int
