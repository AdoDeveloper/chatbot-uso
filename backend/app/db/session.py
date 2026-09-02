from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@event.listens_for(Base, "load", propagate=True)
def _mark_naive_datetimes_as_utc(target, context) -> None:
    mapper = getattr(target, "__mapper__", None)
    if mapper is None:
        return
    unloaded = sa_inspect(target).unloaded
    for column_attr in mapper.column_attrs:
        if column_attr.key in unloaded:
            continue
        value = getattr(target, column_attr.key, None)
        if isinstance(value, datetime) and value.tzinfo is None:
            setattr(target, column_attr.key, value.replace(tzinfo=timezone.utc))


def _make_engine():
    settings = get_settings()

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    kwargs: dict = {
        "echo": settings.DEBUG,
        "json_serializer": lambda obj: json.dumps(obj, ensure_ascii=False),
        "json_deserializer": json.loads,
    }
    if is_sqlite and ":memory:" in settings.DATABASE_URL:
        from sqlalchemy.pool import StaticPool
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    if not is_sqlite:
        kwargs["pool_pre_ping"] = False
        kwargs["pool_recycle"] = 3600
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        kwargs["connect_args"] = {"init_command": "SET time_zone = '+00:00'"}
    return create_async_engine(settings.DATABASE_URL, **kwargs)


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _probe_connection(session: AsyncSession) -> None:
    try:
        await session.execute(sa_text("SELECT 1"))
    except Exception:
        await session.rollback()
        try:
            await session.execute(sa_text("SELECT 1"))
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        await _probe_connection(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
