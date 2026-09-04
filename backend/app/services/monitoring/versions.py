"""
Whole-system versioning service.
Captures full chatbot state as JSONB snapshots (append-only).
Supports diff, change summaries, and rollback.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config_version import ConfigVersion
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.models.notification_rule import NotificationRule
from app.models.widget_config import WidgetConfig

log = structlog.get_logger()

SCHEMA_VERSION = 2

# Los locks del scheduler viven en global_settings con una clave que lleva un
# bucket temporal, así que aparecen y desaparecen solos: si entran al snapshot
# ensucian cada diff de configuración con entradas que nadie modificó.
_EPHEMERAL_KEY_PREFIX = "scheduler:"

# Claves de global_settings que definen el comportamiento del asistente. El
# resto de la tabla (rate limits, caché, agenda de reportes, OAuth) es
# operativo y no se versiona.
_ASSISTANT_SETTING_KEYS = frozenset({
    "system_prompt",
    "greeting_response",
    "temperature",
    "top_k",
    "max_tokens",
    "max_output_tokens",
    "max_input_chars",
    "score_threshold",
    "use_corrective_rag",
    "guardrails_enabled",
    "guardrail_blocked_message",
    "injection_patterns_custom",
    "pii_entities",
    "no_providers_message",
    "csat_reasons",
})

# Claves de configuración que contienen secretos - se enmascaran en los snapshots
_SECRET_KEYS = frozenset({
    "smtp_password",
    "oauth_client_id", "oauth_client_secret",
})

# Etiquetas legibles para settings relevantes (en español)
_SETTING_LABELS = {
    "system_prompt": "system prompt",
    "temperature": "temperature",
    "top_k": "top_k",
    "max_tokens": "max_tokens",
    "score_threshold": "umbral de relevancia",
    "use_corrective_rag": "RAG correctivo",
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
    result = await db.execute(
        select(GlobalSetting).where(
            ~GlobalSetting.key.like(f"{_EPHEMERAL_KEY_PREFIX}%")
        )
    )
    settings = {}
    for row in result.scalars().all():
        if row.key not in _ASSISTANT_SETTING_KEYS:
            continue
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
        "enable_escalation": w.enable_escalation,
        "enable_tts": w.enable_tts,
        "enable_accessibility": w.enable_accessibility,
    }


async def _collect_all(db: AsyncSession) -> dict:
    """Snapshot de la configuración del asistente.

    Se limita a lo que define cómo responde el chatbot. Quedan fuera los
    documentos y las FAQ (el rollback nunca los revirtió: solo avisaba) y las
    reglas de escalamiento y notificación, que son operativas.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "global_settings": await _collect_global_settings(db),
            "llm_providers": await _collect_providers(db),
            "widget_config": await _collect_widget(db),
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

    for oid, old_item in old_map.items():
        if oid not in new_map:
            changes.append({"id": oid, "name": old_item.get(nf, ""), "action": "removed"})

    for nid, new_item in new_map.items():
        if nid not in old_map:
            changes.append({"id": nid, "name": new_item.get(nf, ""), "action": "added"})
        elif nid in old_map:
            old_item = old_map[nid]
            field_changes = {}
            for field in new_item:
                if field == "id":
                    continue
                if old_item.get(field) != new_item[field]:
                    field_changes[field] = [old_item.get(field), new_item[field]]
            if field_changes:
                changes.append({"id": nid, "name": new_item.get(nf, ""), "action": "modified", "changes": field_changes})

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
    """Versión activa más reciente.

    Se ordena de forma explícita: sin ORDER BY, un `limit(1)` devuelve una fila
    arbitraria si por cualquier motivo hay más de una marcada como activa.
    """
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.is_active.is_(True))
        .order_by(ConfigVersion.version_number.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _get_last_deploy_version(db: AsyncSession) -> ConfigVersion | None:
    """Última versión con trigger_source='deploy', o None si nunca se publicó."""
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.trigger_source == "deploy")
        .order_by(ConfigVersion.version_number.desc())
        .limit(1)
    )
    return result.scalars().first()


