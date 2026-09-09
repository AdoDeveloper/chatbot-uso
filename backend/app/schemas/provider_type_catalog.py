from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProviderTypeCatalogCreate(BaseModel):
    type_key: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=120)
    default_api_base: str | None = Field(None, max_length=512)
    default_headers: dict[str, str] = Field(default_factory=dict)
    models_endpoint_path: str = Field("/models", min_length=1, max_length=120)
    notes: str | None = None


class ProviderTypeCatalogUpdate(BaseModel):
    type_key: str | None = Field(None, min_length=1, max_length=50)
    display_name: str | None = Field(None, min_length=1, max_length=120)
    default_api_base: str | None = Field(None, max_length=512)
    default_headers: dict[str, str] | None = None
    models_endpoint_path: str | None = Field(None, min_length=1, max_length=120)
    notes: str | None = None


class ProviderTypeCatalogOut(BaseModel):
    id: uuid.UUID
    type_key: str
    display_name: str
    default_api_base: str | None
    default_headers: dict[str, str]
    models_endpoint_path: str
    is_builtin: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
