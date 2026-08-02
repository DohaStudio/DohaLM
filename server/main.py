"""DohaLM FastAPI application factory and ASGI entry point."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.api.v1 import api_router
from server.api.v1.health import router as health_router
from server.core.config import APISettings
from server.core.errors import APIError, error_payload, install_exception_handlers
from server.core.logging import configure_server_logging
from server.core.request_id import REQUEST_ID_HEADER, request_id
from server.services.inference import InferenceService
from src.inference import ProviderRegistry, create_provider_registry

RegistryFactory = Callable[[APISettings], ProviderRegistry]


def _default_registry(settings: APISettings) -> ProviderRegistry:
    return create_provider_registry(
        settings.inference_provider,
        chunk_delay_ms=settings.stream_chunk_delay_ms,
    )


def create_app(
    settings: APISettings | None = None,
    *,
    registry_factory: RegistryFactory = _default_registry,
) -> FastAPI:
    resolved = settings or APISettings()
    logger = configure_server_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        registry = registry_factory(resolved)
        application.state.settings = resolved
        application.state.provider_registry = registry
        application.state.inference_service = InferenceService(
            registry.active,
            timeout_seconds=resolved.request_timeout_seconds,
        )
        await registry.active.health()
        try:
            yield
        finally:
            await registry.close()

    application = FastAPI(
        title="DohaLM API",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    application.state.logger = logger
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        identifier = request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = identifier
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > resolved.max_request_body_bytes:
            error = APIError(
                "VALIDATION_ERROR",
                "Request body is too large.",
                status_code=413,
            )
            return JSONResponse(
                error_payload(error, identifier),
                status_code=413,
                headers={REQUEST_ID_HEADER: identifier},
            )
        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = identifier
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "request_complete request_id=%s method=%s path=%s status_code=%s duration_ms=%.3f",
            identifier,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(api_router(), prefix=resolved.api_prefix)
    return application


app = create_app()
