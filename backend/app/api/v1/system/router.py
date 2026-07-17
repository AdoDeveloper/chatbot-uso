from fastapi import APIRouter

from app.api.v1.system.cache.router import router as cache_router
from app.api.v1.system.rate_limits.router import router as rate_limits_router
from app.api.v1.system.security.router import router as security_router
from app.api.v1.system.maintenance.router import router as maintenance_router
from app.api.v1.system.alerts.router import router as alerts_router
from app.api.v1.system.guardrails.router import router as guardrails_router

router = APIRouter()

router.include_router(cache_router)
router.include_router(rate_limits_router)
router.include_router(security_router)
router.include_router(maintenance_router)
router.include_router(alerts_router)
router.include_router(guardrails_router)
