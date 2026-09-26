"""Application entry point.

Assembles middleware, routers, error handling and the scheduler lifecycle.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import error_response, register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import engine
from app.schemas.ops import HealthOut

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()

    problems = settings.validate_for_production()
    if problems:
        for problem in problems:
            logger.error("Production configuration problem: %s", problem)
        raise RuntimeError(
            "Refusing to start in production with an insecure configuration: "
            + " ".join(problems)
        )

    # Registering the real agent implementations has to happen after every
    # service module is importable, which is why it is done here.
    from app.agents.wiring import wire_agents

    wire_agents()

    if settings.scheduler_enabled:
        try:
            from app.agents.registry import bootstrap_schedules
            from app.db.session import session_scope
            from app.services.scheduler import scheduler

            # Seed agent + schedule rows for every existing user before the
            # scheduler reconciles, so scheduled agents fire on their own cron
            # without requiring a visit to the Automations screen first.
            with session_scope() as db:
                bootstrap_schedules(db)

            scheduler.start()
        except Exception as exc:
            # A scheduler that cannot start must not take the API down with it.
            logger.error("Scheduler failed to start: %s", exc)

    logger.info(
        "%s %s started in %s mode.", settings.app_name, settings.app_version, settings.environment
    )
    yield

    try:
        from app.services.scheduler import scheduler

        scheduler.shutdown()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Attach a request id, time the request, and log the outcome."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception:
            duration = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "duration_ms": duration,
                },
            )
            raise

        duration = int((time.perf_counter() - started) * 1000)
        response.headers["x-request-id"] = request_id

        # Baseline hardening headers. HSTS is only meaningful over TLS.
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        if settings.is_production:
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"

        logger.info(
            "%s %s -> %s", request.method, request.url.path, response.status_code,
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration,
                "user_id": getattr(request.state, "user_id", None),
            },
        )
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", response_model=HealthOut, tags=["health"])
    def health() -> HealthOut:
        return HealthOut(
            status="ok", version=settings.app_version, environment=settings.environment
        )

    @app.get("/health/ready", tags=["health"])
    def ready() -> Response:
        """Readiness depends on the database actually answering."""
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.error("Readiness check failed: %s", exc)
            return error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "not_ready",
                "The database is not reachable.",
            )
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "ready", "database": "ok"})

    return app


app = create_app()
