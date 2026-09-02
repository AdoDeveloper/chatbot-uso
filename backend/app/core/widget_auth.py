"""
Autenticación del widget y validación de dominio.
Uso como dependencia de FastAPI: Depends(verify_widget_access)
"""
from __future__ import annotations

from fnmatch import fnmatch
from urllib.parse import urlparse

import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.widget_config import WidgetConfig
from app.services.widget.service import get_by_api_key

log = structlog.get_logger()


async def _extract_api_key(request: Request) -> str:
    """Lee la API key desde el header X-Widget-Key o el query param widget_key."""
    key = request.headers.get("X-Widget-Key") or request.query_params.get("widget_key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Widget API key required (X-Widget-Key header or widget_key param)",
        )
    return key


async def require_widget_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WidgetConfig:
    """Valida la API key y devuelve el WidgetConfig."""
    key = await _extract_api_key(request)
    cfg = await get_by_api_key(db, key)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid widget API key",
        )
    return cfg


def _extract_origin_host(request: Request) -> str | None:
    """Extrae el hostname del header Origin o Referer."""
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin:
        return None
    try:
        parsed = urlparse(origin)
        return parsed.hostname
    except Exception:
        return None


async def verify_widget_access(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WidgetConfig:
    """Valida la API key y verifica la allowlist de dominios."""
    cfg = await require_widget_key(request, db)

    allowlist = cfg.domain_allowlist or []
    if not allowlist or "*" in allowlist:
        log.warning("widget_auth.open_allowlist", widget_id=str(cfg.id),
                    note="domain_allowlist accepts all origins")
        return cfg

    host = _extract_origin_host(request)
    if not host:
        if get_settings().ENVIRONMENT == "production":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Origin header required for widget requests",
            )
        return cfg

    for pattern in allowlist:
        if fnmatch(host, pattern):
            return cfg

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Origin '{host}' not in allowed domains",
    )
