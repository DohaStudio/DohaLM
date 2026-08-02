"""Fail-closed placeholder for a future deployment-approved DohaLM adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator

from src.inference.base import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderStatus,
    ProviderUnavailableError,
)


class DohaLMAdapterProvider:
    provider_name = "dohalm-adapter"
    model_id = "dohalm-v0.3"
    adapter_path = None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_name, self.model_id, ProviderStatus.NOT_AVAILABLE)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        del request
        raise ProviderUnavailableError(
            "ADAPTER_NOT_AVAILABLE",
            "No deployment-approved DohaLM adapter is configured.",
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        del request
        raise ProviderUnavailableError(
            "ADAPTER_NOT_AVAILABLE",
            "No deployment-approved DohaLM adapter is configured.",
        )
        yield  # pragma: no cover

    async def close(self) -> None:
        return None
