from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import EscalationTrigger
from app.models.escalation_rule import EscalationRule
from app.models.user import User
from app.schemas.escalation import ChannelPingResult, RuleTestContext, RuleTestResult
from app.services.escalation.engine import evaluate_rule
from app.services.notifications.smtp import get_smtp_config, send_email


async def list_rules(db: AsyncSession) -> list[EscalationRule]:
    result = await db.execute(select(EscalationRule).order_by(EscalationRule.created_at))
    return list(result.scalars().all())


async def create_rule(db: AsyncSession, *, data: dict) -> EscalationRule:
    rule = EscalationRule(**data)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def update_rule(db: AsyncSession, *, rule_id: uuid.UUID, changes: dict) -> EscalationRule:
    result = await db.execute(select(EscalationRule).where(EscalationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Regla no encontrada")
    for k, v in changes.items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, *, rule_id: uuid.UUID) -> None:
    result = await db.execute(select(EscalationRule).where(EscalationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Regla no encontrada")
    await db.delete(rule)
    await db.commit()


async def ping_smtp(db: AsyncSession, *, current_user: User) -> ChannelPingResult:
    """Envía un email de prueba al usuario que lo solicita para verificar que
    SMTP está configurado y que los escalamientos llegarán correctamente."""
    ok = False
    ping_error: str | None = None
    latency_ms: int | None = None
    pinged_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    cfg = await get_smtp_config(db)
    if not cfg:
        ping_error = "SMTP no configurado en el servidor"
    else:
        from app.services.notifications import templates as tpl

        intro = "Este es un correo de prueba de las notificaciones de escalamiento."
        content = tpl.paragraph(intro)
        content += tpl.paragraph(
            "Si ha recibido este correo, los escalamientos llegarán correctamente a su bandeja."
        )
        sent = await send_email(
            to=current_user.email,
            subject="Prueba de notificación de escalamiento",
            body_html=tpl.render_email(
                title="Prueba de notificación de escalamiento", content=content, preheader=intro,
            ),
            _config=cfg,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        ok = sent
        if not sent:
            ping_error = "No se pudo enviar el correo de prueba. Revise la configuración SMTP."

    return ChannelPingResult(
        ok=ok,
        status=250 if ok else None,
        error=ping_error,
        latency_ms=latency_ms,
        pinged_at=pinged_at,
    )


async def test_rule(
    db: AsyncSession, *, rule_id: uuid.UUID | None, trigger_type: EscalationTrigger | None,
    trigger_config: dict | None, context: RuleTestContext,
) -> RuleTestResult:
    """Prueba una regla individual contra un contexto manual sin disparar canales."""
    if rule_id:
        result = await db.execute(select(EscalationRule).where(EscalationRule.id == rule_id))
        rule = result.scalar_one_or_none()
        if not rule:
            raise NotFoundError("Regla no encontrada")
        resolved_trigger_type = rule.trigger_type
        resolved_trigger_config = rule.trigger_config or {}
        rule_name = rule.name
    elif trigger_type is not None:
        resolved_trigger_type = trigger_type
        resolved_trigger_config = trigger_config or {}
        rule_name = "(inline)"
    else:
        raise HTTPException(status_code=400, detail="Debe especificar rule_id o trigger_type")

    matches, detail = evaluate_rule(
        trigger_type=resolved_trigger_type,
        trigger_config=resolved_trigger_config,
        context=context.model_dump(),
    )

    payload_preview = {
        "conversation_id": "test-conversation",
        "question": context.user_message or "(sin mensaje)",
        "reason": f"Trigger {resolved_trigger_type.value}: {rule_name}",
        "trigger_type": resolved_trigger_type.value,
        "matched": matches,
        "detail": detail,
    }

    return RuleTestResult(
        matches=matches,
        detail=detail,
        trigger_type=resolved_trigger_type,
        payload_preview=payload_preview,
    )
