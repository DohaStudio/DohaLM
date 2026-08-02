"""Stable inference provider contracts for service integrations."""

from src.inference.base import (
    GenerationChunk,
    GenerationParameters,
    GenerationRequest,
    GenerationResult,
    InferenceMessage,
    InferenceProvider,
    ProviderHealth,
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
    "ProviderRegistry",
    "ProviderStatus",
    "ProviderUnavailableError",
    "create_provider_registry",
]
