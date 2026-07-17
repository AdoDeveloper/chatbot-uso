"""
Whole-system versioning service.
Captures full chatbot state as JSONB snapshots (append-only).
Supports diff, change summaries, and rollback.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config_version import ConfigVersion
from app.models.escalation_rule import EscalationRule
from app.models.faq_entry import FAQEntry
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.models.notification_rule import NotificationRule
from app.models.source import Source
from app.models.widget_config import WidgetConfig

log = structlog.get_logger()

SCHEMA_VERSION = 2

# Settings keys that contain secrets — masked in snapshots
_SECRET_KEYS = frozenset({
    "smtp_password",
    "oauth_client_id", "oauth_client_secret",
})

# Human-readable labels for notable settings (Spanish)
_SETTING_LABELS = {
    "system_prompt": "system prompt",
    "chatbot_name": "nombre del chatbot",
    "welcome_message": "mensaje de bienvenida",
    "temperature": "temperature",
    "top_k": "top_k",
    "max_tokens": "max_tokens",
    "score_threshold": "umbral de relevancia",
    "use_corrective_rag": "RAG correctivo",
    "use_reranker": "reranker",
    "chunk_parent_size": "tamaño chunk padre",
    "chunk_child_size": "tamaño chunk hijo",
    "guardrails_enabled": "guardrails",
    "semantic_cache_enabled": "cache semántico",
    "rate_limit_chat_per_min": "rate limits",
}

_SECTION_LABELS = {
    "global_settings": "configuración",
    "llm_providers": "proveedores LLM",
    "widget_config": "widget",
    "escalation_rules": "reglas de escalamiento",
    "escalation_channels": "canales de escalamiento",
    "notification_rules": "notificaciones",
    "sources": "fuentes",
    "faq_entries": "FAQ",
}


async def _collect_global_settings(db: AsyncSession) -> dict:
    result = await db.execute(select(GlobalSetting))
    settings = {}
    for row in result.scalars().all():
        if row.key in _SECRET_KEYS:
            settings[row.key] = "[CONFIGURED]" if row.value else None
        else:
            settings[row.key] = row.value
    return settings


async def _collect_providers(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(LLMProvider).order_by(
            LLMProvider.priority.is_(None),
            LLMProvider.priority.asc(),
        )
    )
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "provider_type": p.provider_type,
            "model_name": p.model_name,
            "api_base": p.api_base,
            "is_active": p.is_active,
            "priority": p.priority,
            "has_api_key": bool(p.api_key_encrypted),
        }
        for p in result.scalars().all()
    ]


async def _collect_widget(db: AsyncSession) -> dict:
    result = await db.execute(select(WidgetConfig).limit(1))
    w = result.scalar_one_or_none()
    if not w:
        return {}
    return {
        "chatbot_name": w.chatbot_name,
        "welcome_message": w.welcome_message,
        "primary_color": w.primary_color,
        "position": w.position,
        "logo_url": w.logo_url,
        "domain_allowlist": w.domain_allowlist or [],
        "show_sources": w.show_sources,
        "enable_copy_action": w.enable_copy_action,
        "enable_feedback_icons": w.enable_feedback_icons,
        "show_bot_icon": w.show_bot_icon,
        "suggestions": w.suggestions or [],
        "proactive_message": w.proactive_message or "",
        "max_chats_per_session": w.max_chats_per_session,
        "max_chats_per_day": w.max_chats_per_day,
        "show_end_chat_button": w.show_end_chat_button,
        "show_new_chat_button": w.show_new_chat_button,
        "enable_csat": w.enable_csat,
        "csat_question": w.csat_question,
        "launcher_label": w.launcher_label or "",
    }


async def _collect_escalation_rules(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(EscalationRule))
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "trigger_type": r.trigger_type.value if hasattr(r.trigger_type, "value") else str(r.trigger_type),
            "trigger_config": r.trigger_config if hasattr(r, "trigger_config") else {},
            "enabled": r.enabled,
        }
        for r in result.scalars().all()
    ]


async def _collect_notification_rules(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(NotificationRule))
    return [
        {
            "id": str(r.id),
            "event": r.event.value if hasattr(r.event, "value") else str(r.event),
            "channel": r.channel.value if hasattr(r.channel, "value") else str(r.channel),
            "enabled": r.enabled,
            "target": r.target,
            "config_json": r.config_json or {},
        }
        for r in result.scalars().all()
    ]


async def _collect_sources(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Source).where(Source.deleted_at.is_(None)).order_by(Source.created_at)
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "type": s.type.value if hasattr(s.type, "value") else str(s.type),
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            "chunk_count": s.chunk_count,
            "meta": s.meta or {},
            "created_by_id": str(s.created_by_id) if s.created_by_id else None,
        }
        for s in result.scalars().all()
    ]


async def _collect_faq_entries(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(FAQEntry).where(FAQEntry.deleted_at.is_(None)).order_by(FAQEntry.created_at)
    )
    return [
        {
            "id": str(f.id),
            "question": f.question,
            "answer": f.answer,
            "tags": f.tags or [],
            "is_active": f.is_active,
            "source_id": str(f.source_id) if f.source_id else None,
            "created_by_id": str(f.created_by_id) if f.created_by_id else None,
        }
        for f in result.scalars().all()
    ]


async def _collect_all(db: AsyncSession) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "global_settings": await _collect_global_settings(db),
            "llm_providers": await _collect_providers(db),
            "widget_config": await _collect_widget(db),
            "escalation_rules": await _collect_escalation_rules(db),
            "notification_rules": await _collect_notification_rules(db),
            "sources": await _collect_sources(db),
            "faq_entries": await _collect_faq_entries(db),
        },
    }


def _diff_kv(old: dict, new: dict) -> list[dict]:
    changes = []
    for key in sorted(set(old) | set(new)):
        ov, nv = old.get(key), new.get(key)
        if ov == nv:
            continue
        if ov is None:
            changes.append({"key": key, "action": "added", "new": nv})
        elif nv is None:
            changes.append({"key": key, "action": "removed", "old": ov})
        else:
            changes.append({"key": key, "action": "modified", "old": ov, "new": nv})
    return changes


def _name_field(section: str) -> str:
    return {"llm_providers": "name", "sources": "name", "faq_entries": "question",
            "escalation_rules": "name", "notification_rules": "event"}.get(section, "id")


def _diff_collection(old: list[dict], new: list[dict], section: str) -> list[dict]:
    nf = _name_field(section)
    old_map = {item["id"]: item for item in old}
    new_map = {item["id"]: item for item in new}
    changes = []

    for oid in old_map:
        if oid not in new_map:
            changes.append({"id": oid, "name": old_map[oid].get(nf, ""), "action": "removed"})

    for nid in new_map:
        if nid not in old_map:
            changes.append({"id": nid, "name": new_map[nid].get(nf, ""), "action": "added"})
        elif nid in old_map:
            field_changes = {}
            for field in new_map[nid]:
                if field == "id":
                    continue
                if old_map[nid].get(field) != new_map[nid][field]:
                    field_changes[field] = [old_map[nid].get(field), new_map[nid][field]]
            if field_changes:
                changes.append({"id": nid, "name": new_map[nid].get(nf, ""), "action": "modified", "changes": field_changes})

    return changes


def compute_diff(old_snapshot: dict | None, new_snapshot: dict) -> dict[str, list[dict]]:
    if not old_snapshot or old_snapshot.get("schema_version") != SCHEMA_VERSION:
        old_sections = {"global_settings": old_snapshot or {}} if old_snapshot else {}
    else:
        old_sections = old_snapshot.get("sections", {})

    new_sections = new_snapshot.get("sections", {})
    result: dict[str, list[dict]] = {}

    for section in ("global_settings", "widget_config"):
        result[section] = _diff_kv(
            old_sections.get(section, {}),
            new_sections.get(section, {}),
        )

    for section in ("llm_providers", "escalation_rules", "escalation_channels",
                     "notification_rules", "sources", "faq_entries"):
        result[section] = _diff_collection(
            old_sections.get(section, []),
            new_sections.get(section, []),
            section,
        )

    return result


def generate_change_summary(diff: dict) -> str:
    parts: list[str] = []

    gs = diff.get("global_settings", [])
    if gs:
        notable = [_SETTING_LABELS[c["key"]] for c in gs if c["key"] in _SETTING_LABELS]
        other = sum(1 for c in gs if c["key"] not in _SETTING_LABELS)
        if notable:
            parts.append(f"Modificó {', '.join(notable[:4])}")
        if other:
            parts.append(f"actualizó {other} ajuste(s)")

    wc = diff.get("widget_config", [])
    if wc:
        fields = [c["key"] for c in wc[:3]]
        parts.append(f"actualizó widget: {', '.join(fields)}")

    for section in ("llm_providers", "escalation_rules", "escalation_channels",
                     "notification_rules", "sources", "faq_entries"):
        changes = diff.get(section, [])
        if not changes:
            continue
        label = _SECTION_LABELS.get(section, section)
        added = [c for c in changes if c["action"] == "added"]
        removed = [c for c in changes if c["action"] == "removed"]
        modified = [c for c in changes if c["action"] == "modified"]
        sub = []
        if added:
            names = [c.get("name", "")[:30] for c in added[:2] if c.get("name")]
            sub.append(f"agregó {', '.join(names) if names else f'{len(added)} {label}'}")
        if removed:
            sub.append(f"eliminó {len(removed)} {label}")
        if modified:
            sub.append(f"modificó {len(modified)} {label}")
        parts.extend(sub)

    if not parts:
        return "Sin cambios detectados"
    summary = "; ".join(parts)
    return summary[0].upper() + summary[1:]


async def _next_version(db: AsyncSession) -> int:
    result = await db.execute(
        select(sa_func.coalesce(sa_func.max(ConfigVersion.version_number), 0))
    )
    return result.scalar_one() + 1


async def _get_active_version(db: AsyncSession) -> ConfigVersion | None:
    result = await db.execute(
        select(ConfigVersion).where(ConfigVersion.is_active.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def capture_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    description: str = "",
    trigger_source: str = "manual",
    force: bool = False,
) -> ConfigVersion | None:
    """
    Capture the entire system state. Returns None if no changes detected.

    force=True skips the dedup check against the latest active snapshot so
    a deploy-tagged version is always created when there are changes vs the
    last deployed version (even if an old auto-snapshot already matches).
    """
    snapshot = await _collect_all(db)

    parent = await _get_active_version(db)
    parent_snapshot = parent.config_snapshot if parent else None

    diff = compute_diff(parent_snapshot, snapshot)
    has_changes = any(changes for changes in diff.values())
    if not has_changes and not force:
        log.debug("versioning.no_changes", trigger_source=trigger_source)
        return None

    summary = generate_change_summary(diff)
    if not description:
        description = summary

    # Deactivate previous active
    if parent:
        parent.is_active = False

    version = ConfigVersion(
        version_number=await _next_version(db),
        description=description,
        config_snapshot=snapshot,
        is_active=True,
        snapshot_schema_version=SCHEMA_VERSION,
        change_summary=summary,
        trigger_source=trigger_source,
        parent_version_id=parent.id if parent else None,
        created_by_id=user_id,
    )
    db.add(version)
    await db.flush()

    log.info("versioning.snapshot_created",
             version=version.version_number, trigger=trigger_source, summary=summary[:100])
    return version


async def get_published_widget_config(db: AsyncSession) -> dict | None:
    """Returns the widget_config section from the last deploy snapshot.

    Returns None if no deploy has happened yet — callers should fall back
    to the live WidgetConfig table in that case.
    """
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        return None
    snapshot = version.config_snapshot or {}
    sections = snapshot.get("sections", {})
    return sections.get("widget_config") or snapshot.get("widget_config") or None


async def has_config_changed_since(db: AsyncSession, deployed_snapshot: dict) -> bool:
    """Compare current live config against a deployed snapshot (content-based, not row-count)."""
    current = await _collect_all(db)
    diff = compute_diff(deployed_snapshot, current)
    return any(changes for changes in diff.values())


async def restore_snapshot(
    db: AsyncSession,
    *,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[ConfigVersion, list[str]]:
    """
    Restore system state from a snapshot. Returns (new_version, warnings).
    """
    target = await db.get(ConfigVersion, version_id)
    if not target:
        raise ValueError("Version not found")

    warnings: list[str] = []
    snapshot = target.config_snapshot

    # Handle v1 snapshots (flat key-value only)
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        warnings.append("Versión antigua (v1): solo se restaura configuración básica")
        for key, value in snapshot.items():
            if key == "schema_version":
                continue
            existing = await db.get(GlobalSetting, key)
            if existing:
                existing.value = value
                existing.updated_by_id = user_id
            else:
                db.add(GlobalSetting(key=key, value=value, updated_by_id=user_id))
    else:
        sections = snapshot["sections"]

        # Restore global_settings
        for key, value in sections.get("global_settings", {}).items():
            if value == "[CONFIGURED]":
                continue  # Don't overwrite secrets with mask
            existing = await db.get(GlobalSetting, key)
            if existing:
                existing.value = value
                existing.updated_by_id = user_id
            else:
                db.add(GlobalSetting(key=key, value=value, updated_by_id=user_id))

        # Restore widget_config
        wc_data = sections.get("widget_config", {})
        if wc_data:
            wc_result = await db.execute(select(WidgetConfig).limit(1))
            wc = wc_result.scalar_one_or_none()
            if wc:
                for field in ("chatbot_name", "welcome_message", "primary_color", "position",
                              "logo_url", "domain_allowlist", "show_sources",
                              "enable_copy_action", "enable_feedback_icons"):
                    if field in wc_data:
                        setattr(wc, field, wc_data[field])

        # Restore llm_providers (metadata only, not API keys)
        snap_providers = {p["id"]: p for p in sections.get("llm_providers", [])}
        db_result = await db.execute(select(LLMProvider))
        db_providers = {str(p.id): p for p in db_result.scalars().all()}

        for pid, pdata in snap_providers.items():
            if pid in db_providers:
                p = db_providers[pid]
                p.name = pdata["name"]
                p.provider_type = pdata["provider_type"]
                p.model_name = pdata["model_name"]
                p.api_base = pdata.get("api_base")
                p.is_active = pdata["is_active"]
                p.priority = pdata.get("priority")
            else:
                warnings.append(f"Proveedor '{pdata['name']}' restaurado sin API key — configurar manualmente")
                db.add(LLMProvider(
                    id=uuid.UUID(pid),
                    name=pdata["name"],
                    provider_type=pdata["provider_type"],
                    model_name=pdata["model_name"],
                    api_base=pdata.get("api_base"),
                    is_active=False,
                    priority=pdata.get("priority"),
                ))

        for pid, p in db_providers.items():
            if pid not in snap_providers:
                p.is_active = False
                p.priority = None

        # Restore notification_rules
        for nr_data in sections.get("notification_rules", []):
            nr_result = await db.execute(
                select(NotificationRule).where(NotificationRule.id == uuid.UUID(nr_data["id"]))
            )
            nr = nr_result.scalar_one_or_none()
            if nr:
                nr.enabled = nr_data["enabled"]
                nr.target = nr_data.get("target")

    # Create rollback version
    new_snapshot = await _collect_all(db)
    parent = await _get_active_version(db)
    if parent:
        parent.is_active = False

    rollback_version = ConfigVersion(
        version_number=await _next_version(db),
        description=f"Restauración a v{target.version_number}",
        config_snapshot=new_snapshot,
        is_active=True,
        snapshot_schema_version=SCHEMA_VERSION,
        change_summary=f"Restauración a v{target.version_number}",
        trigger_source="rollback",
        parent_version_id=target.id,
        created_by_id=user_id,
    )
    db.add(rollback_version)
    await db.flush()

    log.info("versioning.rollback", from_version=target.version_number, new_version=rollback_version.version_number)
    return rollback_version, warnings
