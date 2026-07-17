from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy.ext.asyncio import AsyncSession

import jwt as pyjwt

from app.core.security import decode_token
from app.core.token_revocation import is_jti_revoked, is_token_stale
from app.db.session import get_db
from app.models.user import User
from app.services.users import service as user_service

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else None
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")

    # Revocación explícita (logout) vía denylist de jti en Redis.
    if await is_jti_revoked(payload.get("jti")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión cerrada o revocada")

    user = await user_service.get_by_id(db, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta desactivada")

    # Revocación masiva: token emitido antes del último cambio de contraseña.
    if is_token_stale(payload, user.tokens_valid_after):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión expirada por cambio de credenciales")

    return user


def require_permission(module: str, action: str):
    """Dependencia RBAC: verifica el permiso (módulo, acción) contra la BD."""
    async def checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.services.system.rbac import has_permission
        allowed = await has_permission(db, current_user.role, module, action)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sin permiso para {module}.{action}",
            )
        return current_user
    return checker


def require_perm(permission: str):
    """Shorthand: require_perm("knowledge.update") — parses 'module.action'."""
    if "." not in permission:
        raise ValueError(f"Invalid permission string (expected 'module.action'): {permission!r}")
    module, action = permission.rsplit(".", 1)
    return require_permission(module, action)


def get_client_ip(request: Request) -> str:
    """Extrae la IP real del cliente, priorizando headers de proxy reverso.

    Orden de precedencia:
      1. CF-Connecting-IP (Cloudflare — confiable, no spoofeable tras CF)
      2. X-Real-IP (Nginx de confianza)
      3. X-Forwarded-For: se toma la ÚLTIMA IP de la cadena (la del cliente
         real detrás de proxies legítimos), no la primera, que es la que el
         cliente puede falsificar libremente.
      4. request.client.host (conexión directa)

    Nota: X-Forwarded-For es spoofeable por el cliente. En producción debe
    venir siempre detrás de un proxy de confianza (Nginx/CF) que lo reescribe;
    si no hay proxy, se prefiere request.client.host por sobre XFF.
    """
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # La última IP de la cadena es la del cliente origen tras proxies.
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "0.0.0.0"
