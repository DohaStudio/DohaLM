"""Fail-closed provider registry and application-lifetime factory."""

from __future__ import annotations

from collections.abc import Iterable

from src.inference.base import InferenceProvider
from src.inference.providers import BaseQwenProvider, DohaLMAdapterProvider, MockProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[InferenceProvider], active_provider: str) -> None:
        self._providers = {provider.provider_name: provider for provider in providers}
        if active_provider not in self._providers:
            raise ValueError("UNKNOWN_INFERENCE_PROVIDER")
        self.active_provider_name = active_provider

    @property
    def active(self) -> InferenceProvider:
        return self._providers[self.active_provider_name]

    @property
    def providers(self) -> tuple[InferenceProvider, ...]:
        return tuple(self._providers.values())

    async def close(self) -> None:
        for provider in self.providers:
            await provider.close()


def create_provider_registry(active_provider: str, *, chunk_delay_ms: int = 20) -> ProviderRegistry:
    return ProviderRegistry(
        (
            MockProvider(chunk_delay_ms=chunk_delay_ms),
            BaseQwenProvider(),
            DohaLMAdapterProvider(),
        ),
        active_provider=active_provider,
    )
