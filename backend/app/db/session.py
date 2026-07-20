from __future__ import annotations

import json
from typing import AsyncGenerator

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    kwargs: dict = dict(
        echo=settings.DEBUG,
        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
        json_deserializer=json.loads,
    )
    if is_sqlite and ":memory:" in settings.DATABASE_URL:
        from sqlalchemy.pool import StaticPool
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    if not is_sqlite:

        kwargs["pool_pre_ping"] = False
        kwargs["pool_recycle"] = 3600
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    return create_async_engine(settings.DATABASE_URL, **kwargs)


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(sa_text("SELECT 1"))
        except Exception:
            await session.rollback()
            try:
                await session.execute(sa_text("SELECT 1"))
            except Exception:
                await session.rollback()
                raise
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
