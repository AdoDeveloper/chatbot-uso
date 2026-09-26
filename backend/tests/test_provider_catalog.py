"""Catálogo de tipos de proveedor: siembra, edición y cabeceras."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.provider_type_catalog import ProviderTypeCatalog
from app.schemas.provider_type_catalog import ProviderTypeCatalogUpdate
from app.services.ai import llm_gateway
from app.services.system import provider_catalog as svc


async def _cloudflare(db) -> ProviderTypeCatalog:
    return (await db.execute(
        select(ProviderTypeCatalog).where(ProviderTypeCatalog.type_key == "cloudflare")
    )).scalar_one()


async def test_seed_keeps_what_the_admin_edited(db_session):
    await svc.seed_provider_catalog(db_session)
    row = await _cloudflare(db_session)
    await svc.update_type(db_session, row.id, ProviderTypeCatalogUpdate(
        default_headers={"cf-aig-gateway-id": "mi-gateway"},
    ))

    await svc.seed_provider_catalog(db_session)
    await db_session.refresh(row)

    assert row.default_headers == {"cf-aig-gateway-id": "mi-gateway"}


async def test_builtin_type_key_cannot_be_renamed(db_session):
    await svc.seed_provider_catalog(db_session)
    row = await _cloudflare(db_session)

    with pytest.raises(ValueError, match="no puede cambiarse"):
        await svc.update_type(db_session, row.id, ProviderTypeCatalogUpdate(type_key="cf"))


async def test_catalog_headers_apply_even_with_an_explicit_base(monkeypatch):
    class _Entry:
        default_api_base = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        default_headers = {"cf-aig-gateway-id": "mi-gateway"}

    async def _fake_entry(_type_key):
        return _Entry()

    monkeypatch.setattr(llm_gateway, "_resolve_catalog_entry", _fake_entry)

    base, headers = await llm_gateway._resolve_base_and_headers(
        "cloudflare", "https://api.cloudflare.com/client/v4/accounts/abc/ai/v1",
    )

    assert base.endswith("/accounts/abc/ai/v1")
    assert headers == {"cf-aig-gateway-id": "mi-gateway"}
