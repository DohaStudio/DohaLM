"""Provider and model discovery endpoint."""

from fastapi import APIRouter, Depends

from server.api.dependencies import get_registry
from server.schemas.model import ModelInfo, ModelListResponse
from src.inference import ProviderRegistry

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def models(registry: ProviderRegistry = Depends(get_registry)) -> ModelListResponse:
    values = []
    for provider in registry.providers:
        state = await provider.health()
        values.append(
            ModelInfo(
                id=state.model_id,
                provider=state.name,
                status=state.status.value,
                capabilities=["chat", "streaming"],
            )
        )
    return ModelListResponse(active_provider=registry.active_provider_name, models=values)
