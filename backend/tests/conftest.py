from __future__ import annotations
import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-please"
os.environ.setdefault(
    "DATABASE_URL",
    "mysql+aiomysql://chatbot:Admin1234@localhost:3306/chatbot_test_ci",
)
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["UPLOADS_DIR"] = "/tmp/test-uploads"
os.environ["ALLOWED_ORIGINS"] = '["http://testserver"]'
os.environ["WIDGET_BASE_URL"] = "http://testserver"


def pytest_collection_modifyitems(items):
    from pytest_asyncio import is_async_test
    module_scope_marker = pytest.mark.asyncio(loop_scope="module")
    for item in items:
        if is_async_test(item):
            item.add_marker(module_scope_marker, append=False)


@pytest.fixture(autouse=True)
def settings_env(monkeypatch):
    from app.core.config import get_settings
    from app.services.system.settings import invalidate_runtime_overrides
    get_settings.cache_clear()
    invalidate_runtime_overrides()
    yield
    get_settings.cache_clear()
    invalidate_runtime_overrides()



async def _seed_rbac_for_tests(session) -> None:
    """Siembra módulos, permisos y roles RBAC con ORM puro."""
    from app.models.rbac import Module, Permission, Role, RolePermission
    from app.services.system.rbac import MODULES_SEED, SYSTEM_ROLES

    perm_map: dict[str, Permission] = {}
    for mod_data in MODULES_SEED:
        mod = Module(
            name=mod_data["name"],
            display_name=mod_data["display_name"],
            description=mod_data.get("description"),
            is_active=True,
        )
        session.add(mod)
        await session.flush()
        for perm_data in mod_data["permissions"]:
            perm_name = f"{mod_data['name']}.{perm_data['action'].value}"
            perm = Permission(
                module_id=mod.id,
                action=perm_data["action"],
                name=perm_name,
                description=perm_data["desc"],
            )
            session.add(perm)
            perm_map[perm_name] = perm
    await session.flush()

    for role_data in SYSTEM_ROLES:
        session.add(Role(
            name=role_data["name"],
            display_name=role_data["display_name"],
            description=role_data["description"],
            is_system=True,
        ))
        perms = (
            list(perm_map.values()) if role_data["permissions"] == "*"
            else [perm_map[k] for k in role_data["permissions"] if k in perm_map]
        )
        for perm in perms:
            session.add(RolePermission(role=role_data["name"], permission_id=perm.id))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db_engine():
    """El mismo engine que usa la app (app.db.session.engine), con las tablas
    creadas UNA sola vez por archivo de test."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool
    from sqlalchemy import event
    import json as _json
    import app.db.session as db_session_mod
    from app.db.session import Base
    import app.models  # noqa: F401

    settings = db_session_mod.get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        json_serializer=lambda obj: _json.dumps(obj, ensure_ascii=False),
        json_deserializer=_json.loads,
        poolclass=NullPool,
        connect_args={"init_command": "SET time_zone = '+00:00'"},
    )

    if not engine.url.get_backend_name().startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _set_isolation_level(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cur.close()

    db_session_mod.engine = engine
    db_session_mod.AsyncSessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        await _seed_rbac_for_tests(session)
        await session.commit()

    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        if not engine.url.get_backend_name().startswith("sqlite"):
            await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module")
async def db_session(db_engine) -> AsyncGenerator:
    """AsyncSession atada a un SAVEPOINT por test."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with db_engine.connect() as conn:
        outer_txn = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await outer_txn.rollback()



@pytest_asyncio.fixture(loop_scope="module")
async def client(db_session, monkeypatch):
    """
    httpx AsyncClient bound to the FastAPI app, with DB + Redis dependencies
    overridden. Use for endpoint integration tests.
    """
    import fakeredis.aioredis
    from httpx import AsyncClient, ASGITransport

    # Override the FastAPI dependency that yields a DB session.
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = _override_get_db

    # Stub Redis so rate-limit and cache code don't hit a real server.
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    from app.core import redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    from app.core.versioning import _background_tasks
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    app.dependency_overrides.clear()
    await fake.aclose()



@pytest_asyncio.fixture(loop_scope="module")
async def make_user(db_session):
    """Factory that creates a User row and returns it."""
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User

    async def _factory(
        *,
        email: str | None = None,
        password: str = "Test1234!",
        role: UserRole = UserRole.admin,
        full_name: str = "Test User",
    ) -> User:
        u = User(
            id=uuid.uuid4(),
            email=email or f"test-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
            is_active=True,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        return u

    return _factory


@pytest_asyncio.fixture(loop_scope="module")
async def admin_user(make_user):
    """Usuario admin listo para autenticar contra endpoints protegidos."""
    from app.models.enums import UserRole
    return await make_user(role=UserRole.admin)


@pytest.fixture
def auth_headers():
    """Factory that builds Authorization headers from a User."""
    from app.core.security import create_access_token

    def _build(user) -> dict[str, str]:
        token = create_access_token(subject=str(user.id))
        return {"Authorization": f"Bearer {token}"}

    return _build
