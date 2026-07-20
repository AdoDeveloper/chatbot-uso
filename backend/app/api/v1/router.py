from fastapi import APIRouter

from app.api.v1.access.router import router as access_router
from app.api.v1.analytics.router import router as analytics_router
from app.api.v1.audit.router import router as audit_router
from app.api.v1.auth.router import router as auth_router
from app.api.v1.chat.router import router as chat_router
from app.api.v1.conversations.router import router as chat_history_router
from app.api.v1.chunks.router import router as chunks_router
from app.api.v1.escalation.router import router as escalation_router
from app.api.v1.faq.router import router as faq_router
from app.api.v1.health.router import liveness, router as health_router
from app.api.v1.integrations.router import router as integrations_router
from app.api.v1.invitations.router import router as invitations_router
from app.api.v1.notifications.router import router as notifications_router
from app.api.v1.providers.router import router as providers_router
from app.api.v1.settings.router import router as settings_router
from app.api.v1.sources.router import router as sources_router
from app.api.v1.system.router import router as system_router
from app.api.v1.unanswered.router import router as unanswered_router
from app.api.v1.versions.router import router as versions_router
from app.api.v1.widget.router import router as widget_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(invitations_router)
router.include_router(access_router)
router.include_router(system_router)
router.include_router(providers_router)
router.include_router(settings_router)
router.include_router(integrations_router)
router.include_router(versions_router)
router.include_router(sources_router)
router.include_router(chat_router)
router.include_router(chat_history_router)
router.include_router(analytics_router)
router.include_router(unanswered_router)
router.include_router(faq_router)
router.include_router(audit_router)
router.include_router(notifications_router)
router.include_router(escalation_router)
router.include_router(chunks_router)
router.include_router(widget_router)
router.include_router(health_router)


@router.get("/health")
async def health():
    """Compatibility health endpoint. Prefer /health/live for liveness."""
    return await liveness()
