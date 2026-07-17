from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.audit_log import AuditLog
from app.models.global_setting import GlobalSetting
from app.services.ai.guardrails import get_injection_pattern_defs, reload_custom_patterns


async def _load_custom_list(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(GlobalSetting).where(GlobalSetting.key == "injection_patterns_custom"))
    row = result.scalar_one_or_none()
    return row.value if (row and isinstance(row.value, list)) else []


async def _save_custom_list(db: AsyncSession, items: list[dict]) -> None:
    await db.merge(GlobalSetting(key="injection_patterns_custom", value=items))
    await db.commit()
    await reload_custom_patterns(db)


async def list_patterns(db: AsyncSession) -> list[dict]:
    """Lista patrones (built-in + custom). Recarga custom al inicio."""
    await reload_custom_patterns(db)
    return get_injection_pattern_defs()


async def create_pattern(db: AsyncSession, *, regex: str, label: str, category: str, example: str, enabled: bool) -> dict:
    # Validar que el regex compile
    try:
        re.compile(regex)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Regex inválido: {e}")

    items = await _load_custom_list(db)
    pid = str(uuid.uuid4())
    entry = {
        "id": pid,
        "regex": regex,
        "label": label,
        "category": category,
        "example": example,
        "enabled": enabled,
    }
    items.append(entry)
    await _save_custom_list(db, items)
    return {"source": "custom", **entry}


async def update_pattern(db: AsyncSession, *, pattern_id: str, changes: dict) -> dict:
    items = await _load_custom_list(db)
    for it in items:
        if str(it.get("id")) == pattern_id:
            if "regex" in changes:
                try:
                    re.compile(changes["regex"])
                except re.error as e:
                    raise HTTPException(status_code=400, detail=f"Regex inválido: {e}")
            it.update(changes)
            await _save_custom_list(db, items)
            return {
                "source": "custom",
                "id": str(it["id"]), "regex": it["regex"], "label": it["label"],
                "category": it.get("category", "Custom"), "example": it.get("example", ""),
                "enabled": it.get("enabled", True),
            }
    raise NotFoundError("Patrón no encontrado")


async def delete_pattern(db: AsyncSession, *, pattern_id: str) -> None:
    items = await _load_custom_list(db)
    new_items = [it for it in items if str(it.get("id")) != pattern_id]
    if len(new_items) == len(items):
        raise NotFoundError("Patrón no encontrado (¿es built-in?)")
    await _save_custom_list(db, new_items)


async def pattern_impact(db: AsyncSession, *, pattern_id: str, days: int) -> dict:
    """Cuenta cuántos mensajes bloqueó este patrón en los últimos N días.

    Usa el `matched_label` registrado en `audit_log.meta_json` por el motor.
    """
    await reload_custom_patterns(db)
    defs = get_injection_pattern_defs()
    target = next((p for p in defs if p["id"] == pattern_id), None)
    if not target:
        raise NotFoundError("Patrón no encontrado")
    label = target["label"]

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.action == "guardrails.injection_detected")
        .where(AuditLog.created_at >= since)
        .where(func.json_unquote(AuditLog.meta_json["matched_label"]) == label)
    )
    blocks = int(result.scalar_one() or 0)
    return {"label": label, "days": days, "blocks": blocks}
