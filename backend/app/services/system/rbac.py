"""Servicio RBAC — roles dinámicos en DB. seed_rbac es idempotente."""
from __future__ import annotations

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession


log = structlog.get_logger()

from app.models.enums import PermissionAction
from app.models.rbac import Module, Permission, Role, RolePermission

MODULES_SEED: list[dict] = [
    {
        "name": "dashboard",
        "display_name": "Panel Principal",
        "description": "Acceso al dashboard con métricas generales",
        "permissions": [
            {"action": PermissionAction.read, "desc": "Ver panel principal"},
        ],
    },
    {
        "name": "conversations",
        "display_name": "Conversaciones",
        "description": "Historial de conversaciones del chatbot",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver conversaciones"},
            {"action": PermissionAction.update, "desc": "Gestionar conversaciones"},
            {"action": PermissionAction.delete, "desc": "Eliminar conversaciones"},
        ],
    },
    {
        "name": "knowledge",
        "display_name": "Conocimiento",
        "description": "Documentos, consultas y base de conocimiento",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver documentos"},
            {"action": PermissionAction.create, "desc": "Subir documentos"},
            {"action": PermissionAction.update, "desc": "Editar documentos"},
            {"action": PermissionAction.delete, "desc": "Eliminar documentos"},
            {"action": PermissionAction.manage, "desc": "Aprobar o rechazar documentos"},
        ],
    },
    {
        "name": "analytics",
        "display_name": "Estadísticas",
        "description": "Métricas y reportes de uso del chatbot",
        "permissions": [
            {"action": PermissionAction.read, "desc": "Ver estadísticas"},
        ],
    },
    {
        "name": "audit",
        "display_name": "Registros de actividad",
        "description": "Auditoría de acciones realizadas en el sistema",
        "permissions": [
            {"action": PermissionAction.read, "desc": "Ver registros de auditoría"},
        ],
    },
    {
        "name": "bot_settings",
        "display_name": "Configuración del Bot",
        "description": "Parámetros del chatbot, prompts, RAG e integraciones",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver configuración del bot"},
            {"action": PermissionAction.update, "desc": "Modificar configuración del bot"},
        ],
    },
    {
        "name": "escalation",
        "display_name": "Escalamiento",
        "description": "Reglas y gestión de escalamientos de conversaciones",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver escalamientos"},
            {"action": PermissionAction.update, "desc": "Gestionar escalamientos activos"},
            {"action": PermissionAction.manage, "desc": "Configurar reglas de escalamiento"},
        ],
    },
    {
        "name": "users",
        "display_name": "Usuarios",
        "description": "Gestión de cuentas de usuario y accesos",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver lista de usuarios"},
            {"action": PermissionAction.update, "desc": "Editar usuarios"},
            {"action": PermissionAction.delete, "desc": "Eliminar usuarios"},
            {"action": PermissionAction.manage, "desc": "Gestionar roles y permisos"},
        ],
    },
    {
        "name": "notifications",
        "display_name": "Notificaciones",
        "description": "Configuración de alertas y reglas de notificación",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver configuración de notificaciones"},
            {"action": PermissionAction.update, "desc": "Configurar notificaciones"},
        ],
    },
    {
        "name": "system",
        "display_name": "Sistema",
        "description": "Estado del sistema, cuotas y configuración avanzada",
        "permissions": [
            {"action": PermissionAction.read,   "desc": "Ver estado del sistema"},
            {"action": PermissionAction.update, "desc": "Gestionar sistema y cuotas"},
            {"action": PermissionAction.manage, "desc": "Administración total del sistema"},
        ],
    },
]


SYSTEM_ROLES: list[dict] = [
    {
        "name": "admin",
        "display_name": "Administrador",
        "description": "Acceso total al sistema.",
        "permissions": "*",
    },
    {
        "name": "editor",
        "display_name": "Editor",
        "description": "Gestión de contenido y base de conocimiento del chatbot.",
        "permissions": [
            "dashboard.read",
            "conversations.read", "conversations.update",
            "knowledge.read", "knowledge.create", "knowledge.update", "knowledge.delete",
            "bot_settings.read",
            "analytics.read",
            "escalation.read",
        ],
    },
    {
        "name": "viewer",
        "display_name": "Lector",
        "description": "Solo lectura: estadísticas e historial de conversaciones.",
        "permissions": [
            "dashboard.read",
            "analytics.read",
            "conversations.read",
        ],
    },
]


