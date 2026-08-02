"""Model discovery schemas without filesystem disclosure."""

from server.schemas.common import StrictModel


class ModelInfo(StrictModel):
    id: str
    provider: str
    status: str
    capabilities: list[str]


class ModelListResponse(StrictModel):
    active_provider: str
    models: list[ModelInfo]
