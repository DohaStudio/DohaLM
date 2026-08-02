"""Provider-neutral asynchronous inference contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ProviderStatus(str, Enum):
    READY = "ready"
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    UNLOADING = "unloading"
    NOT_AVAILABLE = "not_available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    model_id: str
    status: ProviderStatus


@dataclass(frozen=True)
class InferenceMessage:
    role: str
    content: str


@dataclass(frozen=True)
class GenerationParameters:
    max_new_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.9
    repetition_penalty: float = 1.05
    seed: int | None = None


@dataclass(frozen=True)
class GenerationRequest:
    messages: tuple[InferenceMessage, ...]
    generation: GenerationParameters


@dataclass(frozen=True)
class GenerationResult:
    content: str
    finish_reason: str = "stop"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class GenerationChunk:
    content: str
    finish_reason: str | None = None


class ProviderUnavailableError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = message


class InferenceProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    async def health(self) -> ProviderHealth: ...

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...

    async def close(self) -> None: ...
