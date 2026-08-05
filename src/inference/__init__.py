"""Stable inference provider contracts for service integrations."""

from src.inference.base import (
    GenerationChunk,
    GenerationParameters,
    GenerationRequest,
    GenerationResult,
    InferenceMessage,
    InferenceProvider,
    ProviderHealth,
    ProviderRuntimeMetadata,
    ProviderStatus,
    ProviderUnavailableError,
)
from src.inference.registry import ProviderRegistry, create_provider_registry

__all__ = [
    "GenerationChunk",
    "GenerationParameters",
    "GenerationRequest",
    "GenerationResult",
    "InferenceMessage",
    "InferenceProvider",
    "ProviderHealth",
    "ProviderRuntimeMetadata",
    "ProviderRegistry",
    "ProviderStatus",
    "ProviderUnavailableError",
    "create_provider_registry",
]
