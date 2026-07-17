from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.enums import EscalationTrigger
from app.models.user import User
from app.schemas.escalation import (
    ChannelPingResult,
    EscalationRuleCreate,
    EscalationRuleOut,
    EscalationRuleUpdate,
    EscalationTestResult,
    RuleTestRequest,
    RuleTestResult,
    TriggerSchemaOut,
)
from app.services.escalation import metrics as escalation_metrics
from app.services.escalation import rules as rules_svc
from app.services.escalation import service as svc
from app.services.escalation.engine import schema_for_trigger

router = APIRouter(prefix="/escalation", tags=["escalation"])


@router.get("/rules", response_model=list[EscalationRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_READ)),
):
    return await rules_svc.list_rules(db)


@router.post("/rules", response_model=EscalationRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: EscalationRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_UPDATE)),
):
    return await rules_svc.create_rule(db, data=body.model_dump())


@router.patch("/rules/{rule_id}", response_model=EscalationRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: EscalationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_UPDATE)),
):
    return await rules_svc.update_rule(db, rule_id=rule_id, changes=body.model_dump(exclude_unset=True))


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_UPDATE)),
):
    await rules_svc.delete_rule(db, rule_id=rule_id)


@router.post("/smtp-ping", response_model=ChannelPingResult)
async def ping_smtp(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.ESCALATION_MANAGE)),
):
    """Envía un email de prueba al usuario que lo solicita para verificar que
    SMTP está configurado y que los escalamientos llegarán correctamente."""
    return await rules_svc.ping_smtp(db, current_user=current_user)


# ── Trigger schemas (UI dinámica del formulario) ──────────────────────────────

@router.get("/triggers/schemas", response_model=list[TriggerSchemaOut])
async def list_trigger_schemas(
    _: object = Depends(require_perm(P.ESCALATION_READ)),
):
    return [
        TriggerSchemaOut(trigger_type=t, fields=schema_for_trigger(t))
        for t in EscalationTrigger
    ]


# ── Test ──────────────────────────────────────────────────────────────────────

@router.post("/test", response_model=EscalationTestResult)
async def test_escalation(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_MANAGE)),
):
    """Dispara un escalamiento de prueba — los correos llegan a todos los
    administradores activos registrados en el sistema."""
    await svc.dispatch_escalation(
        db,
        conversation_id="test-conversation",
        question="Esta es una prueba de escalamiento",
        reason="Prueba manual desde el panel",
    )
    return EscalationTestResult(success=True, message="Prueba enviada a todos los administradores activos.")


@router.post("/rules/test", response_model=RuleTestResult)
async def test_rule(
    body: RuleTestRequest,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_MANAGE)),
):
    """Prueba una regla individual contra un contexto manual sin disparar canales."""
    return await rules_svc.test_rule(
        db,
        rule_id=body.rule_id,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config,
        context=body.context,
    )


@router.get("/metrics", response_model=dict)
async def get_escalation_metrics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ESCALATION_READ)),
):
    return await escalation_metrics.get_metrics(db, days=days)
