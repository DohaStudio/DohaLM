"""Fail-closed lifecycle Provider for one explicit DohaLM PEFT adapter."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from src.inference.adapter_loader import (
    AdapterLoaderError,
    AdapterRuntimeHandle,
    load_peft_adapter_runtime,
    unload_peft_adapter_runtime,
)
from src.inference.adapter_manifest import (
    AdapterManifest,
    AdapterManifestError,
    load_adapter_manifest,
)
from src.inference.adapter_validation import (
    AdapterValidationError,
    AdapterValidationResult,
    validate_adapter_artifacts,
)
from src.inference.base import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderRuntimeMetadata,
    ProviderStatus,
    ProviderUnavailableError,
)
from src.inference.generation import generate_sync, start_stream, stream_end_marker
from src.inference.model_loader import LoadedBaseQwen


class AdapterProviderState(str, Enum):
    UNAVAILABLE = "unavailable"
    VALIDATING = "validating"
    VALIDATED_NOT_LOADED = "validated_not_loaded"
    LOADING = "loading"
    READY = "ready"
    INCOMPATIBLE = "incompatible"
    LOAD_FAILED = "load_failed"
    SHUTTING_DOWN = "shutting_down"
    CLOSED = "closed"


@dataclass(frozen=True)
class DohaLMAdapterConfig:
    manifest_path: Path | None = None
    adapter_root: Path | None = None
    base_model_path: Path | None = None
    load_timeout_seconds: float = 300
    generation_timeout_seconds: float = 120
    max_concurrent_generations: int = 1

    def __post_init__(self) -> None:
        if self.load_timeout_seconds <= 0 or self.generation_timeout_seconds <= 0:
            raise ValueError("ADAPTER_TIMEOUT_INVALID")
        if self.max_concurrent_generations < 1:
            raise ValueError("ADAPTER_CONCURRENCY_INVALID")


ManifestLoader = Callable[[Path], AdapterManifest]
ArtifactValidator = Callable[[AdapterManifest], AdapterValidationResult]
RuntimeLoader = Callable[..., AdapterRuntimeHandle]
RuntimeUnloader = Callable[[AdapterRuntimeHandle], bool]
Generator = Callable[
    [LoadedBaseQwen, GenerationRequest, threading.Event], GenerationResult
]
StreamerFactory = Callable[[LoadedBaseQwen, GenerationRequest], Any]

_STATE_STATUS = {
    AdapterProviderState.UNAVAILABLE: ProviderStatus.NOT_AVAILABLE,
    AdapterProviderState.VALIDATING: ProviderStatus.LOADING,
    AdapterProviderState.VALIDATED_NOT_LOADED: ProviderStatus.NOT_LOADED,
    AdapterProviderState.LOADING: ProviderStatus.LOADING,
    AdapterProviderState.READY: ProviderStatus.READY,
    AdapterProviderState.INCOMPATIBLE: ProviderStatus.UNAVAILABLE,
    AdapterProviderState.LOAD_FAILED: ProviderStatus.ERROR,
    AdapterProviderState.SHUTTING_DOWN: ProviderStatus.UNLOADING,
    AdapterProviderState.CLOSED: ProviderStatus.UNAVAILABLE,
}

_SAFE_MESSAGES = {
    "ADAPTER_NOT_AVAILABLE": "No approved local adapter is configured.",
    "ADAPTER_INCOMPATIBLE": "The configured adapter is incompatible.",
    "ADAPTER_LOAD_FAILED": "The configured adapter could not be loaded.",
    "PROVIDER_UNAVAILABLE": "The adapter provider is unavailable.",
}


class DohaLMAdapterProvider:
    provider_name = "dohalm-adapter"

    def __init__(
        self,
        config: DohaLMAdapterConfig | None = None,
        *,
        manifest_loader: ManifestLoader = load_adapter_manifest,
        artifact_validator: ArtifactValidator = validate_adapter_artifacts,
        runtime_loader: RuntimeLoader = load_peft_adapter_runtime,
        runtime_unloader: RuntimeUnloader = unload_peft_adapter_runtime,
        generator: Generator = generate_sync,
        streamer_factory: StreamerFactory = start_stream,
    ) -> None:
        self.config = config or DohaLMAdapterConfig()
        self.model_id = "dohalm-adapter"
        self._manifest_loader = manifest_loader
        self._artifact_validator = artifact_validator
        self._runtime_loader = runtime_loader
        self._runtime_unloader = runtime_unloader
        self._generator = generator
        self._streamer_factory = streamer_factory
        self._manifest: AdapterManifest | None = None
        self._validation: AdapterValidationResult | None = None
        self._handle: AdapterRuntimeHandle | None = None
        self._state = AdapterProviderState.UNAVAILABLE
        self._error_code = "ADAPTER_NOT_AVAILABLE"
        self._startup_attempted = False
        self._state_lock = asyncio.Lock()
        self._load_task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_generations)
        self._logger = logging.getLogger("dohalm.api")

    @property
    def state(self) -> AdapterProviderState:
        return self._state

    def _runtime_metadata(self) -> ProviderRuntimeMetadata | None:
        manifest = self._manifest
        if manifest is None:
            return None
        return ProviderRuntimeMetadata(
            adapter_name=manifest.adapter_name,
            adapter_version=manifest.adapter_version,
            base_model=manifest.base_model,
            base_revision=manifest.base_revision,
            runtime_status=self._state.value,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            self.provider_name,
            self.model_id,
            _STATE_STATUS[self._state],
            self._error_code,
            self._runtime_metadata(),
        )

    async def _set_failure(
        self,
        *,
        expected: AdapterProviderState,
        state: AdapterProviderState,
        error_code: str,
    ) -> None:
        async with self._state_lock:
            if self._state is expected:
                self._state = state
                self._error_code = error_code

    async def startup(self) -> None:
        async with self._state_lock:
            if self._startup_attempted or self._state is AdapterProviderState.CLOSED:
                return
            self._startup_attempted = True
            if any(
                value is None
                for value in (
                    self.config.manifest_path,
                    self.config.adapter_root,
                    self.config.base_model_path,
                )
            ):
                return
            self._state = AdapterProviderState.VALIDATING
            self._error_code = None
        assert self.config.manifest_path is not None
        try:
            manifest = await asyncio.to_thread(
                self._manifest_loader, self.config.manifest_path
            )
            validation = await asyncio.to_thread(self._artifact_validator, manifest)
        except AdapterManifestError as exc:
            unavailable = exc.code == "ADAPTER_MANIFEST_NOT_FOUND"
            await self._set_failure(
                expected=AdapterProviderState.VALIDATING,
                state=(
                    AdapterProviderState.UNAVAILABLE
                    if unavailable
                    else AdapterProviderState.INCOMPATIBLE
                ),
                error_code=(
                    "ADAPTER_NOT_AVAILABLE" if unavailable else "ADAPTER_INCOMPATIBLE"
                ),
            )
            return
        except AdapterValidationError:
            await self._set_failure(
                expected=AdapterProviderState.VALIDATING,
                state=AdapterProviderState.INCOMPATIBLE,
                error_code="ADAPTER_INCOMPATIBLE",
            )
            return
        except Exception:
            await self._set_failure(
                expected=AdapterProviderState.VALIDATING,
                state=AdapterProviderState.INCOMPATIBLE,
                error_code="ADAPTER_INCOMPATIBLE",
            )
            return
        async with self._state_lock:
            if self._state is not AdapterProviderState.VALIDATING:
                return
            self._manifest = manifest
            self._validation = validation
            self.model_id = f"{manifest.adapter_name}@{manifest.adapter_version}"
            self._state = AdapterProviderState.VALIDATED_NOT_LOADED
            self._error_code = None

    def _public_error(self) -> ProviderUnavailableError:
        code = self._error_code or "PROVIDER_UNAVAILABLE"
        return ProviderUnavailableError(code, _SAFE_MESSAGES[code])

    async def _load_and_publish(self) -> None:
        manifest = self._manifest
        validation = self._validation
        if manifest is None or validation is None:
            await self._set_failure(
                expected=AdapterProviderState.LOADING,
                state=AdapterProviderState.INCOMPATIBLE,
                error_code="ADAPTER_INCOMPATIBLE",
            )
            return
        started = time.perf_counter()
        try:
            handle = await asyncio.to_thread(
                self._runtime_loader,
                manifest=manifest,
                validation=validation,
                base_model_path=self.config.base_model_path,
                adapter_root=self.config.adapter_root,
            )
        except AdapterLoaderError as exc:
            load_failed = exc.code in {"ADAPTER_LOAD_FAILED", "ADAPTER_UNLOAD_FAILED"}
            await self._set_failure(
                expected=AdapterProviderState.LOADING,
                state=(
                    AdapterProviderState.LOAD_FAILED
                    if load_failed
                    else AdapterProviderState.INCOMPATIBLE
                ),
                error_code=(
                    "ADAPTER_LOAD_FAILED" if load_failed else "ADAPTER_INCOMPATIBLE"
                ),
            )
            return
        except Exception:
            await self._set_failure(
                expected=AdapterProviderState.LOADING,
                state=AdapterProviderState.LOAD_FAILED,
                error_code="ADAPTER_LOAD_FAILED",
            )
            return
        async with self._state_lock:
            if self._state is not AdapterProviderState.LOADING:
                publish = False
            else:
                self._handle = handle
                self._state = AdapterProviderState.READY
                self._error_code = None
                publish = True
        if not publish:
            with suppress(Exception):
                await asyncio.to_thread(self._runtime_unloader, handle)
            return
        self._logger.info(
            "adapter_load_complete provider=%s adapter_name=%s adapter_version=%s duration_ms=%.3f",
            self.provider_name,
            manifest.adapter_name,
            manifest.adapter_version,
            (time.perf_counter() - started) * 1000,
        )

    async def _ensure_loaded(self) -> AdapterRuntimeHandle:
        async with self._state_lock:
            if self._state is AdapterProviderState.READY and self._handle is not None:
                return self._handle
            if self._state is AdapterProviderState.VALIDATED_NOT_LOADED:
                self._state = AdapterProviderState.LOADING
                self._load_task = asyncio.create_task(self._load_and_publish())
            elif self._state is not AdapterProviderState.LOADING:
                raise self._public_error()
            load_task = self._load_task
        if load_task is None:
            raise self._public_error()
        try:
            await asyncio.wait_for(
                asyncio.shield(load_task), timeout=self.config.load_timeout_seconds
            )
        except TimeoutError:
            async with self._state_lock:
                if self._state is AdapterProviderState.LOADING:
                    self._state = AdapterProviderState.LOAD_FAILED
                    self._error_code = "ADAPTER_LOAD_FAILED"
            raise ProviderUnavailableError(
                "ADAPTER_LOAD_FAILED", _SAFE_MESSAGES["ADAPTER_LOAD_FAILED"]
            ) from None
        async with self._state_lock:
            if self._state is AdapterProviderState.READY and self._handle is not None:
                return self._handle
            raise self._public_error()

    @staticmethod
    def _loaded(handle: AdapterRuntimeHandle) -> LoadedBaseQwen:
        return LoadedBaseQwen(handle.tokenizer, handle.model, handle.torch, 0)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        handle = await self._ensure_loaded()
        async with self._semaphore:
            if self._state is not AdapterProviderState.READY:
                raise self._public_error()
            cancel_event = threading.Event()
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._generator, self._loaded(handle), request, cancel_event
                )
            )
            try:
                return await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self.config.generation_timeout_seconds,
                )
            except (TimeoutError, asyncio.CancelledError):
                cancel_event.set()
                with suppress(Exception):
                    await asyncio.shield(task)
                raise

    async def stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[GenerationChunk]:
        handle = await self._ensure_loaded()
        async with self._semaphore:
            if self._state is not AdapterProviderState.READY:
                raise self._public_error()
            session = self._streamer_factory(self._loaded(handle), request)
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
            except (TimeoutError, asyncio.CancelledError):
                session.cancel()
                await asyncio.to_thread(session.join)
                raise
            finally:
                if not session.ended:
                    session.cancel()
                    await asyncio.to_thread(session.join)

    async def close(self) -> None:
        async with self._state_lock:
            if self._state is AdapterProviderState.CLOSED:
                return
            self._state = AdapterProviderState.SHUTTING_DOWN
            self._error_code = "PROVIDER_UNAVAILABLE"
            load_task = self._load_task
        if load_task is not None and not load_task.done():
            with suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(
                    asyncio.shield(load_task), timeout=self.config.load_timeout_seconds
                )
        acquired = 0
        try:
            async with asyncio.timeout(self.config.generation_timeout_seconds):
                for _ in range(self.config.max_concurrent_generations):
                    await self._semaphore.acquire()
                    acquired += 1
        except TimeoutError:
            pass
        async with self._state_lock:
            handle = self._handle
            self._handle = None
            self._state = AdapterProviderState.CLOSED
            self._error_code = "PROVIDER_UNAVAILABLE"
        try:
            if handle is not None:
                try:
                    await asyncio.to_thread(self._runtime_unloader, handle)
                except Exception:
                    self._logger.error(
                        "adapter_unload_failed provider=%s error_code=ADAPTER_UNLOAD_FAILED",
                        self.provider_name,
                    )
        finally:
            for _ in range(acquired):
                self._semaphore.release()
