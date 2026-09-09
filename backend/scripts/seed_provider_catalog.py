"""Siembra provider_type_catalog con los tipos de proveedor conocidos.

Valores corregidos según investigación real (no solo documentación oficial,
también artículos/issues confirmando comportamiento actual):
  - together: el listado real es /serverless-models, no /models.
  - cloudflare: requiere header cf-aig-gateway-id (se deja vacío para que el
    admin lo complete) y la URL necesita reemplazar {account_id}.
  - lepton: servicio descontinuado 20/05/2025 (adquirido por NVIDIA).
  - anyscale: acceso multi-tenant removido desde agosto de 2024.
  - infomaniak, ovhcloud: URLs con salvedades documentadas en notes.

Ejecutar una sola vez: python scripts/seed_provider_catalog.py
Es idempotente (upsert por type_key) - correrlo de nuevo actualiza defaults
sin duplicar filas ni pisar type_key que el admin haya renombrado.
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.provider_type_catalog import ProviderTypeCatalog

CATALOG: list[dict] = [
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
        "default_api_base": None,
        "notes": "URL local del servidor Ollama; se configura por instancia, no aquí.",
    },
    {
        "type_key": "lmstudio", "display_name": "LM Studio (local)",
        "default_api_base": None,
        "notes": "URL local del servidor LM Studio; se configura por instancia, no aquí.",
    },
    {
        "type_key": "vllm", "display_name": "vLLM (self-hosted)",
        "default_api_base": None,
        "notes": "vLLM rechaza con 400 los campos desconocidos en el payload (a diferencia de OpenAI/OpenRouter) - no forzar reasoning_effort sin confirmar soporte.",
    },
    {"type_key": "cerebras", "display_name": "Cerebras", "default_api_base": "https://api.cerebras.ai/v1"},
    {"type_key": "sambanova", "display_name": "SambaNova Cloud", "default_api_base": "https://api.sambanova.ai/v1"},
    {
        "type_key": "lepton", "display_name": "Lepton AI",
        "default_api_base": "https://api.lepton.ai/v1",
        "notes": "Servicio descontinuado el 20/05/2025 (adquirido por NVIDIA, relanzado como DGX Cloud Lepton). No usar para proveedores nuevos.",
    },
    {
        "type_key": "anyscale", "display_name": "Anyscale Endpoints",
        "default_api_base": "https://api.endpoints.anyscale.com/v1",
        "notes": "Acceso multi-tenant removido desde agosto de 2024. No usar para proveedores nuevos.",
    },
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


async def main() -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(ProviderTypeCatalog))).scalars().all()
        by_key = {row.type_key: row for row in existing}

        created, updated = 0, 0
        for item in CATALOG:
            row = by_key.get(item["type_key"])
            if row is None:
                row = ProviderTypeCatalog(
                    id=uuid.uuid4(),
                    type_key=item["type_key"],
                    display_name=item["display_name"],
                    default_api_base=item.get("default_api_base"),
                    default_headers=item.get("default_headers", {}),
                    models_endpoint_path=item.get("models_endpoint_path", "/models"),
                    is_builtin=True,
                    notes=item.get("notes"),
                )
                db.add(row)
                created += 1
            else:
                row.display_name = item["display_name"]
                row.default_api_base = item.get("default_api_base")
                row.default_headers = item.get("default_headers", {})
                row.models_endpoint_path = item.get("models_endpoint_path", "/models")
                row.notes = item.get("notes")
                updated += 1

        await db.commit()
        print(f"provider_type_catalog: {created} creados, {updated} actualizados.")


asyncio.run(main())
