from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.global_setting import GlobalSetting

_SETTING_KEY = "csat_reasons"

_DEFAULT_REASONS: list[dict] = [
    {"id": "helpful_answer", "label": "Respuesta útil a mi consulta", "enabled": True},
    {"id": "fast_response", "label": "Rapidez para obtener una respuesta", "enabled": True},
    {"id": "clear_communication", "label": "Claridad de la comunicación", "enabled": True},
    {"id": "no_solution", "label": "No obtuve una solución", "enabled": True},
]


async def _load(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(GlobalSetting).where(GlobalSetting.key == _SETTING_KEY))
    row = result.scalar_one_or_none()
    if row and isinstance(row.value, list) and row.value:
        return row.value
    return [dict(r) for r in _DEFAULT_REASONS]


async def _save(db: AsyncSession, items: list[dict]) -> None:
    await db.merge(GlobalSetting(key=_SETTING_KEY, value=items))
    await db.commit()


async def list_reasons(db: AsyncSession, *, only_enabled: bool = False) -> list[dict]:
    items = await _load(db)
    if only_enabled:
        return [r for r in items if r.get("enabled", True)]
    return items


async def create_reason(db: AsyncSession, *, label: str, enabled: bool = True) -> dict:
    items = await _load(db)
    entry = {"id": str(uuid.uuid4()), "label": label, "enabled": enabled}
    items.append(entry)
    await _save(db, items)
    return entry


async def update_reason(db: AsyncSession, *, reason_id: str, changes: dict) -> dict:
    items = await _load(db)
    for it in items:
        if str(it.get("id")) == reason_id:
            it.update(changes)
            await _save(db, items)
            return it
    raise NotFoundError("Motivo no encontrado")


async def delete_reason(db: AsyncSession, *, reason_id: str) -> None:
    items = await _load(db)
    new_items = [it for it in items if str(it.get("id")) != reason_id]
    if len(new_items) == len(items):
        raise NotFoundError("Motivo no encontrado")
    await _save(db, new_items)


async def reorder_reasons(db: AsyncSession, *, ordered_ids: list[str]) -> list[dict]:
    items = await _load(db)
    by_id = {str(it["id"]): it for it in items}
    missing = [i for i in ordered_ids if i not in by_id]
    if missing or len(ordered_ids) != len(items):
        raise NotFoundError("La lista de orden no coincide con los motivos existentes")
    new_items = [by_id[i] for i in ordered_ids]
    await _save(db, new_items)
    return new_items


async def valid_ids(db: AsyncSession) -> set[str]:
    return {str(r["id"]) for r in await list_reasons(db, only_enabled=True)}


async def labels_map(db: AsyncSession) -> dict[str, str]:
    return {str(r["id"]): r["label"] for r in await list_reasons(db)}
