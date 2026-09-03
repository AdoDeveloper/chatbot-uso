"""
Middleware de versionado: captura automáticamente snapshots del sistema tras mutaciones.
Tarea asyncio fire-and-forget, sin latencia adicional para la respuesta.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import MutableMapping
from typing import Any

import jwt as pyjwt
import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import decode_token

log = structlog.get_logger()

# Retiene las tareas de create_task (referencia débil del event loop, si no
# se recolectan a mitad de ejecución); discard() en done_callback las limpia.
_background_tasks: set[asyncio.Task] = set()

# Mapea (método HTTP, prefijo de path) → etiqueta trigger_source
#
# Solo se versiona la configuración del asistente: lo que define cómo responde
# el chatbot. Quedan fuera a propósito la gestión de contenido (documentos y
# FAQ, que el rollback nunca revierte) y los ajustes operativos del sistema
# (cache, rate limits, notificaciones, integraciones).
_VERSIONED_ROUTES: list[tuple[str, str, str]] = [
    ("PUT",    "/api/v1/settings",                      "settings"),
    ("POST",   "/api/v1/providers",                     "providers"),
    ("PATCH",  "/api/v1/providers/",                     "providers"),
    ("DELETE", "/api/v1/providers/",                     "providers"),
    ("PUT",    "/api/v1/widget/config",                 "widget"),
    ("PATCH",  "/api/v1/guardrails/config",             "guardrails"),
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
    Middleware ASGI puro: captura snapshots del sistema tras mutaciones exitosas.

    No hereda de BaseHTTPMiddleware a propósito: evita el wrapping con anyio
    TaskGroup, que genera ExceptionGroups anidados cuando las excepciones
    se propagan desde capas internas de middleware/endpoint.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        response_status: list[int] = []  # contenedor mutable para el closure

        async def capture_send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_status.append(message["status"])
            await send(message)

        # Deja pasar la petición con normalidad: las excepciones se propagan sin envoltura
        await self.app(scope, receive, capture_send)

        # Snapshot fire-and-forget solo tras una respuesta de mutación exitosa
        if response_status and 200 <= response_status[0] < 300:
            trigger_source = _match_route(request.method, request.url.path)
            if trigger_source is not None:
                user_id = _extract_user_id(request)
                if user_id:
                    task = asyncio.create_task(_capture_background(user_id, trigger_source))
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
                else:
                    log.warning("versioning.no_user_id", path=request.url.path,
                                method=request.method, trigger=trigger_source)
