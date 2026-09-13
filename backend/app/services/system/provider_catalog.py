from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_type_catalog import ProviderTypeCatalog
from app.schemas.provider_type_catalog import (
    ProviderTypeCatalogCreate,
    ProviderTypeCatalogOut,
    ProviderTypeCatalogUpdate,
)

log = structlog.get_logger()

# lepton y anyscale quedan fuera a propósito: descontinuados (lepton desde
# 20/05/2025, adyacente a la adquisición por NVIDIA; anyscale perdió el
# acceso multi-tenant en agosto de 2024) - no tiene sentido sembrarlos como
# opción elegible en el panel.
_BUILTIN_CATALOG: list[dict] = [
    {"type_key": "openai", "display_name": "OpenAI", "default_api_base": "https://api.openai.com/v1"},
    {"type_key": "groq", "display_name": "Groq", "default_api_base": "https://api.groq.com/openai/v1"},
    {"type_key": "openrouter", "display_name": "OpenRouter", "default_api_base": "https://openrouter.ai/api/v1"},
    {"type_key": "deepseek", "display_name": "DeepSeek", "default_api_base": "https://api.deepseek.com/v1"},
    {
        "type_key": "together", "display_name": "Together AI",
        "default_api_base": "https://api.together.xyz/v1",
        "models_endpoint_path": "/serverless-models",
        "notes": "El endpoint de listado de modelos es /serverless-models, no /models.",
    },
    {"type_key": "xai", "display_name": "xAI (Grok)", "default_api_base": "https://api.x.ai/v1"},
    {"type_key": "mistral", "display_name": "Mistral AI", "default_api_base": "https://api.mistral.ai/v1"},
    {"type_key": "fireworks", "display_name": "Fireworks AI", "default_api_base": "https://api.fireworks.ai/inference/v1"},
    {"type_key": "perplexity", "display_name": "Perplexity", "default_api_base": "https://api.perplexity.ai"},
    {
        "type_key": "ollama", "display_name": "Ollama (local)",
        "default_api_base": None, "is_local": True,
        "notes": "URL local del servidor Ollama; se configura por instancia, no aquí.",
    },
    {
        "type_key": "lmstudio", "display_name": "LM Studio (local)",
        "default_api_base": None, "is_local": True,
        "notes": "URL local del servidor LM Studio; se configura por instancia, no aquí.",
    },
    {
        "type_key": "vllm", "display_name": "vLLM (self-hosted)",
        "default_api_base": None, "is_local": True,
        "notes": "vLLM rechaza con 400 los campos desconocidos en el payload (a diferencia de OpenAI/OpenRouter) - no forzar reasoning_effort sin confirmar soporte.",
    },
    {"type_key": "cerebras", "display_name": "Cerebras", "default_api_base": "https://api.cerebras.ai/v1"},
    {"type_key": "sambanova", "display_name": "SambaNova Cloud", "default_api_base": "https://api.sambanova.ai/v1"},
    {
        "type_key": "ovhcloud", "display_name": "OVHcloud AI Endpoints",
        "default_api_base": "https://llama-3-1-70b-instruct.endpoints.kepler.ai.cloud.ovh.net/api/openai_compat/v1",
        "notes": "El catálogo real de modelos vive en un endpoint público separado (catalog.endpoints.ai.ovh.net/rest/v1/models_v2), distinto del endpoint de inferencia. La detección automática de modelos puede no funcionar sin ajustar la URL por despliegue.",
    },
    {"type_key": "nvidia", "display_name": "NVIDIA NIM", "default_api_base": "https://integrate.api.nvidia.com/v1"},
    {
        "type_key": "cloudflare", "display_name": "Cloudflare Workers AI",
        "default_api_base": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "default_headers": {"cf-aig-gateway-id": ""},
        "notes": "Reemplaza {account_id} en la URL por el ID de cuenta real. Requiere el header cf-aig-gateway-id con el ID del gateway del admin (dejar vacío rompe la petición).",
    },
    {"type_key": "hyperbolic", "display_name": "Hyperbolic", "default_api_base": "https://api.hyperbolic.xyz/v1"},
    {"type_key": "nebius", "display_name": "Nebius AI Studio", "default_api_base": "https://api.studio.nebius.ai/v1"},
    {
        "type_key": "infomaniak", "display_name": "Infomaniak AI Tools",
        "default_api_base": "https://api.ai.infomaniak.com/v1",
        "notes": "La API real de Infomaniak parece requerir un product_id en el path (/1/ai/{product_id}/...). Verificar y ajustar la URL por despliegue antes de usar.",
    },
    {"type_key": "scaleway", "display_name": "Scaleway Generative APIs", "default_api_base": "https://api.scaleway.ai/v1"},
    {"type_key": "anthropic", "display_name": "Anthropic", "default_api_base": "https://api.anthropic.com"},
    {"type_key": "gemini", "display_name": "Google Gemini", "default_api_base": "https://generativelanguage.googleapis.com/v1beta"},
    {"type_key": "cohere", "display_name": "Cohere", "default_api_base": "https://api.cohere.com/v2"},
]


