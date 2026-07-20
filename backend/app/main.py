from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sqlalchemy import select, update
from sqlalchemy.exc import TimeoutError as SQLATimeoutError

from app.api.v1.router import router as v1_router
from app.core.exceptions import DomainError
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.enums import SourceStatus
from app.models.source import Source
from app.services.system.seed import seed_first_admin, seed_defaults
from app.services.system.settings import seed_default_settings
from app.services.system.rbac import seed_rbac
from app.services.ai.embedding import _get_dense_model, _get_sparse_model
from app.services.ai.guardrails import _get_presidio_analyzer, _get_presidio_anonymizer
from app.services.system import scheduler
from app.core.versioning import VersioningMiddleware
from fastapi.exceptions import HTTPException, RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(debug=settings.DEBUG)
    logger.info("Starting up", app=settings.APP_NAME, version=settings.APP_VERSION, env=settings.ENVIRONMENT)

    async with AsyncSessionLocal() as db:
        try:
            await seed_first_admin(db)
            await seed_defaults(db)
            await seed_default_settings(db)
            await seed_rbac(db)
        except Exception:
            logger.exception("startup.seed_failed — revisar logs anteriores para detalle")
            raise

        # MySQL no soporta RETURNING en UPDATE — SELECT previo para contar,
        # luego UPDATE sin RETURNING.
        stuck_result = await db.execute(
            select(Source.id)
            .where(Source.status == SourceStatus.processing, Source.deleted_at.is_(None))
        )
        stuck_ids = stuck_result.fetchall()
        if stuck_ids:
            await db.execute(
                update(Source)
                .where(Source.status == SourceStatus.processing, Source.deleted_at.is_(None))
                .values(
                    status=SourceStatus.error,
                    error_message="Ingesta interrumpida por reinicio del servidor. Use 'Reingestar' para volver a intentarlo.",
                )
            )
            await db.commit()
            logger.warning("startup.reset_stuck_sources", count=len(stuck_ids))

    from app.services.ingestion.vector_store import ensure_collection
    await ensure_collection()

    import asyncio

    async def _background_warmup():
        loop = asyncio.get_running_loop()
        logger.info("startup.prewarming_models_and_guardrails")
        try:
            await asyncio.gather(
                loop.run_in_executor(None, _get_dense_model),
                loop.run_in_executor(None, _get_sparse_model),
                loop.run_in_executor(None, _get_presidio_analyzer),
                loop.run_in_executor(None, _get_presidio_anonymizer),
            )
            logger.info("startup.prewarming_complete")
        except Exception:
            logger.exception("startup.prewarming_failed")
        try:
            from app.services.ai.guardrails import reload_custom_patterns
            async with AsyncSessionLocal() as db:
                await reload_custom_patterns(db)
            logger.info("startup.custom_guardrail_patterns_loaded")
        except Exception:
            logger.warning("startup.custom_guardrail_patterns_load_failed")

    asyncio.create_task(_background_warmup())

    scheduler.start()

    yield

    scheduler.stop()

    from app.services.ai.llm_gateway import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

    logger.info("Shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    _is_prod = settings.ENVIRONMENT == "production"
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if _is_prod else "/api/docs",
        redoc_url=None if _is_prod else "/api/redoc",
        openapi_url=None if _is_prod else "/api/openapi.json",
        lifespan=lifespan,
    )

    _admin_origins = set(settings.ALLOWED_ORIGINS)
    _admin_origins_wildcard = "*" in _admin_origins

    async def _validate_json_body(request: Request) -> None:
        """Valida tamaño y profundidad del JSON para prevenir DoS."""
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" not in content_type:
            return
        body = await request.body()
        if len(body) > settings.MAX_JSON_BODY_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"Payload too large. Maximum size is {settings.MAX_JSON_BODY_SIZE_MB}MB.",
            )
        try:
            data = json.loads(body.decode("utf-8"))

            def check_depth(obj, current_depth=0):
                if current_depth > settings.MAX_JSON_DEPTH:
                    raise ValueError(f"JSON depth exceeds maximum of {settings.MAX_JSON_DEPTH}")
                if isinstance(obj, dict):
                    return max((check_depth(v, current_depth + 1) for v in obj.values()), default=0)
                if isinstance(obj, list):
                    return max((check_depth(i, current_depth + 1) for i in obj), default=0)
                return current_depth

            check_depth(data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    class JsonBodyValidationMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if "application/json" in request.headers.get("content-type", "").lower():
                try:
                    await _validate_json_body(request)
                except HTTPException as e:
                    return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
            return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(req: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = first.get("loc", ())
        field = " → ".join(str(p) for p in loc if p != "body")
        msg = first.get("msg", "Datos inválidos")
        detail = f"{field}: {msg}" if field else msg
        logger.warning("request_validation_error", path=req.url.path, field=field, msg=msg)
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(ResponseValidationError)
    async def response_validation_error_handler(req: Request, exc: ResponseValidationError):
        # Be defensive: exc.errors() includes the offending `input` value, and
        # been closed, calling repr() on it raises DetachedInstanceError —
        # which masks the actual response-validation problem in the logs.
        try:
            errors_repr = str(exc.errors())[:1500]
        except Exception as repr_err:
            errors_repr = f"<could not stringify exc.errors(): {type(repr_err).__name__}: {repr_err}>"
        try:
            error_summary = repr(exc)[:500]
        except Exception:
            error_summary = type(exc).__name__
        logger.error(
            "response_validation_error",
            path=req.url.path,
            method=req.method,
            error=error_summary,
            errors=errors_repr,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Ocurrió un error interno. Inténtelo de nuevo más tarde."},
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(req: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(SQLATimeoutError)
    async def db_pool_exhausted_handler(req: Request, exc: SQLATimeoutError):
        logger.warning("db_pool_exhausted", path=req.url.path, method=req.method, error=repr(exc)[:300])
        return JSONResponse(
            status_code=503,
            content={"detail": "El asistente está muy solicitado en este momento. Inténtelo de nuevo en unos segundos."},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(req: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path=req.url.path,
            method=req.method,
            error=repr(exc)[:500],
        )
        origin = req.headers.get("origin", "")
        headers: dict[str, str] = {}
        if origin and (_admin_origins_wildcard or origin in _admin_origins):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor."},
            headers=headers,
        )

    # Public paths (widget, auth login, health): open origins, NO credentials
    # Admin paths: restricted to ALLOWED_ORIGINS with credentials
    _PUBLIC_PREFIXES = (
        "/api/v1/widget/public/",
        "/api/v1/auth/login",
        "/api/v1/health",
        "/widget/",           # static widget JS assets
    )
    _ALLOWED_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    _ALLOWED_HEADERS = "Authorization, Content-Type, X-Session-ID, X-Widget-Key, X-Environment"
    class SplitCORSMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            origin = request.headers.get("origin", "")
            path = request.url.path
            is_public = any(path.startswith(p) for p in _PUBLIC_PREFIXES)
            is_admin_allowed = origin and (_admin_origins_wildcard or origin in _admin_origins)

            if request.method == "OPTIONS":
                headers: dict[str, str] = {
                    "Access-Control-Allow-Methods": _ALLOWED_METHODS,
                    "Access-Control-Allow-Headers": _ALLOWED_HEADERS,
                    "Access-Control-Max-Age": "600",
                }
                if is_public:
                    headers["Access-Control-Allow-Origin"] = origin or "*"
                elif is_admin_allowed:
                    headers["Access-Control-Allow-Origin"] = origin
                    headers["Access-Control-Allow-Credentials"] = "true"
                else:
                    return Response(status_code=403)
                return Response(status_code=204, headers=headers)

            response = await call_next(request)

            if is_public:
                response.headers["Access-Control-Allow-Origin"] = origin or "*"
                response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
            elif is_admin_allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS

            return response

    app.add_middleware(SplitCORSMiddleware)

    app.add_middleware(JsonBodyValidationMiddleware)

    app.add_middleware(VersioningMiddleware)

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        """Add security headers to all responses."""
        async def dispatch(self, request: Request, call_next) -> Response:
            response = await call_next(request)
            
            # Content Security Policy - restrict resources
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self';"
            )
            response.headers["Content-Security-Policy"] = csp
            
            # Other security headers
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            
            # HSTS (only in production)
            settings = get_settings()
            if settings.ENVIRONMENT == "production":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(v1_router, prefix="/api/v1")

    widget_dir = Path(__file__).parent.parent / "static" / "widget"
    if widget_dir.is_dir():
        app.mount("/widget", StaticFiles(directory=str(widget_dir)), name="widget-static")

    return app

app = create_app()
