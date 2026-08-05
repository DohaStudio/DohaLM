from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.inference.adapter_loader import AdapterLoaderError
from src.inference.adapter_manifest import AdapterManifestError
from src.inference.adapter_validation import AdapterValidationError
from src.inference.base import (
    GenerationParameters,
    GenerationRequest,
    GenerationResult,
    InferenceMessage,
    ProviderStatus,
    ProviderUnavailableError,
)
from src.inference.generation import stream_end_marker
from src.inference.providers.dohalm_adapter import (
    AdapterProviderState,
    DohaLMAdapterConfig,
    DohaLMAdapterProvider,
)


def request() -> GenerationRequest:
    return GenerationRequest(
        (InferenceMessage("user", "hello"),), GenerationParameters()
    )


def manifest():
    return SimpleNamespace(
        adapter_name="general-instruct",
        adapter_version="1.0.0",
        base_model="Qwen/Qwen2.5-1.5B-Instruct",
        base_revision="revision",
    )


def handle():
    return SimpleNamespace(model=object(), tokenizer=object(), torch=object())


def configured(**dependencies) -> DohaLMAdapterProvider:
    return DohaLMAdapterProvider(
        DohaLMAdapterConfig(
            manifest_path=Path("adapter-manifest.json"),
            adapter_root=Path("adapter"),
            base_model_path=Path("base"),
            load_timeout_seconds=1,
            generation_timeout_seconds=1,
        ),
        manifest_loader=dependencies.pop("manifest_loader", lambda _path: manifest()),
        artifact_validator=dependencies.pop(
            "artifact_validator", lambda _value: object()
        ),
        runtime_loader=dependencies.pop("runtime_loader", lambda **_values: handle()),
        **dependencies,
    )


def test_startup_is_static_preflight_and_exposes_safe_metadata() -> None:
    async def run() -> None:
        load_calls = 0

        def loader(**_values):
            nonlocal load_calls
            load_calls += 1
            return handle()

        provider = configured(runtime_loader=loader)
        await provider.startup()
        health = await provider.health()
        assert provider.state is AdapterProviderState.VALIDATED_NOT_LOADED
        assert health.status is ProviderStatus.NOT_LOADED
        assert health.runtime_metadata is not None
        assert health.runtime_metadata.adapter_version == "1.0.0"
        assert load_calls == 0
        await provider.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("error", "state", "code"),
    [
        (
            AdapterManifestError("ADAPTER_MANIFEST_NOT_FOUND"),
            AdapterProviderState.UNAVAILABLE,
            "ADAPTER_NOT_AVAILABLE",
        ),
        (
            AdapterManifestError("ADAPTER_MANIFEST_INVALID"),
            AdapterProviderState.INCOMPATIBLE,
            "ADAPTER_INCOMPATIBLE",
        ),
        (
            AdapterValidationError("ADAPTER_CONFIG_INCOMPATIBLE"),
            AdapterProviderState.INCOMPATIBLE,
            "ADAPTER_INCOMPATIBLE",
        ),
    ],
)
def test_preflight_failures_are_fail_closed(error, state, code) -> None:
    async def run() -> None:
        def fail(_value):
            raise error

        kwargs = (
            {"manifest_loader": fail}
            if isinstance(error, AdapterManifestError)
            else {"artifact_validator": fail}
        )
        provider = configured(**kwargs)
        await provider.startup()
        health = await provider.health()
        assert provider.state is state
        assert health.error_code == code
        with pytest.raises(ProviderUnavailableError, match=code):
            await provider.generate(request())

    asyncio.run(run())


def test_missing_explicit_paths_keeps_provider_unavailable() -> None:
    async def run() -> None:
        provider = DohaLMAdapterProvider()
        await provider.startup()
        health = await provider.health()
        assert health.status is ProviderStatus.NOT_AVAILABLE
        assert health.error_code == "ADAPTER_NOT_AVAILABLE"

    asyncio.run(run())


def test_concurrent_first_requests_single_flight_and_publish_atomically() -> None:
    async def run() -> None:
        calls = 0
        release = threading.Event()

        def loader(**_values):
            nonlocal calls
            calls += 1
            release.wait(1)
            return handle()

        provider = configured(
            runtime_loader=loader,
            generator=lambda _loaded, _request, _cancel: GenerationResult("ok"),
        )
        await provider.startup()
        first = asyncio.create_task(provider.generate(request()))
        second = asyncio.create_task(provider.generate(request()))
        await asyncio.sleep(0.05)
        assert provider.state is AdapterProviderState.LOADING
        release.set()
        assert [value.content for value in await asyncio.gather(first, second)] == [
            "ok",
            "ok",
        ]
        assert calls == 1
        assert (await provider.health()).status is ProviderStatus.READY
        await provider.close()

    asyncio.run(run())


