from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


MAX_SUGGESTIONS = 6
MAX_SUGGESTION_LEN = 60
MAX_PROACTIVE_LEN = 200


class WidgetConfigUpdate(BaseModel):
    chatbot_name: str | None = Field(default=None, max_length=128)
    welcome_message: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = None
    position: str | None = Field(default=None, pattern="^(bottom-right|bottom-left|top-right|top-left)$")
    logo_url: str | None = Field(default=None, max_length=2048)
    domain_allowlist: list[str] | None = Field(default=None, max_length=50)
    show_sources: bool | None = None
    enable_copy_action: bool | None = None
    enable_feedback_icons: bool | None = None
    enable_tts: bool | None = None
    enable_accessibility: bool | None = None
    show_bot_icon: bool | None = None
    suggestions: list[str] | None = None
    proactive_message: str | None = Field(default=None, max_length=MAX_PROACTIVE_LEN)
    max_chats_per_session: int | None = Field(default=None, ge=1, le=100000)
    max_chats_per_day: int | None = Field(default=None, ge=1, le=100000)
    show_end_chat_button: bool | None = None
    show_new_chat_button: bool | None = None
    enable_csat: bool | None = None
    csat_question: str | None = Field(default=None, max_length=200)
    enable_escalation: bool | None = None
    launcher_label: str | None = Field(default=None, max_length=80)

    @field_validator("primary_color")
    @classmethod
    def _validate_primary_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _HEX_RE.match(v.strip()):
            raise ValueError("primary_color debe ser un color hexadecimal válido (ej. #1E40AF)")
        raw = _HEX_RE.match(v.strip()).group(1)  # type: ignore[union-attr]
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        return f"#{raw.lower()}"

    @field_validator("logo_url")
    @classmethod
    def _validate_logo_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("https://", "http://", "/")):
            raise ValueError("El logo debe ser una dirección web (https://…) o una ruta del sitio (/…).")
        return v

    @field_validator("domain_allowlist")
    @classmethod
    def _validate_domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = [d.strip() for d in v if d and d.strip()]
        if any(len(d) > 253 for d in cleaned):
            raise ValueError("Cada dominio permitido debe tener como máximo 253 caracteres.")
        return cleaned

    @field_validator("suggestions")
    @classmethod
    def _validate_suggestions(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        for s in v:
            t = (s or "").strip()
            if not t or t in seen:
                continue
            if len(t) > MAX_SUGGESTION_LEN:
                t = t[:MAX_SUGGESTION_LEN]
            cleaned.append(t)
            seen.add(t)
            if len(cleaned) >= MAX_SUGGESTIONS:
                break
        return cleaned


class WidgetConfigOut(BaseModel):
    id: uuid.UUID
    api_key: str
    chatbot_name: str
    welcome_message: str
    primary_color: str
    position: str
    logo_url: str | None
    domain_allowlist: list[str]
    show_sources: bool
    enable_copy_action: bool
    enable_feedback_icons: bool
    enable_tts: bool
    enable_accessibility: bool
    show_bot_icon: bool
    suggestions: list[str]
    proactive_message: str
    max_chats_per_session: int | None
    max_chats_per_day: int | None
    show_end_chat_button: bool
    show_new_chat_button: bool
    enable_csat: bool
    csat_question: str
    enable_escalation: bool
    launcher_label: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class WidgetPublicConfigOut(BaseModel):
    """Solo campos seguros - sin api_key, sin domain_allowlist, sin id."""
    chatbot_name: str
    welcome_message: str
    primary_color: str
    position: str
    logo_url: str | None
    show_sources: bool
    enable_copy_action: bool
    enable_feedback_icons: bool
    enable_tts: bool = True
    enable_accessibility: bool = True
    show_bot_icon: bool
    suggestions: list[str]
    proactive_message: str
    show_end_chat_button: bool
    show_new_chat_button: bool
    enable_csat: bool
    csat_question: str
    csat_reasons: dict[str, str] = {}
    enable_escalation: bool = True
    launcher_label: str
    max_input_chars: int = 4000

    model_config = {"from_attributes": True}


class EmbedCodeOut(BaseModel):
    script_tag: str
    api_key: str
