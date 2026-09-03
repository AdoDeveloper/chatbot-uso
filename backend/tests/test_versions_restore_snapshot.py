"""Tests de app/services/monitoring/versions.py::restore_snapshot - ramas sin cubrir.

test_versions_router.py::TestRollback solo ejercita el camino feliz vía HTTP
(un solo GlobalSetting, esquema v2 actual). Esta es la ruta de recuperación
ante desastres del sistema: un rollback corrupto o parcial (reactivar un
proveedor LLM sin API key, restaurar un secreto enmascarado como el string
literal "[CONFIGURED]", o no revertir el snapshot v1 legado) no se detectaría
sin tests directos de cada rama.

Se llama a restore_snapshot() directo (no vía HTTP) para poder construir
snapshots sintéticos con las formas exactas de cada rama, incluyendo casos
que capture_snapshot() normal no produciría fácilmente (ej. v1 legacy).
"""
from __future__ import annotations

import uuid

import pytest

from app.models.config_version import ConfigVersion
from app.models.enums import UserRole
from app.models.global_setting import GlobalSetting
from app.models.llm_provider import LLMProvider
from app.models.notification_rule import NotificationRule
from app.models.widget_config import WidgetConfig
from app.services.monitoring.versions import SCHEMA_VERSION, restore_snapshot


@pytest.fixture
async def admin_user(make_user):
    return await make_user(role=UserRole.admin)


async def _make_version(db_session, snapshot: dict, *, schema_version: int = SCHEMA_VERSION) -> ConfigVersion:
    v = ConfigVersion(
        id=uuid.uuid4(),
        version_number=1,
        description="test snapshot",
        config_snapshot=snapshot,
        is_active=False,
        snapshot_schema_version=schema_version,
        trigger_source="manual",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


class TestRestoreSnapshotV1Legacy:
    async def test_v1_snapshot_restores_flat_settings_with_warning(self, db_session, admin_user):
        """Snapshots viejos (schema_version != SCHEMA_VERSION actual, formato
        plano key-value sin 'sections') deben restaurarse igual, con aviso
        explícito de que solo se restauró configuración básica."""
        v1_snapshot = {"schema_version": 1, "chatbot_name": "Bot Legado", "max_input_chars": 500}
        target = await _make_version(db_session, v1_snapshot, schema_version=1)

        new_version, warnings = await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()

        assert any("v1" in w.lower() for w in warnings)
        restored = await db_session.get(GlobalSetting, "chatbot_name")
        assert restored.value == "Bot Legado"
        assert new_version.trigger_source == "rollback"


class TestEphemeralLocksExcludedFromSnapshots:
    async def test_capture_ignores_scheduler_locks(self, db_session):
        """Los locks del scheduler viven en global_settings pero no son
        configuración: si entran al snapshot ensucian todos los diffs."""
        from app.services.monitoring.versions import _collect_global_settings

        db_session.add(GlobalSetting(
            key=f"scheduler:health:{uuid.uuid4().hex[:8]}",
            value={"owner": "x", "expires_at": "2026-01-01T00:00:00+00:00"},
        ))
        db_session.add(GlobalSetting(key="temperature", value=0.4))
        await db_session.commit()

        collected = await _collect_global_settings(db_session)

        assert not [k for k in collected if k.startswith("scheduler:")]
        assert collected["temperature"] == 0.4

    async def test_restore_ignores_locks_from_old_snapshots(self, db_session, admin_user):
        """Snapshots anteriores al fix guardaron miles de locks: restaurarlos
        no debe recrearlos en global_settings."""
        lock_key = f"scheduler:health:{uuid.uuid4().hex[:8]}"
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "global_settings": {
                    lock_key: {"owner": "x", "expires_at": "2026-01-01T00:00:00+00:00"},
                    "temperature": 0.9,
                },
            },
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()

        assert await db_session.get(GlobalSetting, lock_key) is None
        restored = await db_session.get(GlobalSetting, "temperature")
        assert restored.value == 0.9


class TestRestoreSnapshotSecretMasking:
    async def test_masked_secret_value_is_not_overwritten(self, db_session, admin_user):
        """El snapshot nunca contiene el secreto real, solo el string literal
        '[CONFIGURED]' - restaurarlo tal cual escribiría ese texto como si
        fuera la clave real, dejando el sistema roto silenciosamente."""
        db_session.add(GlobalSetting(key="smtp_password", value="real-secret-value"))
        await db_session.commit()

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {"global_settings": {"smtp_password": "[CONFIGURED]"}},
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()

        setting = await db_session.get(GlobalSetting, "smtp_password")
        assert setting.value == "real-secret-value", "el valor enmascarado no debe sobrescribir el secreto real"

    async def test_non_masked_global_setting_is_restored_normally(self, db_session, admin_user):
        db_session.add(GlobalSetting(key="chatbot_name", value="Nombre Nuevo"))
        await db_session.commit()

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {"global_settings": {"chatbot_name": "Nombre Original"}},
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()

        setting = await db_session.get(GlobalSetting, "chatbot_name")
        assert setting.value == "Nombre Original"


