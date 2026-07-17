"""Guardrails configuration & injection log endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.common import OperationStatus
from app.services.ai.guardrails import validate_input, reload_custom_patterns
from app.services.system import guardrail_patterns as patterns_svc

router = APIRouter(prefix="/guardrails", tags=["system:guardrails"])
_reader = require_perm(P.SYSTEM_READ)
_admin  = require_perm(P.SYSTEM_MANAGE)


class InjectionPattern(BaseModel):
    id: str
    regex: str
    label: str
    category: str
    example: str
    source: str  # "builtin" | "custom"
    enabled: bool = True


class PatternCreate(BaseModel):
    regex: str = Field(..., min_length=1, max_length=500)
    label: str = Field(..., min_length=1, max_length=120)
    category: str = Field("Custom", min_length=1, max_length=80)
    example: str = Field("", max_length=300)
    enabled: bool = True


class PatternUpdate(BaseModel):
    regex: str | None = Field(None, min_length=1, max_length=500)
    label: str | None = Field(None, min_length=1, max_length=120)
    category: str | None = Field(None, min_length=1, max_length=80)
    example: str | None = Field(None, max_length=300)
    enabled: bool | None = None


class PatternImpact(BaseModel):
    label: str
    days: int
    blocks: int


class GuardrailConfig(BaseModel):
    enabled: bool
    max_input_chars: int
    max_output_tokens: int
    pii_entities: list[str]
    injection_patterns_count: int


class GuardrailTestRequest(BaseModel):
    text: str


class GuardrailTestResponse(BaseModel):
    passed: bool
    reason: str
    sanitized_text: str
    matched_label: str | None = None
    matched_category: str | None = None
    matched_pattern: str | None = None


class InjectionLogEntry(BaseModel):
    id: str
    action: str
    ip: str | None
    meta_json: dict
    created_at: str


@router.get("/config", response_model=GuardrailConfig)
async def get_config(
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    from app.core.config import get_settings as get_app_settings
    from app.services.ai.guardrails import get_active_compiled_patterns
    s = get_app_settings()
    return GuardrailConfig(
        enabled=s.GUARDRAILS_ENABLED,
        max_input_chars=s.MAX_INPUT_CHARS,
        max_output_tokens=s.MAX_OUTPUT_TOKENS,
        pii_entities=["PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "IBAN_CODE"],
        injection_patterns_count=len(get_active_compiled_patterns()),
    )


@router.patch("/config", response_model=OperationStatus)
async def update_config(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
) -> OperationStatus:
    """Actualiza la configuración de guardrails (enabled, max chars, max tokens, PII).

    Solo persiste claves whitelisteadas para prevenir inyección en GlobalSetting.
    """
    from app.models.global_setting import GlobalSetting
    allowed = {"guardrails_enabled", "max_input_chars", "max_output_tokens", "pii_entities"}
    for k, v in body.items():
        if k in allowed:
            await db.merge(GlobalSetting(key=k, value=v))
    await db.commit()
    return OperationStatus()


@router.get("/patterns", response_model=list[InjectionPattern])
async def list_patterns(
    db: AsyncSession = Depends(get_db),
    _=Depends(_reader),
):
    """Lista patrones (built-in + custom). Recarga custom al inicio."""
    defs = await patterns_svc.list_patterns(db)
    return [InjectionPattern(**p) for p in defs]


@router.post("/patterns", response_model=InjectionPattern, status_code=201)
async def create_pattern(
    body: PatternCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    entry = await patterns_svc.create_pattern(
        db, regex=body.regex, label=body.label, category=body.category,
        example=body.example, enabled=body.enabled,
    )
    return InjectionPattern(**entry)


@router.patch("/patterns/{pattern_id}", response_model=InjectionPattern)
async def update_pattern(
    pattern_id: str,
    body: PatternUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    entry = await patterns_svc.update_pattern(db, pattern_id=pattern_id, changes=body.model_dump(exclude_unset=True))
    return InjectionPattern(**entry)


@router.delete("/patterns/{pattern_id}", response_model=OperationStatus)
async def delete_pattern(
    pattern_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
) -> OperationStatus:
    await patterns_svc.delete_pattern(db, pattern_id=pattern_id)
    return OperationStatus()


@router.get("/patterns/{pattern_id}/impact", response_model=PatternImpact)
async def pattern_impact(
    pattern_id: str,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    result = await patterns_svc.pattern_impact(db, pattern_id=pattern_id, days=days)
    return PatternImpact(**result)


@router.get("/injection-log", response_model=list[InjectionLogEntry])
async def get_injection_log(
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.action == "guardrails.injection_detected")
        .order_by(AuditLog.created_at.desc())
        .limit(page_size)
    )
    logs = result.scalars().all()
    return [
        InjectionLogEntry(
            id=str(log.id),
            action=log.action,
            ip=log.ip,
            meta_json=log.meta_json,
            created_at=str(log.created_at),
        )
        for log in logs
    ]


@router.post("/test", response_model=GuardrailTestResponse)
async def test_guardrails(
    body: GuardrailTestRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(_admin),
):
    """Prueba el motor con un texto. Retorna el patrón que matcheó (si alguno)."""
    # Refresca custom patterns por si se editaron desde otro proceso
    await reload_custom_patterns(db)
    result = validate_input(body.text)
    return GuardrailTestResponse(
        passed=result.passed,
        reason=result.reason,
        sanitized_text=result.sanitized_text,
        matched_label=result.matched_label,
        matched_category=result.matched_category,
        matched_pattern=result.matched_pattern,
    )
