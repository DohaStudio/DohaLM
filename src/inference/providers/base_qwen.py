"""Lazy, offline-only Base Qwen provider for the local FastAPI service."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress

from src.inference.base import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderStatus,
    ProviderUnavailableError,
)
from src.inference.generation import generate_sync, start_stream, stream_end_marker
from src.inference.model_loader import (
    BASE_QWEN_MODEL_ID,
    BASE_QWEN_REVISION,
    BaseQwenConfig,
    LoadedBaseQwen,
    load_base_qwen,
    release_cuda_cache,
    unload_base_qwen,
)

Loader = Callable[[BaseQwenConfig], LoadedBaseQwen]
Generator = Callable[
    [LoadedBaseQwen, GenerationRequest, threading.Event], GenerationResult
]
StreamerFactory = Callable[[LoadedBaseQwen, GenerationRequest], object]


class BaseQwenProvider:
    provider_name = "base-qwen"
    model_id = BASE_QWEN_MODEL_ID
    revision = BASE_QWEN_REVISION

    def __init__(
        self,
        config: BaseQwenConfig | None = None,
        *,
        loader: Loader = load_base_qwen,
        generator: Generator = generate_sync,
        streamer_factory: StreamerFactory = start_stream,
    ) -> None:
        self.config = config or BaseQwenConfig()
        self.model_id = self.config.model_id
        self.revision = self.config.revision
        self._loader = loader
        self._generator = generator
        self._streamer_factory = streamer_factory
        self._loaded: LoadedBaseQwen | None = None
        self._status = ProviderStatus.NOT_LOADED
        self._state_lock = asyncio.Lock()
        self._load_task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_generations)
        self._logger = logging.getLogger("dohalm.api")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_name, self.model_id, self._status)

    async def _load_and_publish(self) -> None:
        started = time.perf_counter()
        try:
            loaded = await asyncio.to_thread(self._loader, self.config)
        except Exception:
            async with self._state_lock:
                self._status = ProviderStatus.ERROR
            self._logger.error(
                "model_load_failed provider=%s model_id=%s revision=%s",
                self.provider_name,
                self.model_id,
                self.revision,
            )
            return
        async with self._state_lock:
            if self._status is ProviderStatus.UNLOADING:
                await asyncio.to_thread(unload_base_qwen, loaded)
                release_cuda_cache(loaded)
                return
            self._loaded = loaded
            self._status = ProviderStatus.READY
        self._logger.info(
            "model_load_complete provider=%s model_id=%s revision=%s quantization=%s duration_ms=%.3f allocated_vram_bytes=%s",
            self.provider_name,
            self.model_id,
            self.revision,
            self.config.quantization,
            (time.perf_counter() - started) * 1000,
            loaded.allocated_vram_bytes,
        )

    async def _ensure_loaded(self) -> LoadedBaseQwen:
        async with self._state_lock:
            if self._status is ProviderStatus.READY and self._loaded is not None:
                return self._loaded
            if self._status is ProviderStatus.ERROR:
                raise ProviderUnavailableError(
                    "MODEL_LOAD_FAILED", "The local model could not be loaded."
                )
            if self._status is ProviderStatus.UNLOADING:
                raise ProviderUnavailableError(
                    "MODEL_UNLOADING", "The local model is unloading."
                )
            if self._load_task is None:
                self._status = ProviderStatus.LOADING
                self._load_task = asyncio.create_task(self._load_and_publish())
            load_task = self._load_task
        try:
            await asyncio.wait_for(
                asyncio.shield(load_task),
                timeout=self.config.load_timeout_seconds,
            )
        except TimeoutError:
            raise ProviderUnavailableError(
                "MODEL_LOAD_TIMEOUT",
                "The local model did not load within the configured timeout.",
            ) from None
        async with self._state_lock:
            if self._status is ProviderStatus.READY and self._loaded is not None:
                return self._loaded
        raise ProviderUnavailableError(
            "MODEL_LOAD_FAILED", "The local model could not be loaded."
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        loaded = await self._ensure_loaded()
        async with self._semaphore:
            started = time.perf_counter()
            cancel_event = threading.Event()
            task = asyncio.create_task(
                asyncio.to_thread(self._generator, loaded, request, cancel_event)
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self.config.generation_timeout_seconds,
                )
            except (TimeoutError, asyncio.CancelledError):
                cancel_event.set()
                with suppress(Exception):
                    await asyncio.shield(task)
                raise
            duration = time.perf_counter() - started
            peak = int(loaded.torch.cuda.max_memory_allocated(0))
            tokens_per_second = (
                result.completion_tokens / duration
                if result.completion_tokens is not None and duration
                else 0
            )
            self._logger.info(
                "generation_complete provider=%s model_id=%s prompt_tokens=%s completion_tokens=%s duration_ms=%.3f tokens_per_second=%.3f finish_reason=%s peak_vram_bytes=%s",
                self.provider_name,
                self.model_id,
                result.prompt_tokens,
                result.completion_tokens,
                duration * 1000,
                tokens_per_second,
                result.finish_reason,
                peak,
            )
            return result

    async def stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[GenerationChunk]:
        loaded = await self._ensure_loaded()
        async with self._semaphore:
            session = self._streamer_factory(loaded, request)
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.config.generation_timeout_seconds):
                    while True:
                        value = await asyncio.to_thread(session.next_text)
                        if value is stream_end_marker():
                            break
                        if value:
                            yield GenerationChunk(content=str(value))
                await asyncio.to_thread(session.join)
                if session.error:
                    raise RuntimeError("STREAM_WORKER_FAILED") from session.error[0]
                finish_reason = (
                    session.finish_reason[0] if session.finish_reason else "error"
                )
                yield GenerationChunk(content="", finish_reason=finish_reason)
                self._logger.info(
                    "stream_generation_complete provider=%s model_id=%s duration_ms=%.3f finish_reason=%s peak_vram_bytes=%s",
                    self.provider_name,
                    self.model_id,
                    (time.perf_counter() - started) * 1000,
                    finish_reason,
                    int(loaded.torch.cuda.max_memory_allocated(0)),
                )
            except (TimeoutError, asyncio.CancelledError):
                session.cancel()
                await asyncio.to_thread(session.join)
                raise
            finally:
                if not session.ended:
                    session.cancel()
                    await asyncio.to_thread(session.join)

    async def close(self) -> None:
        if not self.config.unload_on_shutdown:
            return
        async with self._state_lock:
            load_task = self._load_task
            self._status = ProviderStatus.UNLOADING
        if load_task is not None and not load_task.done():
            await asyncio.shield(load_task)
        for _ in range(self.config.max_concurrent_generations):
            await self._semaphore.acquire()
        try:
            loaded = self._loaded
            self._loaded = None
            if loaded is not None:
                await asyncio.to_thread(unload_base_qwen, loaded)
                release_cuda_cache(loaded)
            async with self._state_lock:
                self._status = ProviderStatus.NOT_LOADED
                self._load_task = None
        finally:
            for _ in range(self.config.max_concurrent_generations):
                self._semaphore.release()
