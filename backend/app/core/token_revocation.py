"""
JWT revocation: per-jti denylist (Redis) + per-user tokens_valid_after cutoff (DB).
Fail-open on Redis outage — the DB cutoff is always enforced.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.core import redis as redis_mod

log = structlog.get_logger()

_DENY_PREFIX = "jwt:denylist:"


async def revoke_jti(jti: str, expires_at: datetime) -> None:
    """Add a token's jti to the denylist until its natural expiry."""
    if not jti:
        return
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    ttl = int((expires_at - now).total_seconds())
    if ttl <= 0:
        return  # already expired — nothing to deny
    try:
        await redis_mod.get_redis().set(f"{_DENY_PREFIX}{jti}", "1", ex=ttl)
    except Exception:
        log.warning("token_revocation.revoke_failed", jti=jti[:8])


async def is_jti_revoked(jti: str | None) -> bool:
    """Return True if this jti has been explicitly revoked. Fail-open."""
    if not jti:
        return False
    try:
        return await redis_mod.get_redis().exists(f"{_DENY_PREFIX}{jti}") == 1
    except Exception:
        log.warning("token_revocation.check_failed", jti=jti[:8])
        return False


def is_token_stale(payload: dict, tokens_valid_after: datetime | None) -> bool:
    """True if the token was issued before the user's tokens_valid_after cutoff.

    A token without `iat` (legacy, pre-revocation) is treated as stale only if
    a cutoff exists — otherwise older tokens silently bypassed the check.
    """
    if tokens_valid_after is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        # No iat means it predates this feature; if a cutoff was set after a
        # password change, such a token must be rejected.
        return True
    issued = datetime.fromtimestamp(iat, tz=timezone.utc)
    if tokens_valid_after.tzinfo is None:
        tokens_valid_after = tokens_valid_after.replace(tzinfo=timezone.utc)
    # 1s grace: a token minted in the same second as the cutoff is valid.
    return issued < tokens_valid_after.replace(microsecond=0)
