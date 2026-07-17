"""Endpoint admin para disparar el motor de alertas proactivas.

Pensado para llamarse periódicamente (cron, scheduler externo, o desde la UI
con un botón "Evaluar ahora"). Devuelve el conteo de alertas disparadas por
tipo. Si no hay reglas configuradas para el evento, no se envía nada.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.services.monitoring.alerts import run_all_checks


router = APIRouter(prefix="/alerts", tags=["system:alerts"])
_admin = require_perm(P.SYSTEM_MANAGE)


class AlertsCheckResult(BaseModel):
    fired_by_check: dict[str, int]
    total_fired: int


@router.post("/run", response_model=AlertsCheckResult)
async def run_proactive_checks(
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
) -> AlertsCheckResult:
    """Ejecuta los checks proactivos (service_down, rate_limit, sla, lab_score)."""
    counters = await run_all_checks(db)
    return AlertsCheckResult(
        fired_by_check=counters,
        total_fired=sum(counters.values()),
    )