class _VersioningLock:
    """Mutex distribuido para toda la sección crítica de capture_snapshot
    """

    _KEY = "versioning:capture_lock"

    async def __aenter__(self) -> bool:
        from app.core import redis as _redis_mod
        try:
            ok = await _redis_mod.get_redis().set(self._KEY, "1", ex=30, nx=True)
            self._acquired = bool(ok)
        except Exception:
            self._acquired = None  # Redis no disponible: no bloquear el versionado
        if self._acquired is False:
            import asyncio
            for _ in range(20):  # hasta ~2s
                await asyncio.sleep(0.1)
                try:
                    ok = await _redis_mod.get_redis().set(self._KEY, "1", ex=30, nx=True)
                except Exception:
                    self._acquired = None
                    break
                if ok:
                    self._acquired = True
                    break
        return self._acquired is not False

    async def __aexit__(self, *exc) -> None:
        if self._acquired:
            from app.core import redis as _redis_mod
            try:
                await _redis_mod.get_redis().delete(self._KEY)
            except Exception:
                pass


async def capture_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    description: str = "",
    trigger_source: str = "manual",
    force: bool = False,
) -> ConfigVersion | None:
    async with _VersioningLock() as acquired:
        # Sin el lock, dos capturas concurrentes leen el mismo número de
        # versión y desactivan cada una a un padre distinto: quedan dos
        # versiones con el mismo number y ambas activas.
        if not acquired:
            log.warning("versioning.skipped_no_lock", trigger_source=trigger_source)
            return None

        snapshot = await _collect_all(db)

        parent = await _get_active_version(db)

        diff_baseline = parent
        if trigger_source == "deploy":
            diff_baseline = await _get_last_deploy_version(db)
        diff_baseline_snapshot = diff_baseline.config_snapshot if diff_baseline else None

        diff = compute_diff(diff_baseline_snapshot, snapshot)
        has_changes = any(changes for changes in diff.values())
        if not has_changes and not force:
            log.debug("versioning.no_changes", trigger_source=trigger_source)
            return None

        summary = generate_change_summary(diff)
        if not description:
            description = summary

        # Desactiva todas las anteriores, no solo el padre: si quedara más de
        # una activa, apagar una sola dejaría el resto activas para siempre.
        await db.execute(
            update(ConfigVersion)
            .where(ConfigVersion.is_active.is_(True))
            .values(is_active=False)
        )

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

        await _prune_auto_snapshots(db)
        return version


# Snapshots automáticos a conservar; deploys y la versión activa quedan fuera de la poda.
MAX_AUTO_SNAPSHOTS = 50


async def _prune_auto_snapshots(db: AsyncSession) -> int:
    """Elimina los snapshots automáticos más antiguos que excedan el límite.

    No se excluyen las versiones referenciadas como padre: como cada versión
    apunta a la anterior, esa condición bloqueaba la cadena entera y la poda
    no borraba nada. La FK es ON DELETE SET NULL, así que los hijos quedan sin
    padre en vez de con una referencia rota, y el diff cae al comportamiento
    que ya usa para las versiones sin padre: comparar contra la anterior por
    número de versión.
    """
    candidates = list(await db.scalars(
        select(ConfigVersion.id)
        .where(ConfigVersion.trigger_source != "deploy")
        .where(ConfigVersion.is_active.is_(False))
        .order_by(ConfigVersion.created_at.desc())
    ))
    stale_ids = set(candidates[MAX_AUTO_SNAPSHOTS:])
    if not stale_ids:
        return 0

    await db.execute(delete(ConfigVersion).where(ConfigVersion.id.in_(stale_ids)))
    log.info("versioning.pruned", removed=len(stale_ids), kept=MAX_AUTO_SNAPSHOTS)
    return len(stale_ids)


async def get_published_widget_config(db: AsyncSession) -> dict | None:
    """Devuelve la configuración del widget publicada en el último deploy.
    """
    from app.services.system.settings import _latest_deploy_version
    version = await _latest_deploy_version(db)
    if version is None:
        return None
    snapshot = version.config_snapshot or {}
    sections = snapshot.get("sections", {})
    return sections.get("widget_config") or snapshot.get("widget_config") or None


