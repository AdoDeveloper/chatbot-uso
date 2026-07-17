from fastapi import APIRouter

from app.api.v1.access.users.router import router as users_router
from app.api.v1.access.rbac.router import router as rbac_router

router = APIRouter()

router.include_router(users_router)
router.include_router(rbac_router)
