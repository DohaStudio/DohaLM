"""Process liveness and active-provider readiness endpoints."""

from fastapi import APIRouter, Depends

from server.api.dependencies import get_registry
from server.core.errors import APIError
from server.schemas.health import HealthResponse, ReadinessResponse
from src.inference import ProviderRegistry, ProviderStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="dohalm-api", version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(registry: ProviderRegistry = Depends(get_registry)) -> ReadinessResponse:
    provider = await registry.active.health()
    if provider.status is not ProviderStatus.READY:
        raise APIError(
            "PROVIDER_NOT_READY",
            "The active inference provider is not ready.",
            status_code=503,
        )
    return ReadinessResponse(
        status="ready",
        provider={
            "name": provider.name,
            "model_id": provider.model_id,
            "status": provider.status.value,
        },
    )
