"""
Revocación de JWT: denylist por jti (Redis) + corte tokens_valid_after por usuario (DB).
Fail-open ante una caída de Redis - el corte de la DB siempre se aplica.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.core import redis as redis_mod

log = structlog.get_logger()

_DENY_PREFIX = "jwt:denylist:"


async def revoke_jti(jti: str, expires_at: datetime) -> None:
    """Agrega el jti de un token a la denylist hasta su expiración natural."""
    if not jti:
        return
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    ttl = int((expires_at - now).total_seconds())
    if ttl <= 0:
        return  # ya expiró - nada que denegar
    try:
        await redis_mod.get_redis().set(f"{_DENY_PREFIX}{jti}", "1", ex=ttl)
    except Exception:
        log.warning("token_revocation.revoke_failed", jti=jti[:8])


async def is_jti_revoked(jti: str | None) -> bool:
    """Devuelve True si este jti fue revocado explícitamente. Fail-open."""
    if not jti:
        return False
    try:
        return await redis_mod.get_redis().exists(f"{_DENY_PREFIX}{jti}") == 1
    except Exception:
        log.warning("token_revocation.check_failed", jti=jti[:8])
        return False


def is_token_stale(payload: dict, tokens_valid_after: datetime | None) -> bool:
    """True si el token fue emitido antes del corte tokens_valid_after del usuario."""
    if tokens_valid_after is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        return True
    issued = datetime.fromtimestamp(iat, tz=timezone.utc)
    if tokens_valid_after.tzinfo is None:
        tokens_valid_after = tokens_valid_after.replace(tzinfo=timezone.utc)
    # Margen de 1s: un token emitido en el mismo segundo que el corte es válido.
    return issued < tokens_valid_after.replace(microsecond=0)
