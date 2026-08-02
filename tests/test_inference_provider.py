from __future__ import annotations

import asyncio
import threading
import time

import pytest

from src.inference import (
    GenerationParameters,
    GenerationRequest,
    GenerationResult,
    InferenceMessage,
    ProviderStatus,
    ProviderUnavailableError,
    create_provider_registry,
)
from src.inference.generation import (
    generation_kwargs,
    prepare_inputs,
    stream_end_marker,
)
from src.inference.model_loader import BaseQwenConfig, LoadedBaseQwen, ModelLoadError
from src.inference.providers import (
    BaseQwenProvider,
    DohaLMAdapterProvider,
    MockProvider,
)


def request(content: str = "DohaLM을 설명해 줘.") -> GenerationRequest:
    return GenerationRequest(
        messages=(InferenceMessage(role="user", content=content),),
        generation=GenerationParameters(),
    )


def test_mock_provider_is_offline_deterministic_and_streams_same_text() -> None:
    async def run() -> None:
        provider = MockProvider(chunk_delay_ms=0)
        assert (await provider.health()).status is ProviderStatus.READY
        first = await provider.generate(request())
        second = await provider.generate(request())
        chunks = [chunk.content async for chunk in provider.stream(request())]
        assert first == second
        assert "DohaLM Mock 응답" in first.content
        assert "".join(chunks) == first.content
        assert first.prompt_tokens is None
        await provider.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("provider", "code", "status"),
    [
        (
            DohaLMAdapterProvider(),
            "ADAPTER_NOT_AVAILABLE",
            ProviderStatus.NOT_AVAILABLE,
        ),
    ],
)
def test_placeholder_providers_fail_closed(
    provider, code: str, status: ProviderStatus
) -> None:
    async def run() -> None:
        assert (await provider.health()).status is status
        with pytest.raises(ProviderUnavailableError) as error:
            await provider.generate(request())
        assert error.value.code == code
        with pytest.raises(ProviderUnavailableError) as stream_error:
            await anext(provider.stream(request()))
        assert stream_error.value.code == code

    asyncio.run(run())


class FakeCuda:
    def __init__(self) -> None:
        self.emptied = False

    def max_memory_allocated(self, _device: int) -> int:
        return 1234

    def is_available(self) -> bool:
        return True

    def empty_cache(self) -> None:
        self.emptied = True

    def ipc_collect(self) -> None:
        return None


class FakeTorch:
    def __init__(self) -> None:
        self.cuda = FakeCuda()


def fake_loaded() -> LoadedBaseQwen:
    return LoadedBaseQwen(object(), object(), FakeTorch(), 100)  # type: ignore[arg-type]


def test_base_qwen_is_lazy_loads_once_and_unloads() -> None:
    async def run() -> None:
        calls = 0

        def loader(_config: BaseQwenConfig) -> LoadedBaseQwen:
            nonlocal calls
            calls += 1
            time.sleep(0.01)
            return fake_loaded()

        def generator(_loaded, _request, _cancel):
            return GenerationResult("응답", prompt_tokens=4, completion_tokens=2)

        provider = BaseQwenProvider(loader=loader, generator=generator)
        assert (await provider.health()).status is ProviderStatus.NOT_LOADED
        first, second = await asyncio.gather(
            provider.generate(request()), provider.generate(request())
        )
        assert first.content == second.content == "응답"
        assert calls == 1
        assert (await provider.health()).status is ProviderStatus.READY
        loaded = provider._loaded
        assert loaded is not None
        await provider.close()
        assert (await provider.health()).status is ProviderStatus.NOT_LOADED
        assert loaded.torch.cuda.emptied is True

    asyncio.run(run())


def test_base_qwen_load_failure_is_sanitized_and_not_retried() -> None:
    async def run() -> None:
        calls = 0

        def loader(_config: BaseQwenConfig) -> LoadedBaseQwen:
            nonlocal calls
            calls += 1
            raise ModelLoadError("C:/private/cache/detail")

        provider = BaseQwenProvider(loader=loader)
        with pytest.raises(ProviderUnavailableError) as error:
            await provider.generate(request())
        assert error.value.code == "MODEL_LOAD_FAILED"
        assert "private" not in error.value.safe_message
        with pytest.raises(ProviderUnavailableError):
            await provider.generate(request())
        assert calls == 1
        assert (await provider.health()).status is ProviderStatus.ERROR

    asyncio.run(run())


