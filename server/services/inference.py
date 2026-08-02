"""Timeout-aware inference service with provider error translation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from src.inference import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    InferenceProvider,
    ProviderUnavailableError,
)

from server.core.errors import APIError


class InferenceService:
    def __init__(self, provider: InferenceProvider, *, timeout_seconds: float) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            return await asyncio.wait_for(
                self.provider.generate(request),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            raise APIError(
                "INFERENCE_TIMEOUT",
                "Inference request timed out.",
                status_code=504,
            ) from None
        except ProviderUnavailableError as exc:
            raise APIError(exc.code, exc.safe_message, status_code=503) from None
        except asyncio.CancelledError:
            raise
        except Exception:
            raise APIError(
                "INFERENCE_FAILED",
                "Inference request failed.",
                status_code=500,
            ) from None

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return self.provider.stream(request)