async def seed_rbac(db: AsyncSession) -> dict[str, int]:
    """Crea módulos, permisos, roles del sistema y permisos por defecto.

    Superadmin recibe todos los permisos. Los demás roles reciben
    sus permisos predeterminados definidos en SYSTEM_ROLES. Idempotente.
    """
    try:
        await db.execute(text("SELECT 1 FROM modules LIMIT 1"))
    except (ProgrammingError, IntegrityError):
        await db.rollback()
        log.warning("rbac.seed_skipped", reason="tables_not_exist — run: alembic upgrade head")
        return {"modules": 0, "permissions": 0, "grants": 0, "roles": 0}

    modules_created = perms_created = grants_created = roles_created = 0

    perm_map: dict[str, Permission] = {}  # "module.action" → Permission
    for mod_data in MODULES_SEED:
        mod = await db.scalar(select(Module).where(Module.name == mod_data["name"]))
        if mod is None:
            try:
                mod = Module(
                    name=mod_data["name"],
                    display_name=mod_data["display_name"],
                    description=mod_data.get("description"),
                    is_active=True,
                )
                db.add(mod)
                await db.flush()
                modules_created += 1
            except IntegrityError:
                await db.rollback()
                mod = await db.scalar(select(Module).where(Module.name == mod_data["name"]))

        for perm_data in mod_data["permissions"]:
            perm_name = f"{mod_data['name']}.{perm_data['action'].value}"
            perm = await db.scalar(select(Permission).where(Permission.name == perm_name))
            if perm is None:
                try:
                    perm = Permission(
                        module_id=mod.id,
                        action=perm_data["action"],
                        name=perm_name,
                        description=perm_data["desc"],
                    )
                    db.add(perm)
                    await db.flush()
                    perms_created += 1
                except IntegrityError:
                    await db.rollback()
                    perm = await db.scalar(select(Permission).where(Permission.name == perm_name))
            perm_map[perm_name] = perm

    for role_data in SYSTEM_ROLES:
        existing_role = await db.scalar(select(Role).where(Role.name == role_data["name"]))
        if existing_role is None:
            try:
                db.add(Role(
                    name=role_data["name"],
                    display_name=role_data["display_name"],
                    description=role_data["description"],
                    is_system=True,
                ))
                await db.flush()
                roles_created += 1
            except IntegrityError:
                await db.rollback()

    await db.flush()

    for role_data in SYSTEM_ROLES:
        role_name = role_data["name"]
        perms_to_grant = (
            list(perm_map.values()) if role_data["permissions"] == "*"
            else [perm_map[k] for k in role_data["permissions"] if k in perm_map]
        )

        for perm in perms_to_grant:
            existing_grant = await db.scalar(
                select(RolePermission).where(
                    RolePermission.role == role_name,
                    RolePermission.permission_id == perm.id,
                )
            )
            if existing_grant is None:
                try:
                    db.add(RolePermission(role=role_name, permission_id=perm.id))
                    await db.flush()
                    grants_created += 1
                except IntegrityError:
                    await db.rollback()

    await db.commit()
    log.info(
        "rbac.seed_complete",
        modules=modules_created, permissions=perms_created,
        roles=roles_created, grants=grants_created,
    )
    return {
        "modules": modules_created,
        "permissions": perms_created,
        "roles": roles_created,
        "grants": grants_created,
    }


async def has_permission(db: AsyncSession, role: str, module_name: str, action: str) -> bool:
    """Verifica si un rol tiene permiso para (módulo, acción)."""
    result = await db.scalar(
        select(RolePermission)
        .join(Permission, RolePermission.permission_id == Permission.id)
        .join(Module, Permission.module_id == Module.id)
        .where(RolePermission.role == role)
        .where(Module.name == module_name)
        .where(Permission.action == action)
    )
    return result is not None


async def get_role_permissions(db: AsyncSession, role: str) -> set[str]:
    """Devuelve el conjunto de permisos concedidos a un rol como 'modulo.accion'."""
    try:
        rows = await db.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role == role)
        )
        return {r for (r,) in rows.all()}
    except ProgrammingError:
        await db.rollback()
        return set()


async def issue_user_tokens(db: AsyncSession, user: object) -> tuple[str, str]:
    """Emite un par (access, refresh) JWT para `user`, incrustando en el access
    los permisos reales del rol (lista 'modulo.accion').

    Centraliza la emisión para que TODO login/refresh/SSO/invitación incluya los
    permisos en el token, manteniendo la UI sincronizada sin llamadas extra.
    """
    from app.core.security import create_access_token, create_refresh_token

    perms = sorted(await get_role_permissions(db, user.role))
    access = create_access_token(str(user.id), permissions=perms)
    refresh = create_refresh_token(str(user.id))
    return access, refresh


async def get_all_roles(db: AsyncSession) -> list[Role]:
    """Lista todos los roles ordenados por fecha de creación."""
    try:
        rows = await db.scalars(select(Role).order_by(Role.created_at))
        return list(rows)
    except ProgrammingError:
        await db.rollback()
        return []



