"""
Versioning middleware — auto-captures system snapshots after mutations.
Fire-and-forget asyncio task, zero added latency to the response.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, MutableMapping

import jwt as pyjwt

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import decode_token

log = structlog.get_logger()

# Maps (HTTP method, path prefix) → trigger_source label
_VERSIONED_ROUTES: list[tuple[str, str, str]] = [
    ("PUT",    "/api/v1/settings",                      "settings"),
    ("POST",   "/api/v1/providers",                     "providers"),
    ("PATCH",  "/api/v1/providers/",                     "providers"),
    ("DELETE", "/api/v1/providers/",                     "providers"),
    ("PUT",    "/api/v1/widget/config",                 "widget"),
    ("PATCH",  "/api/v1/guardrails/config",             "guardrails"),
    ("PATCH",  "/api/v1/cache/config",                  "cache"),
    ("PATCH",  "/api/v1/rate-limits/config",            "rate_limits"),
    ("POST",   "/api/v1/escalation/rules",              "escalation"),
    ("PATCH",  "/api/v1/escalation/rules/",             "escalation"),
    ("DELETE", "/api/v1/escalation/rules/",             "escalation"),
    ("PUT",    "/api/v1/escalation/channels/",          "escalation"),
    ("PUT",    "/api/v1/notifications/rules/",          "notifications"),
    ("POST",   "/api/v1/sources/upload",                "sources"),
    ("PATCH",  "/api/v1/sources/",                      "sources"),
    ("DELETE", "/api/v1/sources/",                      "sources"),
    ("POST",   "/api/v1/sources/bulk/",                 "sources"),
    ("POST",   "/api/v1/faq",                           "faq"),
    ("PATCH",  "/api/v1/faq/",                          "faq"),
    ("DELETE", "/api/v1/faq/",                          "faq"),
    ("PUT",    "/api/v1/integrations/oauth",            "integrations"),
]


def _match_route(method: str, path: str) -> str | None:
    for route_method, route_prefix, trigger in _VERSIONED_ROUTES:
        if method == route_method and path.startswith(route_prefix):
            return trigger
    return None


def _extract_user_id(request: Request) -> uuid.UUID | None:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


async def _capture_background(user_id: uuid.UUID, trigger_source: str) -> None:
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.monitoring.versions import capture_snapshot

        async with AsyncSessionLocal() as db:
            await capture_snapshot(db, user_id=user_id, trigger_source=trigger_source)
            await db.commit()
    except Exception as exc:
        log.warning("versioning.background_capture_failed", error=str(exc), trigger=trigger_source)


class VersioningMiddleware:
    """
    Pure ASGI middleware — captures system snapshots after successful mutations.

    Does NOT inherit BaseHTTPMiddleware intentionally: avoids anyio TaskGroup
    wrapping that causes nested ExceptionGroups when exceptions propagate from
    inner middleware/endpoint layers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        response_status: list[int] = []  # mutable container for closure

        async def capture_send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_status.append(message["status"])
            await send(message)

        # Let the request pass through normally — exceptions propagate without wrapping
        await self.app(scope, receive, capture_send)

        # Fire-and-forget snapshot only after a successful mutation response
        if response_status and 200 <= response_status[0] < 300:
            trigger_source = _match_route(request.method, request.url.path)
            if trigger_source is not None:
                user_id = _extract_user_id(request)
                if user_id:
                    asyncio.create_task(_capture_background(user_id, trigger_source))
                else:
                    log.warning("versioning.no_user_id", path=request.url.path,
                                method=request.method, trigger=trigger_source)
