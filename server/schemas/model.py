"""Model discovery schemas without filesystem disclosure."""

from server.schemas.common import StrictModel


class AdapterRuntimeMetadata(StrictModel):
    adapter_name: str
    adapter_version: str
    base_model: str
    base_revision: str
    runtime_status: str


class ModelInfo(StrictModel):
    id: str
    provider: str
    status: str
    capabilities: list[str]
    runtime_metadata: AdapterRuntimeMetadata | None = None


class ModelListResponse(StrictModel):
    active_provider: str
    models: list[ModelInfo]