def test_load_failure_is_retained_without_retry() -> None:
    async def run() -> None:
        calls = 0

        def loader(**_values):
            nonlocal calls
            calls += 1
            raise AdapterLoaderError("ADAPTER_LOAD_FAILED")

        provider = configured(runtime_loader=loader)
        await provider.startup()
        for _ in range(2):
            with pytest.raises(ProviderUnavailableError, match="ADAPTER_LOAD_FAILED"):
                await provider.generate(request())
        assert calls == 1
        assert provider.state is AdapterProviderState.LOAD_FAILED

    asyncio.run(run())


def test_load_timeout_is_retained_and_late_handle_is_not_published() -> None:
    async def run() -> None:
        release = threading.Event()
        unloaded = []
        runtime = handle()

        def loader(**_values):
            release.wait(1)
            return runtime

        provider = DohaLMAdapterProvider(
            DohaLMAdapterConfig(
                manifest_path=Path("adapter-manifest.json"),
                adapter_root=Path("adapter"),
                base_model_path=Path("base"),
                load_timeout_seconds=0.05,
            ),
            manifest_loader=lambda _path: manifest(),
            artifact_validator=lambda _value: object(),
            runtime_loader=loader,
            runtime_unloader=lambda value: unloaded.append(value) or True,
        )
        await provider.startup()
        with pytest.raises(ProviderUnavailableError, match="ADAPTER_LOAD_FAILED"):
            await provider.generate(request())
        assert provider.state is AdapterProviderState.LOAD_FAILED
        release.set()
        assert provider._load_task is not None
        await provider._load_task
        assert unloaded == [runtime]
        assert provider.state is AdapterProviderState.LOAD_FAILED
        await provider.close()

    asyncio.run(run())


class FakeStreamSession:
    def __init__(self) -> None:
        self.values = iter(("one ", "two", stream_end_marker()))
        self.error: list[BaseException] = []
        self.finish_reason = ["stop"]
        self.cancelled = False

    def next_text(self):
        return next(self.values)

    def cancel(self) -> None:
        self.cancelled = True

    def join(self) -> None:
        return None

    @property
    def ended(self) -> bool:
        return True


def test_chat_and_stream_share_one_concurrent_first_load() -> None:
    async def run() -> None:
        calls = 0
        release = threading.Event()

        def loader(**_values):
            nonlocal calls
            calls += 1
            release.wait(1)
            return handle()

        provider = configured(
            runtime_loader=loader,
            generator=lambda _loaded, _request, _cancel: GenerationResult("chat"),
            streamer_factory=lambda _loaded, _request: FakeStreamSession(),
        )
        await provider.startup()
        chat_task = asyncio.create_task(provider.generate(request()))

        async def consume_stream():
            return [chunk async for chunk in provider.stream(request())]

        stream_task = asyncio.create_task(consume_stream())
        await asyncio.sleep(0.05)
        assert (await provider.health()).status is ProviderStatus.LOADING
        release.set()
        chat_result, stream_result = await asyncio.gather(chat_task, stream_task)
        assert chat_result.content == "chat"
        assert stream_result[-1].finish_reason == "stop"
        assert calls == 1
        await provider.close()

    asyncio.run(run())


def test_chat_and_stream_share_loaded_runtime_and_close_unloads_once() -> None:
    async def run() -> None:
        unloaded = []
        runtime = handle()
        provider = configured(
            runtime_loader=lambda **_values: runtime,
            runtime_unloader=lambda value: unloaded.append(value) or True,
            generator=lambda _loaded, _request, _cancel: GenerationResult("chat"),
            streamer_factory=lambda _loaded, _request: FakeStreamSession(),
        )
        await provider.startup()
        assert (await provider.generate(request())).content == "chat"
        chunks = [chunk async for chunk in provider.stream(request())]
        assert "".join(chunk.content for chunk in chunks) == "one two"
        assert chunks[-1].finish_reason == "stop"
        await provider.close()
        await provider.close()
        assert unloaded == [runtime]
        assert provider.state is AdapterProviderState.CLOSED

    asyncio.run(run())


