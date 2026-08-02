"""Fail-closed placeholder for a future deployment-approved Qwen provider."""

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


class BaseQwenProvider:
    provider_name = "base-qwen"
    model_id = "Qwen/Qwen2.5-1.5B-Instruct"
    revision = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_name, self.model_id, ProviderStatus.NOT_LOADED)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        del request
        raise ProviderUnavailableError(
            "MODEL_NOT_LOADED",
            "Base Qwen provider is configured but not loaded.",
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        del request
        raise ProviderUnavailableError(
            "MODEL_NOT_LOADED",
            "Base Qwen provider is configured but not loaded.",
        )
        yield  # pragma: no cover

    async def close(self) -> None:
        return None
