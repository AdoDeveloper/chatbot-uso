from __future__ import annotations

import uuid

import pytest

from app.models.config_version import ConfigVersion
from app.models.global_setting import GlobalSetting
from app.services.system.settings import (
    RUNTIME_DEFAULTS,
    get_deployed_runtime_overrides,
    get_runtime_overrides,
    invalidate_runtime_overrides,
)

pytestmark = pytest.mark.asyncio


async def _make_deploy_version(db_session, *, global_settings: dict, trigger_source: str = "deploy"):
    version = ConfigVersion(
        id=uuid.uuid4(),
        config_snapshot={"sections": {"global_settings": global_settings}},
        trigger_source=trigger_source,
    )
    db_session.add(version)
    await db_session.commit()
    return version


class TestDeployedRuntimeOverrides:
    async def test_falls_back_to_live_when_no_deploy(self, db_session):
        invalidate_runtime_overrides()
        live = await get_runtime_overrides(db_session)
        deployed = await get_deployed_runtime_overrides(db_session)
        assert deployed == live

    async def test_reads_from_last_deploy_snapshot_not_live_value(self, db_session):
        db_session.add(GlobalSetting(key="guardrails_enabled", value=True))
        db_session.add(GlobalSetting(key="max_input_chars", value=4000))
        await db_session.commit()

        await _make_deploy_version(
            db_session,
            global_settings={"guardrails_enabled": False, "max_input_chars": 999},
        )

        deployed = await get_deployed_runtime_overrides(db_session)
        assert deployed["guardrails_enabled"] is False
        assert deployed["max_input_chars"] == 999

        invalidate_runtime_overrides()
        live = await get_runtime_overrides(db_session)
        assert live["guardrails_enabled"] is True
        assert live["max_input_chars"] == 4000

    async def test_ignores_non_deploy_snapshot_even_if_more_recent(self, db_session):
        await _make_deploy_version(
            db_session,
            global_settings={"guardrails_enabled": False},
        )
        await _make_deploy_version(
            db_session,
            global_settings={"guardrails_enabled": True},
            trigger_source="settings",
        )

        deployed = await get_deployed_runtime_overrides(db_session)
        assert deployed["guardrails_enabled"] is False

    async def test_missing_keys_in_snapshot_use_defaults(self, db_session):
        await _make_deploy_version(db_session, global_settings={})
        deployed = await get_deployed_runtime_overrides(db_session)
        assert deployed == RUNTIME_DEFAULTS
