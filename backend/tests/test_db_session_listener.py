from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import load_only

from app.core.security import hash_password
from app.models.config_version import ConfigVersion
from app.models.enums import UserRole
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_committed_admin(write_session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Test1234!"),
        full_name="Test User",
        role=UserRole.admin,
        is_active=True,
    )
    write_session.add(user)
    await write_session.flush()
    return user


class TestMarkNaiveDatetimesAsUtc:
    async def test_loaded_datetime_column_gets_utc_tzinfo(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        version_id = uuid.uuid4()
        async with Session() as write_session:
            admin_user = await _make_committed_admin(write_session)
            version = ConfigVersion(
                id=version_id, version_number=1, description="test",
                config_snapshot={}, is_active=False, snapshot_schema_version=2,
                trigger_source="manual", created_by_id=admin_user.id,
            )
            write_session.add(version)
            await write_session.commit()

        async with Session() as fresh_session:
            result = await fresh_session.execute(select(ConfigVersion).where(ConfigVersion.id == version_id))
            row = result.scalars().first()
            assert row.created_at.tzinfo is not None

    async def test_deferred_column_is_not_touched_and_stays_unloaded(self, db_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

        version_id = uuid.uuid4()
        async with Session() as write_session:
            admin_user = await _make_committed_admin(write_session)
            version = ConfigVersion(
                id=version_id, version_number=1, description="test",
                config_snapshot={"large": "x" * 100}, is_active=False, snapshot_schema_version=2,
                trigger_source="manual", created_by_id=admin_user.id,
            )
            write_session.add(version)
            await write_session.commit()

        async with Session() as fresh_session:
            result = await fresh_session.execute(
                select(ConfigVersion)
                .options(load_only(ConfigVersion.id, ConfigVersion.created_at))
                .where(ConfigVersion.id == version_id)
            )
            row = result.scalars().first()
            state = sa_inspect(row)
            assert "config_snapshot" in state.unloaded, (
                "el listener global cargó config_snapshot pese a load_only excluirla"
            )
            assert row.created_at.tzinfo is not None
