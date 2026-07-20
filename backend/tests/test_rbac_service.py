"""Tests unitarios directos para app.services.system.rbac.

conftest._seed_rbac_for_tests siembra MODULES_SEED/SYSTEM_ROLES con ORM puro
ANTES de cada test (fixture db_engine, autouse vía db_session), así que la BD
ya llega con RBAC poblado — seed_rbac() aquí siempre corre en modo idempotente
(counts en 0), nunca desde una tabla vacía. Los tests de creación usan un
helper que vacía esas tablas primero para poder verificar el camino de
creación real; los demás dependen del seed ya aplicado por el fixture.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.rbac import Module, Permission, Role, RolePermission
from app.services.system import rbac as rbac_service

pytestmark = pytest.mark.asyncio


async def _clear_rbac_tables(db_session) -> None:
    """Vacía lo que _seed_rbac_for_tests ya sembró, para probar seed_rbac()
    desde una tabla vacía en vez de su camino idempotente (counts en 0)."""
    await db_session.execute(RolePermission.__table__.delete())
    await db_session.execute(Role.__table__.delete())
    await db_session.execute(Permission.__table__.delete())
    await db_session.execute(Module.__table__.delete())
    await db_session.commit()


async def test_seed_rbac_creates_modules_permissions_roles_and_grants(db_session):
    await _clear_rbac_tables(db_session)
    counts = await rbac_service.seed_rbac(db_session)

    assert counts["modules"] == len(rbac_service.MODULES_SEED)
    expected_perms = sum(len(m["permissions"]) for m in rbac_service.MODULES_SEED)
    assert counts["permissions"] == expected_perms
    assert counts["roles"] == len(rbac_service.SYSTEM_ROLES)
    assert counts["grants"] > 0

    admin_role = await db_session.scalar(select(Role).where(Role.name == "admin"))
    assert admin_role is not None
    assert admin_role.is_system is True

    modules = (await db_session.scalars(select(Module))).all()
    assert len(modules) == len(rbac_service.MODULES_SEED)


async def test_seed_rbac_is_idempotent(db_session):
    await _clear_rbac_tables(db_session)
    first = await rbac_service.seed_rbac(db_session)
    second = await rbac_service.seed_rbac(db_session)

    assert first["modules"] > 0
    assert second["modules"] == 0
    assert second["permissions"] == 0
    assert second["roles"] == 0
    assert second["grants"] == 0


async def test_seed_rbac_admin_gets_all_permissions(db_session):
    await rbac_service.seed_rbac(db_session)

    total_perms = (await db_session.scalars(select(Permission))).all()
    admin_grants = (
        await db_session.scalars(
            select(RolePermission).where(RolePermission.role == "admin")
        )
    ).all()

    assert len(admin_grants) == len(total_perms)


async def test_seed_rbac_returns_zero_counts_when_tables_missing(db_session, monkeypatch):
    from sqlalchemy.exc import ProgrammingError

    async def _boom(*args, **kwargs):
        raise ProgrammingError("SELECT 1 FROM modules LIMIT 1", {}, Exception("no such table"))

    monkeypatch.setattr(db_session, "execute", _boom)

    counts = await rbac_service.seed_rbac(db_session)

    assert counts == {"modules": 0, "permissions": 0, "grants": 0, "roles": 0}


async def test_has_permission_true_for_granted_permission(db_session):
    await rbac_service.seed_rbac(db_session)

    assert await rbac_service.has_permission(db_session, "editor", "knowledge", "read") is True


async def test_has_permission_false_for_ungranted_permission(db_session):
    await rbac_service.seed_rbac(db_session)

    assert await rbac_service.has_permission(db_session, "viewer", "knowledge", "delete") is False


async def test_has_permission_false_for_unknown_role(db_session):
    await rbac_service.seed_rbac(db_session)

    assert await rbac_service.has_permission(db_session, "no_such_role", "dashboard", "read") is False


async def test_get_role_permissions_returns_expected_set_for_viewer(db_session):
    await rbac_service.seed_rbac(db_session)

    perms = await rbac_service.get_role_permissions(db_session, "viewer")

    assert perms == {"dashboard.read", "analytics.read", "conversations.read"}


async def test_get_role_permissions_admin_has_all(db_session):
    await rbac_service.seed_rbac(db_session)

    all_perm_names = {
        p for (p,) in (await db_session.execute(select(Permission.name))).all()
    }
    admin_perms = await rbac_service.get_role_permissions(db_session, "admin")

    assert admin_perms == all_perm_names


async def test_get_role_permissions_empty_for_unknown_role(db_session):
    await rbac_service.seed_rbac(db_session)

    perms = await rbac_service.get_role_permissions(db_session, "ghost_role")

    assert perms == set()


async def test_get_role_permissions_returns_empty_set_on_programming_error(db_session, monkeypatch):
    from sqlalchemy.exc import ProgrammingError

    async def _boom(*args, **kwargs):
        raise ProgrammingError("SELECT ...", {}, Exception("no such table"))

    monkeypatch.setattr(db_session, "execute", _boom)

    perms = await rbac_service.get_role_permissions(db_session, "admin")

    assert perms == set()


async def test_get_all_roles_returns_system_roles_in_creation_order(db_session):
    # get_all_roles ordena por created_at, pero _seed_rbac_for_tests inserta
    # los 3 roles del sistema dentro de la misma transacción — server_default
    # func.now() en MySQL evalúa una sola vez por sentencia, así que las tres
    # filas comparten el mismo timestamp y el desempate entre ellas queda
    # indefinido (no es un bug de este test: get_all_roles no garantiza orden
    # estable sin una columna de desempate explícita). Verificamos el
    # contenido, no un orden que la función no promete bajo timestamps iguales.
    await rbac_service.seed_rbac(db_session)

    roles = await rbac_service.get_all_roles(db_session)

    assert {r.name for r in roles} == {"admin", "editor", "viewer"}
    assert all(r.is_system for r in roles)


async def test_get_all_roles_empty_when_no_roles(db_session):
    await _clear_rbac_tables(db_session)

    roles = await rbac_service.get_all_roles(db_session)

    assert roles == []


async def test_get_all_roles_returns_empty_list_on_programming_error(db_session, monkeypatch):
    from sqlalchemy.exc import ProgrammingError

    async def _boom(*args, **kwargs):
        raise ProgrammingError("SELECT ...", {}, Exception("no such table"))

    monkeypatch.setattr(db_session, "scalars", _boom)

    roles = await rbac_service.get_all_roles(db_session)

    assert roles == []


async def test_issue_user_tokens_embeds_role_permissions_in_access_token(db_session):
    await rbac_service.seed_rbac(db_session)

    fake_user = SimpleNamespace(id=uuid.uuid4(), role="viewer")

    access, refresh = await rbac_service.issue_user_tokens(db_session, fake_user)

    settings = get_settings()
    access_payload = pyjwt.decode(access, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    refresh_payload = pyjwt.decode(refresh, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert access_payload["sub"] == str(fake_user.id)
    assert access_payload["type"] == "access"
    assert sorted(access_payload["permissions"]) == sorted(
        ["dashboard.read", "analytics.read", "conversations.read"]
    )

    assert refresh_payload["sub"] == str(fake_user.id)
    assert refresh_payload["type"] == "refresh"
    assert "permissions" not in refresh_payload


async def test_issue_user_tokens_empty_permissions_for_role_without_grants(db_session):
    await rbac_service.seed_rbac(db_session)
    db_session.add(Role(name="ghost", display_name="Ghost", description="sin permisos", is_system=False))
    await db_session.commit()

    fake_user = SimpleNamespace(id=uuid.uuid4(), role="ghost")

    access, _ = await rbac_service.issue_user_tokens(db_session, fake_user)

    settings = get_settings()
    payload = pyjwt.decode(access, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert payload["permissions"] == []