async def seed_provider_catalog(db: AsyncSession) -> None:
    """Siembra/actualiza los tipos de proveedor conocidos al arrancar.

    Idempotente (upsert por type_key): no duplica filas ni pisa un type_key
    que el admin haya renombrado a mano.
    """
    existing = (await db.execute(select(ProviderTypeCatalog))).scalars().all()
    by_key = {row.type_key: row for row in existing}

    for item in _BUILTIN_CATALOG:
        row = by_key.get(item["type_key"])
        if row is None:
            db.add(ProviderTypeCatalog(
                id=uuid.uuid4(),
                type_key=item["type_key"],
                display_name=item["display_name"],
                default_api_base=item.get("default_api_base"),
                default_headers=item.get("default_headers", {}),
                models_endpoint_path=item.get("models_endpoint_path", "/models"),
                is_builtin=True,
                is_local=item.get("is_local", False),
                notes=item.get("notes"),
            ))
        else:
            row.display_name = item["display_name"]
            row.default_api_base = item.get("default_api_base")
            row.default_headers = item.get("default_headers", {})
            row.models_endpoint_path = item.get("models_endpoint_path", "/models")
            row.is_local = item.get("is_local", False)
            row.notes = item.get("notes")

    await db.commit()


def _to_out(row: ProviderTypeCatalog) -> ProviderTypeCatalogOut:
    return ProviderTypeCatalogOut.model_validate(row)


async def list_types(db: AsyncSession) -> list[ProviderTypeCatalogOut]:
    result = await db.execute(
        select(ProviderTypeCatalog).order_by(ProviderTypeCatalog.display_name.asc())
    )
    return [_to_out(r) for r in result.scalars().all()]


async def get_type_by_key(db: AsyncSession, type_key: str) -> ProviderTypeCatalog | None:
    result = await db.execute(
        select(ProviderTypeCatalog).where(ProviderTypeCatalog.type_key == type_key)
    )
    return result.scalars().first()


async def create_type(db: AsyncSession, data: ProviderTypeCatalogCreate) -> ProviderTypeCatalogOut:
    row = ProviderTypeCatalog(
        type_key=data.type_key,
        display_name=data.display_name,
        default_api_base=data.default_api_base,
        default_headers=data.default_headers,
        models_endpoint_path=data.models_endpoint_path,
        is_local=data.is_local,
        notes=data.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"Ya existe un tipo de proveedor con la clave '{data.type_key}'.") from exc
    await db.refresh(row)
    log.info("provider_type_catalog.created", id=str(row.id), type_key=row.type_key)
    return _to_out(row)


async def update_type(
    db: AsyncSession, catalog_id: uuid.UUID, data: ProviderTypeCatalogUpdate,
) -> ProviderTypeCatalogOut | None:
    row = await db.get(ProviderTypeCatalog, catalog_id)
    if not row:
        return None

    if data.type_key is not None:
        row.type_key = data.type_key
    if data.display_name is not None:
        row.display_name = data.display_name
    if "default_api_base" in data.model_fields_set:
        row.default_api_base = data.default_api_base or None
    if data.default_headers is not None:
        row.default_headers = data.default_headers
    if data.models_endpoint_path is not None:
        row.models_endpoint_path = data.models_endpoint_path
    if data.is_local is not None:
        row.is_local = data.is_local
    if "notes" in data.model_fields_set:
        row.notes = data.notes or None

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"Ya existe un tipo de proveedor con la clave '{data.type_key}'.") from exc
    await db.refresh(row)
    log.info("provider_type_catalog.updated", id=str(row.id))
    return _to_out(row)


async def delete_type(db: AsyncSession, catalog_id: uuid.UUID) -> bool:
    row = await db.get(ProviderTypeCatalog, catalog_id)
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    log.info("provider_type_catalog.deleted", id=str(catalog_id))
    return True
