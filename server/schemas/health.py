"""Liveness and readiness schemas."""

from server.schemas.common import StrictModel


class HealthResponse(StrictModel):
    status: str
    service: str
    version: str


class ProviderStatusResponse(StrictModel):
    name: str
    model_id: str
    status: str


class ReadinessResponse(StrictModel):
    status: str
    provider: ProviderStatusResponse