def test_generation_timeout_cancels_worker_and_releases_slot() -> None:
    async def run() -> None:
        calls = 0

        def generator(_loaded, _request, cancel_event):
            nonlocal calls
            calls += 1
            if calls == 1:
                cancel_event.wait(1)
                return GenerationResult("", finish_reason="cancelled")
            return GenerationResult("recovered")

        provider = DohaLMAdapterProvider(
            DohaLMAdapterConfig(
                manifest_path=Path("adapter-manifest.json"),
                adapter_root=Path("adapter"),
                base_model_path=Path("base"),
                generation_timeout_seconds=0.05,
            ),
            manifest_loader=lambda _path: manifest(),
            artifact_validator=lambda _value: object(),
            runtime_loader=lambda **_values: handle(),
            generator=generator,
        )
        await provider.startup()
        with pytest.raises(TimeoutError):
            await provider.generate(request())
        assert (await provider.generate(request())).content == "recovered"
        await provider.close()

    asyncio.run(run())


class BlockingStreamSession:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.error: list[BaseException] = []
        self.finish_reason: list[str] = []
        self.cancelled = False
        self.joined = False

    def next_text(self):
        self.started.set()
        self.stopped.wait(1)
        return stream_end_marker()

    def cancel(self) -> None:
        self.cancelled = True
        self.stopped.set()

    def join(self) -> None:
        self.stopped.wait(1)
        self.joined = True

    @property
    def ended(self) -> bool:
        return self.stopped.is_set()


def test_stream_cancellation_joins_worker_and_releases_slot() -> None:
    async def run() -> None:
        session = BlockingStreamSession()
        provider = configured(
            generator=lambda _loaded, _request, _cancel: GenerationResult("next"),
            streamer_factory=lambda _loaded, _request: session,
        )
        await provider.startup()

        async def consume() -> None:
            async for _chunk in provider.stream(request()):
                pass

        task = asyncio.create_task(consume())
        assert await asyncio.to_thread(session.started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.cancelled is True
        assert session.joined is True
        assert (await provider.generate(request())).content == "next"
        await provider.close()

    asyncio.run(run())


def test_generation_semaphore_limits_concurrent_requests() -> None:
    async def run() -> None:
        entered = 0
        maximum = 0
        release = threading.Event()

        def generator(_loaded, _request, _cancel):
            nonlocal entered, maximum
            entered += 1
            maximum = max(maximum, entered)
            release.wait(1)
            entered -= 1
            return GenerationResult("ok")

        provider = configured(generator=generator)
        await provider.startup()
        first = asyncio.create_task(provider.generate(request()))
        second = asyncio.create_task(provider.generate(request()))
        await asyncio.sleep(0.05)
        assert maximum == 1
        release.set()
        await asyncio.gather(first, second)
        assert maximum == 1
        await provider.close()

    asyncio.run(run())


def test_generation_cancellation_reaches_worker_and_releases_slot() -> None:
    async def run() -> None:
        started = threading.Event()
        cancelled = threading.Event()

        def generator(_loaded, _request, cancel_event):
            started.set()
            cancel_event.wait(1)
            cancelled.set()
            return GenerationResult("", finish_reason="cancelled")

        provider = configured(generator=generator)
        await provider.startup()
        task = asyncio.create_task(provider.generate(request()))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        await provider.close()

    asyncio.run(run())


def test_shutdown_during_load_never_publishes_ready() -> None:
    async def run() -> None:
        started = threading.Event()
        release = threading.Event()
        runtime = handle()
        unloaded = []

        def loader(**_values):
            started.set()
            release.wait(1)
            return runtime

        provider = configured(
            runtime_loader=loader,
            runtime_unloader=lambda value: unloaded.append(value) or True,
        )
        await provider.startup()
        generation = asyncio.create_task(provider.generate(request()))
        assert await asyncio.to_thread(started.wait, 1)
        closing = asyncio.create_task(provider.close())
        await asyncio.sleep(0.02)
        assert provider.state is AdapterProviderState.SHUTTING_DOWN
        release.set()
        await closing
        with pytest.raises(ProviderUnavailableError, match="PROVIDER_UNAVAILABLE"):
            await generation
        assert unloaded == [runtime]
        assert provider.state is AdapterProviderState.CLOSED

    asyncio.run(run())


def test_unload_failure_is_isolated_and_provider_still_closes() -> None:
    async def run() -> None:
        def fail_unload(_handle):
            raise RuntimeError("private detail")

        provider = configured(
            runtime_unloader=fail_unload,
            generator=lambda _loaded, _request, _cancel: GenerationResult("ok"),
        )
        await provider.startup()
        await provider.generate(request())
        await provider.close()
        assert provider.state is AdapterProviderState.CLOSED
        assert (await provider.health()).error_code == "PROVIDER_UNAVAILABLE"

    asyncio.run(run())
