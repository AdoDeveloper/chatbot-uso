"""
Multi-dimensional rate limiting using Redis sliding windows.
Falls open if Redis is down. All limits configurable via Settings.
"""
from __future__ import annotations

import asyncio
import structlog
import time

from app.core.redis import get_redis

log = structlog.get_logger()

# --- Fallback en memoria cuando Redis no está disponible -------------------
# Limitador deslizante por proceso. No se comparte entre workers ni persiste
# entre reinicios: es una última línea de defensa, NO un reemplazo de Redis.
# Umbrales 30% más permisivos que Redis para evitar falsos positivos bajo
# concurrencia multi-worker (el tope real efectivo es N× por worker).
_LOCAL_LIMITS: dict[str, list[float]] = {}
_LOCAL_LOCK = asyncio.Lock()
_LOCAL_PERMISSIVE_FACTOR = 1.3
_LOCAL_FALLBACK_WARNED = False


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s.")


async def check_rate_limit(
    key_prefix: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    Check and increment a sliding window counter.
    Returns True if within limit, raises RateLimitExceeded if over.
    Falls open (returns True) if Redis is unavailable — callers that need
    a hard guarantee under Redis failure should check `redis_available` separately.
    """
    try:
        redis = get_redis()
        key = f"rl:{key_prefix}:{identifier}:{window_seconds}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        if count > max_requests:
            ttl = await redis.ttl(key)
            raise RateLimitExceeded(retry_after=max(ttl, 1))
        return True
    except RateLimitExceeded:
        raise
    except Exception as exc:
        # Redis caído (o cualquier fallo de Redis): en vez de fallar abierto,
        # aplicar el limitador en memoria de reserva y dejar rastro.
        global _LOCAL_FALLBACK_WARNED
        if not _LOCAL_FALLBACK_WARNED:
            log.warning("ratelimit.local_fallback_active", error=str(exc))
            _LOCAL_FALLBACK_WARNED = True
        try:
            await _local_rate_limit(key_prefix, identifier, max_requests, window_seconds)
        except RateLimitExceeded:
            raise
        except Exception:
            # El propio fallback en memoria falló: permitir para no tumbar el servicio.
            log.warning("ratelimit.local_fallback_failed", key_prefix=key_prefix)
        return True


def _local_prune(key: str, window_seconds: int, now: float) -> list[float]:
    stamps = _LOCAL_LIMITS.get(key)
    if not stamps:
        return []
    cutoff = now - window_seconds
    kept = [t for t in stamps if t > cutoff]
    if kept:
        _LOCAL_LIMITS[key] = kept
    else:
        _LOCAL_LIMITS.pop(key, None)
    return kept


async def _local_rate_limit(
    key_prefix: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """Limitador en memoria de reserva; lanza RateLimitExceeded si excede."""
    limit = max(1, int(max_requests * _LOCAL_PERMISSIVE_FACTOR))
    now = time.monotonic()
    key = f"local:{key_prefix}:{identifier}:{window_seconds}"
    async with _LOCAL_LOCK:
        stamps = _local_prune(key, window_seconds, now)
        stamps.append(now)
        _LOCAL_LIMITS[key] = stamps
        count = len(stamps)
    if count > limit:
        raise RateLimitExceeded(retry_after=window_seconds)


async def check_chat_limits(client_ip: str, limits: dict, *, session_id: str | None = None) -> None:
    """Check all chat rate limit dimensions. Raises RateLimitExceeded on breach.

    Si se pasa `session_id`, se aplica también un límite por sesión.
    No toca el pipeline RAG: es solo el guardia previo del endpoint de chat.
    """
    await check_rate_limit(
        "chat:min", client_ip,
        max_requests=limits.get("per_min", 10),
        window_seconds=60,
    )
    await check_rate_limit(
        "chat:hour", client_ip,
        max_requests=limits.get("per_hour", 100),
        window_seconds=3600,
    )
    if session_id:
        # Granularidad por sesión: protege contra un solo cliente que mantenga
        # una sesión y la inunde, incluso si rota IPs.
        await check_rate_limit(
            "chat:session", session_id,
            max_requests=limits.get("per_session_min", 20),
            window_seconds=60,
        )


async def record_throttle_event(
    *,
    dimension: str,
    identifier: str,
    identifier_type: str,
    limit_value: int,
    retry_after_seconds: int | None,
) -> None:
    """Persiste el evento de throttle para historial. Best-effort, no bloquea."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.rate_limit_event import RateLimitEvent
        async with AsyncSessionLocal() as db:
            db.add(RateLimitEvent(
                dimension=dimension,
                identifier=identifier,
                identifier_type=identifier_type,
                limit_value=limit_value,
                retry_after_seconds=retry_after_seconds,
            ))
            await db.commit()
    except Exception as exc:
        log.debug("rate_limit.throttle_event_persist_failed", error=str(exc))


async def get_throttled_ips(
    limit_per_min: int | None = None,
    limit_per_hour: int | None = None,
) -> list[dict]:
    """Scan Redis for IPs currently near or over rate limits.

    Key shape: `rl:chat:<window_label>:<ip>:<window_seconds>`
    Acepta los límites efectivos del panel; si no se pasan usa los defaults.
    """
    from app.services.system.settings import RUNTIME_DEFAULTS
    limit_per_min = limit_per_min or RUNTIME_DEFAULTS["rate_limit_chat_per_min"]
    limit_per_hour = limit_per_hour or RUNTIME_DEFAULTS["rate_limit_chat_per_hour"]
    threshold_min = max(1, limit_per_min // 2)
    threshold_hour = max(1, limit_per_hour // 2)

    try:
        redis = get_redis()
        pattern = "rl:chat:*"
        results = []
        cursor = 0
        seen: set[str] = set()
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=200)
            for key in keys:
                parts = key.split(":")
                # rl:chat:<label>:<ip>:<window_seconds>
                # IPv6 addresses contain ":" so ip = everything between index 3
                # and the last segment (the numeric window).
                if len(parts) < 5:
                    continue
                window = parts[-1]
                ip = ":".join(parts[3:-1])
                if ip in seen:
                    continue
                count = await redis.get(key)
                ttl = await redis.ttl(key)
                if not count:
                    continue
                count_int = int(count)
                is_per_min = window == "60"
                limit = limit_per_min if is_per_min else limit_per_hour
                threshold = threshold_min if is_per_min else threshold_hour
                if count_int >= threshold:
                    seen.add(ip)
                    results.append({
                        "ip": ip,
                        "current_count": count_int,
                        "limit": limit,
                        "window": "per_min" if is_per_min else "per_hour",
                        "ttl_seconds": max(ttl, 0),
                    })
            if cursor == 0:
                break
        return sorted(results, key=lambda x: x["current_count"], reverse=True)
    except Exception:
        return []


async def reset_ip(ip: str) -> None:
    """Remove rate limit keys for a specific IP.

    No se puede usar el glob `rl:*:{ip}:*` porque las direcciones IPv6 contienen
    ':' y romperían el patrón. En su lugar escaneamos todas las claves `rl:*` y
    extraemos el identificador igual que hace `get_throttled_ips`
    (clave = `rl:<prefix...>:<identifier>:<window>`), comparándolo con `ip`.
    """
    try:
        redis = get_redis()
        cursor = 0
        keys_to_delete = []
        while True:
            cursor, keys = await redis.scan(cursor, match="rl:*", count=200)
            for key in keys:
                parts = key.split(":")
                if len(parts) < 5:
                    continue
                # identifier = todo entre el índice 3 y el último segmento (window)
                identifier = ":".join(parts[3:-1])
                if identifier == ip:
                    keys_to_delete.append(key)
            if cursor == 0:
                break
        if keys_to_delete:
            await redis.delete(*keys_to_delete)
    except Exception:
        pass
