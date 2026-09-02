from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import P
from app.models.enums import NotificationEvent

EVENT_PERMISSION: dict[NotificationEvent, str] = {
    NotificationEvent.doc_ready: P.KNOWLEDGE_READ,
    NotificationEvent.doc_error: P.KNOWLEDGE_READ,
    NotificationEvent.escalation: P.ESCALATION_READ,
    NotificationEvent.unanswered_digest: P.ANALYTICS_READ,
    NotificationEvent.provider_down: P.SYSTEM_READ,
    NotificationEvent.service_down: P.SYSTEM_READ,
    NotificationEvent.rate_limit_threshold: P.SYSTEM_READ,
}


async def visible_events(db: AsyncSession, role: str) -> list[str]:
    from app.services.system.rbac import get_role_permissions

    granted = await get_role_permissions(db, role)
    return [
        ev.value for ev, perm in EVENT_PERMISSION.items()
        if perm in granted
    ]


async def role_sees_event(db: AsyncSession, role: str, event: NotificationEvent) -> bool:
    from app.services.system.rbac import has_permission

    perm = EVENT_PERMISSION.get(event)
    if perm is None:
        return False
    module, action = perm.rsplit(".", 1)
    return await has_permission(db, role, module, action)
