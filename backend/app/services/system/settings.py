from __future__ import annotations

import time
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cryptography.fernet import InvalidToken
from app.core.security import decrypt_secret_async, encrypt_secret_async
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.schemas.provider import ProviderCreate, ProviderOut, ProviderUpdate
from app.schemas.settings import ChatbotSettings

log = structlog.get_logger()

_DEFAULTS = ChatbotSettings().model_dump()


RUNTIME_DEFAULTS: dict = {
    "rate_limit_chat_per_min": 10,
    "rate_limit_chat_per_hour": 100,
    "semantic_cache_enabled": True,
    "semantic_cache_ttl": 43200,
    "semantic_cache_threshold": 0.90,
}
_RUNTIME_TTL_SECONDS = 60.0
_runtime_cache: tuple[float, dict] | None = None


async def get_runtime_overrides(db: AsyncSession) -> dict:
    """Valores efectivos de los ajustes de runtime desde GlobalSetting."""
    global _runtime_cache
    now = time.monotonic()
    if _runtime_cache is not None and now - _runtime_cache[0] < _RUNTIME_TTL_SECONDS:
        return _runtime_cache[1]

    effective = dict(RUNTIME_DEFAULTS)
    try:
        result = await db.execute(
            select(GlobalSetting).where(GlobalSetting.key.in_(tuple(effective)))
        )
        for row in result.scalars().all():
            if row.value is not None:
                default = effective[row.key]
                effective[row.key] = type(default)(row.value)
    except Exception as exc:
        log.warning("settings.runtime_overrides_load_failed", error=str(exc))

    _runtime_cache = (now, effective)
    return effective


def invalidate_runtime_overrides() -> None:
    """Fuerza la recarga inmediata tras un cambio desde el panel."""
    global _runtime_cache
    _runtime_cache = None


async def get_settings(db: AsyncSession) -> ChatbotSettings:
    result = await db.execute(select(GlobalSetting))
    rows = {r.key: r.value for r in result.scalars().all()}
    merged = {**_DEFAULTS, **rows}
    return ChatbotSettings(**{k: merged[k] for k in ChatbotSettings.model_fields if k in merged})


async def get_deployed_settings(db: AsyncSession) -> ChatbotSettings:
    """Returns the config from the last explicit deploy snapshot.

    Falls back to get_settings() if no deploy has been published yet,
    so the system works out-of-the-box before the first deployment.
    """
    from app.models.config_version import ConfigVersion
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        return await get_settings(db)
    snapshot = version.config_snapshot or {}
    sections = snapshot.get("sections", {})
    raw = sections.get("global_settings") or snapshot.get("global_settings") or {}
    merged = {**_DEFAULTS, **raw}
    return ChatbotSettings(**{k: merged[k] for k in ChatbotSettings.model_fields if k in merged})


async def update_settings(db: AsyncSession, data: ChatbotSettings, user_id: uuid.UUID) -> ChatbotSettings:
    # Auto-snapshot is now handled by VersioningMiddleware (post-response)
    for key, value in data.model_dump().items():
        existing = await db.get(GlobalSetting, key)
        if existing:
            existing.value = value
            existing.updated_by_id = user_id
        else:
            db.add(GlobalSetting(key=key, value=value, updated_by_id=user_id))
    await db.commit()
    log.info("settings.updated", user_id=str(user_id))
    return data


async def seed_default_settings(db: AsyncSession) -> None:
    """Siembra los ajustes editables desde el panel con los defaults del código.

    Los tamaños de chunk no se siembran: se leen siempre del .env porque
    cambiarlos exige reingestar todas las fuentes.
    """
    initial = {**_DEFAULTS, **RUNTIME_DEFAULTS}
    for key, value in initial.items():
        existing = await db.get(GlobalSetting, key)
        if existing is None:
            db.add(GlobalSetting(key=key, value=value))
    await db.commit()