async def get_public_widget_flag(db: AsyncSession, live_widget: WidgetConfig, flag: str) -> bool:
    """Resuelve un flag booleano del widget (enable_escalation, enable_csat,
    ...) con el mismo criterio que ve el público en GET /widget/public/config:
    la config PUBLICADA si existe (mismo fallback que public_config: sin
    deploy previo, usa la fila viva). Evita que el backend evalúe/acepte
    solicitudes contra un valor distinto al que el widget anuncia - p. ej.
    un admin que cambia el toggle en vivo sin republicar dejaba el botón del
    widget visible/oculto según lo publicado, pero el endpoint real
    aceptaba o rechazaba según la fila viva, desincronizados entre sí.
    """
    published = await get_published_widget_config(db)
    if published is not None:
        return bool(published.get(flag, True))
    return bool(getattr(live_widget, flag, True))


async def has_config_changed_since(db: AsyncSession, deployed_snapshot: dict) -> bool:
    """Compara la configuración actual con un snapshot desplegado."""
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
    Restaura el estado del sistema a partir de un snapshot. Devuelve (nueva_version, advertencias).
    """
    target = await db.get(ConfigVersion, version_id)
    if not target:
        raise ValueError("Version not found")

    warnings: list[str] = []
    snapshot = target.config_snapshot

    # Maneja snapshots v1 (solo clave-valor plano)
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        warnings.append("Versión antigua (v1): solo se restaura configuración básica")
        for key, value in snapshot.items():
            if key == "schema_version" or key.startswith(_EPHEMERAL_KEY_PREFIX):
                continue
            existing = await db.get(GlobalSetting, key)
            if existing:
                existing.value = value
                existing.updated_by_id = user_id
            else:
                db.add(GlobalSetting(key=key, value=value, updated_by_id=user_id))
    else:
        sections = snapshot["sections"]

        # Restaura global_settings
        for key, value in sections.get("global_settings", {}).items():
            if value == "[CONFIGURED]":
                continue  # No sobrescribir secretos con la máscara
            if key.startswith(_EPHEMERAL_KEY_PREFIX):
                continue  # Snapshots antiguos pueden traer locks del scheduler
            existing = await db.get(GlobalSetting, key)
            if existing:
                existing.value = value
                existing.updated_by_id = user_id
            else:
                db.add(GlobalSetting(key=key, value=value, updated_by_id=user_id))

        # Restaura widget_config
        wc_data = sections.get("widget_config", {})
        if wc_data:
            wc_result = await db.execute(select(WidgetConfig).limit(1))
            wc = wc_result.scalar_one_or_none()
            if wc:
                for field in ("chatbot_name", "welcome_message", "primary_color", "position",
                              "logo_url", "domain_allowlist", "show_sources",
                              "enable_copy_action", "enable_feedback_icons",
                              "show_bot_icon", "suggestions", "proactive_message",
                              "max_chats_per_session", "max_chats_per_day",
                              "show_end_chat_button", "show_new_chat_button",
                              "enable_csat", "csat_question", "launcher_label"):
                    if field in wc_data:
                        setattr(wc, field, wc_data[field])

        # Restaura llm_providers (solo metadata, no las API keys)
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
                warnings.append(f"Proveedor '{pdata['name']}' restaurado sin API key - configurar manualmente")
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

        # Restaura notification_rules
        for nr_data in sections.get("notification_rules", []):
            nr_result = await db.execute(
                select(NotificationRule).where(NotificationRule.id == uuid.UUID(nr_data["id"]))
            )
            nr = nr_result.scalar_one_or_none()
            if nr:
                nr.enabled = nr_data["enabled"]
                nr.target = nr_data.get("target")
                nr.config_json = nr_data.get("config_json") or {}
            else:
                db.add(NotificationRule(
                    id=uuid.UUID(nr_data["id"]),
                    event=nr_data["event"],
                    channel=nr_data["channel"],
                    enabled=nr_data["enabled"],
                    target=nr_data.get("target"),
                    config_json=nr_data.get("config_json") or {},
                ))
        if sections.get("escalation_rules"):
            warnings.append("Las reglas de escalamiento no se revierten - solo configuración del asistente, widget y proveedores")
        if sections.get("sources"):
            warnings.append("Las fuentes de conocimiento no se revierten - el rollback no elimina ni restaura documentos")
        if sections.get("faq_entries"):
            warnings.append("Las preguntas frecuentes (FAQ) no se revierten")

    # Crea la versión de rollback
    new_snapshot = await _collect_all(db)
    await db.execute(
        update(ConfigVersion)
        .where(ConfigVersion.is_active.is_(True))
        .values(is_active=False)
    )

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
