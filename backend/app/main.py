from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import admin, auth, integrations, meetings, memos, misc, projects, providers, transcripts
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.integrations.errors import IntegrationError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.embedded_worker:
        from app.worker import start_embedded_worker

        worker = start_embedded_worker()
        yield
        worker.stop()
    else:
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_environment()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Product Core (Workstream 1) and meeting-platform integrations (Workstream 2) API. "
            "All endpoints are under /api/v1."
        ),
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    @app.exception_handler(IntegrationError)
    async def _integration_error(_: Request, exc: IntegrationError) -> Response:
        return integrations.integration_error_response(exc)

    if settings.trusted_hosts and "*" not in settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    if settings.cors_allowed_origins:
        # The browser normally talks to the API through the same-origin Next.js
        # proxy; CORS is only needed for explicitly listed origins.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response

    api = APIRouter(prefix="/api/v1")
    for module in (auth, projects, meetings, transcripts, memos, providers, misc, admin, integrations):
        api.include_router(module.router)
    api.include_router(misc.health_router)
    app.include_router(api)
    return app


app = create_app()
