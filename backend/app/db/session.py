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

        # NOTA: no usar pool_pre_ping=True con el driver aiomysql — su método
        # ping() exige el arg `reconnect` y SQLAlchemy lo llama sin él, lo que
        # rompe el arranque (TypeError). En su lugar nos apoyamos en
        # pool_recycle para descartar conexiones antes del wait_timeout de
        # MySQL (28800s = 8h) y así evitar entregar conexiones muertas.
        kwargs["pool_pre_ping"] = False
        # Recicla conexiones cada hora, muy por debajo del wait_timeout del
        # servidor, de modo que el pool nunca entregue una conexión que MySQL
        # ya haya cerrado por inactividad (causa del "deja de responder tras
        # horas y revive al reiniciar").
        kwargs["pool_recycle"] = 3600
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        # Default de SQLAlchemy (30s): si por alguna razón el pool —ya
        # generoso— se agotara, prefiere esperar antes de fallar en vez de
        # cortar de inmediato (mismo principio que LLM_MAX_CONCURRENCY).
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
        # Verifica que la conexión del pool siga viva antes de usarla. Si
        # MySQL la cerró (timeout de inactividad) o la PC se suspendió y la
        # conexión TCP se rompió, el SELECT 1 falla; al hacer rollback y
        # re-ejecutar, SQLAlchemy descarta la conexión muerta y abre una
        # fresca (en lugar de colgar el request hasta reiniciar el servicio).
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
