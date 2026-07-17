from __future__ import annotations
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio

# Must be set before ANY app module import so _make_engine() sees SQLite.
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-please"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["UPLOADS_DIR"] = "/tmp/test-uploads"
os.environ["ALLOWED_ORIGINS"] = '["http://testserver"]'
os.environ["WIDGET_BASE_URL"] = "http://testserver"


@pytest.fixture(autouse=True)
def settings_env(monkeypatch):
    from app.core.config import get_settings
    from app.services.system.settings import invalidate_runtime_overrides
    get_settings.cache_clear()
    invalidate_runtime_overrides()
    yield
    get_settings.cache_clear()
    invalidate_runtime_overrides()



async def _seed_rbac_for_tests(engine) -> None:
    """Siembra módulos, permisos y roles RBAC con ORM puro.

    Usa inserts directos porque la BD es vacía en cada test — sin colisiones.
    Sin este seed, require_perm() devuelve 403 para cualquier rol.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.models.rbac import Module, Permission, Role, RolePermission
    from app.services.system.rbac import MODULES_SEED, SYSTEM_ROLES

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
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
        await session.commit()


@pytest_asyncio.fixture
async def db_engine():
    """El mismo engine que usa la app (app.db.session.engine), con las tablas
    creadas. Código como persist_turn() abre sesiones directamente desde
    AsyncSessionLocal (bind=engine) sin pasar por el override de get_db, así
    que el engine de test y el de la app deben ser el mismo objeto."""
    from app.db.session import Base, engine
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_rbac_for_tests(engine)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator:
    """An AsyncSession bound to the per-test engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session



@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """
    httpx AsyncClient bound to the FastAPI app, with DB + Redis dependencies
    overridden. Use for endpoint integration tests.
    """
    import fakeredis.aioredis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from httpx import AsyncClient, ASGITransport

    Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    # Override the FastAPI dependency that yields a DB session.
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = _override_get_db

    # Stub Redis so rate-limit and cache code don't hit a real server.
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    from app.core import redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    await fake.aclose()



@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
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
