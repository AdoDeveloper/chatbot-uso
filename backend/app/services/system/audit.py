from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

log = structlog.get_logger()


def mask_headers(changes: dict) -> dict:
    """Las cabeceras HTTP pueden llevar credenciales: en auditoría solo consta su nombre."""
    out = dict(changes)
    for key in ("extra_headers", "default_headers"):
        if isinstance(out.get(key), dict):
            out[key] = {name: "***" for name in out[key]}
    return out


async def log_action(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    actor_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        meta_json=meta or {},
        ip=ip,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
    log.info("audit.log", action=action, resource_type=resource_type, actor_id=str(actor_id) if actor_id is not None else None)
    return entry