def test_generation_timeout_cancels_worker_and_releases_slot() -> None:
    async def run() -> None:
        calls = 0

        def generator(_loaded, _request, cancel_event: threading.Event):
            nonlocal calls
            calls += 1
            if calls == 1:
                assert cancel_event.wait(1)
                return GenerationResult("", finish_reason="cancelled")
            return GenerationResult("복구", prompt_tokens=1, completion_tokens=1)

        provider = BaseQwenProvider(
            BaseQwenConfig(generation_timeout_seconds=0.2),
            loader=lambda _config: fake_loaded(),
            generator=generator,
        )
        with pytest.raises(TimeoutError):
            await provider.generate(request())
        assert (await provider.generate(request())).content == "복구"
        await provider.close()

    asyncio.run(run())


class FakeStreamSession:
    def __init__(self) -> None:
        self.values = iter(("안녕 ", "하세요", stream_end_marker()))
        self.error: list[BaseException] = []
        self.finish_reason = ["stop"]
        self.ended = True
        self.cancelled = False

    def next_text(self):
        return next(self.values)

    def cancel(self) -> None:
        self.cancelled = True

    def join(self) -> None:
        return None


def test_base_qwen_stream_uses_worker_session_without_schema_change() -> None:
    async def run() -> None:
        provider = BaseQwenProvider(
            loader=lambda _config: fake_loaded(),
            streamer_factory=lambda _loaded, _request: FakeStreamSession(),
        )
        chunks = [chunk.content async for chunk in provider.stream(request())]
        assert "".join(chunks) == "안녕 하세요"
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
        self.stopped.wait(2)
        return stream_end_marker()

    def cancel(self) -> None:
        self.cancelled = True
        self.stopped.set()

    def join(self) -> None:
        self.stopped.wait(2)
        self.joined = True

    @property
    def ended(self) -> bool:
        return self.stopped.is_set()


def test_stream_cancellation_joins_worker_and_returns_semaphore() -> None:
    async def run() -> None:
        session = BlockingStreamSession()
        provider = BaseQwenProvider(
            loader=lambda _config: fake_loaded(),
            generator=lambda _loaded, _request, _cancel: GenerationResult("후속 응답"),
            streamer_factory=lambda _loaded, _request: session,
        )

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
        assert (await provider.generate(request())).content == "후속 응답"
        await provider.close()

    asyncio.run(run())


def test_generation_mapping_omits_sampling_values_for_greedy() -> None:
    greedy = request()
    greedy = GenerationRequest(
        messages=greedy.messages,
        generation=GenerationParameters(temperature=0, top_p=0.2),
    )
    greedy_values = generation_kwargs(greedy, threading.Event())
    assert greedy_values["do_sample"] is False
    assert "temperature" not in greedy_values
    assert "top_p" not in greedy_values
    sampled_values = generation_kwargs(request(), threading.Event())
    assert sampled_values["do_sample"] is True
    assert sampled_values["temperature"] == 0.7
    assert sampled_values["top_p"] == 0.9


class FakeTensor:
    shape = (1, 3)

    def to(self, device: str, *, non_blocking: bool):
        assert device == "cuda:0"
        assert non_blocking is True
        return self


class RecordingTokenizer:
    def __init__(self) -> None:
        self.messages = None
        self.options = None

    def apply_chat_template(self, messages, **options):
        self.messages = messages
        self.options = options
        return "official-template-output"

    def __call__(self, prompt, **options):
        assert prompt == "official-template-output"
        assert options == {"return_tensors": "pt", "add_special_tokens": False}
        return {"input_ids": FakeTensor(), "attention_mask": FakeTensor()}


def test_prompt_uses_official_chat_template_without_invented_system_message() -> None:
    tokenizer = RecordingTokenizer()
    loaded = LoadedBaseQwen(tokenizer, object(), FakeTorch(), 0)
    conversation = GenerationRequest(
        messages=(
            InferenceMessage(role="user", content="  질문  "),
            InferenceMessage(role="assistant", content=" 이전 답변 "),
            InferenceMessage(role="user", content=" 후속 질문 "),
        ),
        generation=GenerationParameters(),
    )
    _inputs, prompt_tokens = prepare_inputs(loaded, conversation)
    assert prompt_tokens == 3
    assert tokenizer.messages == [
        {"role": "user", "content": "질문"},
        {"role": "assistant", "content": "이전 답변"},
        {"role": "user", "content": "후속 질문"},
    ]
    assert tokenizer.options == {"tokenize": False, "add_generation_prompt": True}


def test_registry_has_one_application_lifetime_instance_and_rejects_unknown() -> None:
    registry = create_provider_registry("mock", chunk_delay_ms=0)
    assert registry.active is registry.active
    assert [item.provider_name for item in registry.providers] == [
        "mock",
        "base-qwen",
        "dohalm-adapter",
    ]
    with pytest.raises(ValueError, match="UNKNOWN_INFERENCE_PROVIDER"):
        create_provider_registry("dynamic-import")
    asyncio.run(registry.close())
