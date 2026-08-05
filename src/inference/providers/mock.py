"""Deterministic, offline inference provider for API development."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from src.inference.base import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderStatus,
)


class MockProvider:
    provider_name = "mock"
    model_id = "dohalm-mock-v1"

    def __init__(self, *, chunk_delay_ms: int = 20) -> None:
        self._chunk_delay_seconds = chunk_delay_ms / 1000

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_name, self.model_id, ProviderStatus.READY)

    async def startup(self) -> None:
        return None

    @staticmethod
    def _response(request: GenerationRequest) -> str:
        user_content = request.messages[-1].content
        summary = re.sub(r"\s+", " ", user_content).strip()[:120]
        return f'DohaLM Mock 응답입니다. 입력하신 질문은 "{summary}"입니다.'

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(content=self._response(request))

    async def stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[GenerationChunk]:
        parts = re.findall(r"\S+\s*", self._response(request))
        for part in parts:
            if self._chunk_delay_seconds:
                await asyncio.sleep(self._chunk_delay_seconds)
            yield GenerationChunk(content=part)

    async def close(self) -> None:
        return None