class TestRestoreSnapshotWidgetConfig:
    async def test_all_captured_widget_fields_are_restored(self, db_session, admin_user):
        wc = WidgetConfig(
            id=uuid.uuid4(), chatbot_name="Bot Modificado", welcome_message="Hola modificado",
            enable_csat=False, csat_question="pregunta modificada", launcher_label="chat modificado",
        )
        db_session.add(wc)
        await db_session.commit()

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "widget_config": {
                    "chatbot_name": "Bot Original",
                    "welcome_message": "Hola original",
                    "enable_csat": True,
                    "csat_question": "pregunta original",
                    "launcher_label": "chat original",
                },
            },
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()
        await db_session.refresh(wc)

        assert wc.chatbot_name == "Bot Original"
        assert wc.welcome_message == "Hola original"
        assert wc.enable_csat is True
        assert wc.csat_question == "pregunta original"
        assert wc.launcher_label == "chat original"


class TestRestoreSnapshotLLMProviders:
    async def test_provider_absent_from_snapshot_is_deactivated(self, db_session, admin_user):
        """Un proveedor que se agregó DESPUÉS del snapshot elegido no debe
        quedar activo tras el rollback - se desactiva y pierde prioridad."""
        provider = LLMProvider(
            id=uuid.uuid4(), name="Proveedor Nuevo", provider_type="openai",
            model_name="gpt-4", is_active=True, priority=1,
        )
        db_session.add(provider)
        await db_session.commit()

        snapshot = {"schema_version": SCHEMA_VERSION, "sections": {"llm_providers": []}}
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()
        await db_session.refresh(provider)

        assert provider.is_active is False
        assert provider.priority is None

    async def test_provider_in_snapshot_but_missing_from_db_is_recreated_inactive_with_warning(
        self, db_session, admin_user,
    ):
        """Un proveedor que estaba en el snapshot pero fue borrado de la BD
        se recrea SIN api_key (nunca se captura) - debe quedar inactivo y
        el warning debe decírselo al admin explícitamente, no fallar silente
        con una clave vacía funcionando a medias."""
        missing_id = str(uuid.uuid4())
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "llm_providers": [{
                    "id": missing_id, "name": "Proveedor Borrado", "provider_type": "anthropic",
                    "model_name": "claude-3", "api_base": None, "is_active": True, "priority": 1,
                }],
            },
        }
        target = await _make_version(db_session, snapshot)

        _, warnings = await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()

        recreated = await db_session.get(LLMProvider, uuid.UUID(missing_id))
        assert recreated is not None
        assert recreated.is_active is False, "un proveedor recreado sin API key nunca debe quedar activo"
        assert recreated.api_key_encrypted is None
        assert any("api key" in w.lower() for w in warnings)

    async def test_provider_present_in_both_is_updated_in_place(self, db_session, admin_user):
        provider = LLMProvider(
            id=uuid.uuid4(), name="Nombre Modificado", provider_type="openai",
            model_name="gpt-3.5", is_active=False, priority=None,
        )
        db_session.add(provider)
        await db_session.commit()

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "llm_providers": [{
                    "id": str(provider.id), "name": "Nombre Original", "provider_type": "openai",
                    "model_name": "gpt-4", "api_base": None, "is_active": True, "priority": 1,
                }],
            },
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()
        await db_session.refresh(provider)

        assert provider.name == "Nombre Original"
        assert provider.model_name == "gpt-4"
        assert provider.is_active is True
        assert provider.priority == 1


class TestRestoreSnapshotNotificationRules:
    async def test_notification_rule_enabled_and_target_are_restored(self, db_session, admin_user):
        from app.models.enums import NotificationChannel, NotificationEvent

        rule = NotificationRule(
            id=uuid.uuid4(), event=NotificationEvent.escalation,
            channel=NotificationChannel.email, enabled=False, target="new@example.com",
        )
        db_session.add(rule)
        await db_session.commit()

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "notification_rules": [{
                    "id": str(rule.id), "enabled": True, "target": "original@example.com",
                }],
            },
        }
        target = await _make_version(db_session, snapshot)

        await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        await db_session.commit()
        await db_session.refresh(rule)

        assert rule.enabled is True
        assert rule.target == "original@example.com"


class TestRestoreSnapshotNotRevertedWarnings:
    async def test_warns_about_escalation_rules_sources_and_faq_not_reverted(self, db_session, admin_user):
        """Estas secciones se capturan en snapshots pero deliberadamente no
        se revierten (borrar fuentes/FAQ productivas en un rollback sería
        destructivo) - el admin debe ser avisado, no dejado sin explicación."""
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {
                "escalation_rules": [{"id": "1"}],
                "sources": [{"id": "2"}],
                "faq_entries": [{"id": "3"}],
            },
        }
        target = await _make_version(db_session, snapshot)

        _, warnings = await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)

        joined = " ".join(warnings).lower()
        assert "escalamiento" in joined
        assert "fuentes" in joined
        assert "frecuentes" in joined or "faq" in joined

    async def test_no_warnings_when_those_sections_are_empty(self, db_session, admin_user):
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "sections": {"escalation_rules": [], "sources": [], "faq_entries": []},
        }
        target = await _make_version(db_session, snapshot)

        _, warnings = await restore_snapshot(db_session, version_id=target.id, user_id=admin_user.id)
        assert warnings == []


class TestRestoreSnapshotNotFound:
    async def test_raises_value_error_for_unknown_version(self, db_session, admin_user):
        with pytest.raises(ValueError):
            await restore_snapshot(db_session, version_id=uuid.uuid4(), user_id=admin_user.id)
