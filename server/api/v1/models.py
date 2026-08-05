"""Provider and model discovery endpoint."""

from fastapi import APIRouter, Depends

from server.api.dependencies import get_registry
from server.schemas.model import AdapterRuntimeMetadata, ModelInfo, ModelListResponse
from src.inference import ProviderRegistry

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def models(
    registry: ProviderRegistry = Depends(get_registry),
) -> ModelListResponse:
    values = []
    for provider in registry.providers:
        state = await provider.health()
        values.append(
            ModelInfo(
                id=state.model_id,
                provider=state.name,
                status=state.status.value,
                capabilities=["chat", "streaming"],
                runtime_metadata=(
                    AdapterRuntimeMetadata(
                        adapter_name=state.runtime_metadata.adapter_name,
                        adapter_version=state.runtime_metadata.adapter_version,
                        base_model=state.runtime_metadata.base_model,
                        base_revision=state.runtime_metadata.base_revision,
                        runtime_status=state.runtime_metadata.runtime_status,
                    )
                    if state.runtime_metadata is not None
                    else None
                ),
            )
        )
    return ModelListResponse(
        active_provider=registry.active_provider_name, models=values
    )
