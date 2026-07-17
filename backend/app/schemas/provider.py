from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    # Texto libre: "openai", "anthropic", "groq", "gemini", "bedrock", "ollama", etc.
    provider_type: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=120)
    api_key: str | None = Field(None, description="Plaintext — will be encrypted before storage")
    api_base: str | None = Field(None, max_length=512)
    dashboard_url: str | None = Field(None, max_length=512)
    is_active: bool = True
    # None = fuera de cadena; 1 = principal; 2+ = fallback
    priority: int | None = Field(None, ge=1)


class ProviderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    provider_type: str | None = Field(None, min_length=1, max_length=50)
    model_name: str | None = Field(None, min_length=1, max_length=120)
    api_key: str | None = None    # None = sin cambio; "" = borrar clave
    api_base: str | None = None
    dashboard_url: str | None = None
    is_active: bool | None = None
    priority: int | None = Field(None, ge=1)  # None = quitar de la cadena


class ProviderTestRequest(BaseModel):
    """Prueba una conexión antes o después de guardar."""
    provider_type: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=120)
    api_key: str | None = None
    api_base: str | None = None


class ProviderTestResult(BaseModel):
    success: bool
    latency_ms: int | None = None
    error: str | None = None


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    model_name: str
    api_base: str | None
    dashboard_url: str | None
    has_api_key: bool
    is_active: bool
    priority: int | None
    created_at: datetime
    updated_at: datetime
    # Health-check
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_latency_ms: int | None = None
    last_test_error: str | None = None

    model_config = {"from_attributes": True}


class ProviderReorderItem(BaseModel):
    id: uuid.UUID
    priority: int | None = Field(None, ge=1)


class ProviderReorderRequest(BaseModel):
    items: list[ProviderReorderItem]


class ProviderModelsRequest(BaseModel):
    provider_type: str = Field(..., min_length=1, max_length=50)
    api_key: str | None = None
    api_base: str | None = None


class ProviderModelItem(BaseModel):
    id: str
    name: str


class ProviderModelsResult(BaseModel):
    models: list[ProviderModelItem]