def _to_out(p: LLMProvider) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        model_name=p.model_name,
        api_base=p.api_base,
        dashboard_url=p.dashboard_url,
        has_api_key=p.api_key_encrypted is not None,
        is_active=p.is_active,
        priority=p.priority,
        created_at=p.created_at,
        updated_at=p.updated_at,
        last_test_at=p.last_test_at,
        last_test_ok=p.last_test_ok,
        last_test_latency_ms=p.last_test_latency_ms,
        last_test_error=p.last_test_error,
    )


async def list_providers(db: AsyncSession) -> list[ProviderOut]:
    """Lista proveedores: primero los de la cadena (por prioridad), luego el resto."""
    result = await db.execute(
        select(LLMProvider).order_by(
            LLMProvider.priority.is_(None),   # nulls last
            LLMProvider.priority.asc(),
            LLMProvider.created_at.asc(),
        )
    )
    return [_to_out(p) for p in result.scalars().all()]


async def create_provider(db: AsyncSession, data: ProviderCreate) -> ProviderOut:
    if data.priority is not None:
        await _shift_priorities(db, data.priority, exclude_id=None)

    provider = LLMProvider(
        name=data.name,
        provider_type=data.provider_type,
        model_name=data.model_name,
        api_key_encrypted=await encrypt_secret_async(data.api_key) if data.api_key else None,
        api_base=data.api_base,
        dashboard_url=data.dashboard_url,
        is_active=data.is_active,
        priority=data.priority,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    log.info("provider.created", id=str(provider.id), name=provider.name)
    return _to_out(provider)


async def update_provider(db: AsyncSession, provider_id: uuid.UUID, data: ProviderUpdate) -> ProviderOut | None:
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        return None

    if data.name is not None:
        provider.name = data.name
    if data.provider_type is not None:
        provider.provider_type = data.provider_type
    if data.model_name is not None:
        provider.model_name = data.model_name
    if data.api_key is not None:
        provider.api_key_encrypted = await encrypt_secret_async(data.api_key) if data.api_key else None
    if data.api_base is not None:
        provider.api_base = data.api_base or None
    if "dashboard_url" in data.model_fields_set:
        provider.dashboard_url = data.dashboard_url or None
    if data.is_active is not None:
        provider.is_active = data.is_active

    # priority: None → quitar de la cadena; int → insertar/mover
    if "priority" in data.model_fields_set:
        if data.priority is not None:
            await _shift_priorities(db, data.priority, exclude_id=provider_id)
        provider.priority = data.priority

    await db.commit()
    await db.refresh(provider)
    log.info("provider.updated", id=str(provider.id))
    return _to_out(provider)


async def delete_provider(db: AsyncSession, provider_id: uuid.UUID) -> bool:
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        return False
    await db.delete(provider)
    await db.commit()
    log.info("provider.deleted", id=str(provider_id))
    return True


async def _safe_decrypt(encrypted: str | None, provider_name: str = "?") -> str | None:
    """Descifra la API key; devuelve None si el token es inválido (SECRET_KEY rotado)."""
    if not encrypted:
        return None
    try:
        return await decrypt_secret_async(encrypted)
    except InvalidToken:
        log.warning("settings.decrypt_key_failed", provider=provider_name,
                    hint="Re-save the API key in Configuración → Proveedores")
        return None


async def get_deployed_chain(db: AsyncSession) -> list[tuple[LLMProvider, str | None]]:
    """Cadena de proveedores según el último snapshot de deploy.

    Lee qué proveedores estaban activos y en qué prioridad al momento del
    último deploy. Las API keys se obtienen del registro vivo en DB (no del
    snapshot, donde están enmascaradas). Si un proveedor fue eliminado de DB
    después del deploy se omite; si la key no puede descifrarse también.

    Fallback: si no hay ningún deploy previo, delega a get_active_chain().
    """
    from app.models.config_version import ConfigVersion
    from sqlalchemy import select as _sel
    result = await db.execute(
        _sel(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        return await get_active_chain(db)

    snapshot = version.config_snapshot or {}
    sections = snapshot.get("sections", {})
    snap_providers = [
        p for p in sections.get("llm_providers", [])
        if p.get("is_active") and p.get("priority") is not None
    ]
    if not snap_providers:
        return []

    snap_providers.sort(key=lambda p: p["priority"])
    snap_ids = [uuid.UUID(p["id"]) for p in snap_providers]

    db_result = await db.execute(
        _sel(LLMProvider).where(LLMProvider.id.in_(snap_ids))
    )
    db_map = {str(p.id): p for p in db_result.scalars().all()}

    chain = []
    for snap in snap_providers:
        p = db_map.get(snap["id"])
        if p is None:
            log.warning("settings.deployed_provider_missing", provider_id=snap["id"], name=snap.get("name"))
            continue
        key = await _safe_decrypt(p.api_key_encrypted, p.name)
        if p.api_key_encrypted and key is None:
            continue  # key cifrada con SECRET_KEY distinto — saltar
        chain.append((p, key))
    return chain


async def get_active_chain(db: AsyncSession) -> list[tuple[LLMProvider, str | None]]:
    """
    Devuelve la cadena de proveedores activos ordenada por prioridad.
    Cada elemento es (provider, decrypted_api_key).
    Proveedores cuya key no puede descifrarse se omiten de la cadena.
    """
    result = await db.execute(
        select(LLMProvider)
        .where(LLMProvider.is_active.is_(True), LLMProvider.priority.is_not(None))
        .order_by(LLMProvider.priority.asc())
    )
    providers = result.scalars().all()
    chain = []
    for p in providers:
        key = await _safe_decrypt(p.api_key_encrypted, p.name)
        if p.api_key_encrypted and key is None:
            continue  # key cifrada con SECRET_KEY distinto — saltar proveedor
        chain.append((p, key))
    return chain


async def get_provider_with_key(db: AsyncSession, provider_id: uuid.UUID) -> tuple[LLMProvider, str | None] | None:
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        return None
    key = await _safe_decrypt(provider.api_key_encrypted, provider.name)
    return provider, key


async def _shift_priorities(db: AsyncSession, from_priority: int, exclude_id: uuid.UUID | None) -> None:
    """Desplaza hacia arriba todos los proveedores con priority >= from_priority para hacer hueco."""
    q = select(LLMProvider).where(LLMProvider.priority >= from_priority)
    if exclude_id:
        q = q.where(LLMProvider.id != exclude_id)
    result = await db.execute(q)
    for p in result.scalars().all():
        p.priority = (p.priority or 0) + 1


async def reorder_providers(db: AsyncSession, items: list[tuple[uuid.UUID, int | None]]) -> list[ProviderOut]:
    """Reordena en bulk la cadena de prioridad. Cada item es (id, priority|None).

    Útil para drag-and-drop: el frontend envía la lista completa con la prioridad
    objetivo y el backend la persiste atómicamente.
    """
    affected_ids = [i for i, _ in items]
    if affected_ids:
        result = await db.execute(select(LLMProvider).where(LLMProvider.id.in_(affected_ids)))
        for p in result.scalars().all():
            p.priority = None
        await db.flush()

    # Etapa 2: aplicar las prioridades nuevas
    for pid, prio in items:
        provider = await db.get(LLMProvider, pid)
        if provider is None:
            continue
        provider.priority = prio

    await db.commit()
    return await list_providers(db)


async def record_test_result(
    db: AsyncSession,
    provider_id: uuid.UUID,
    *,
    success: bool,
    latency_ms: int | None,
    error: str | None,
) -> None:
    """Persiste el resultado del último test en el modelo del proveedor."""
    from datetime import datetime, timezone
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        return
    provider.last_test_at = datetime.now(timezone.utc)
    provider.last_test_ok = success
    provider.last_test_latency_ms = latency_ms
    provider.last_test_error = (error or None) if not success else None
    await db.commit()
