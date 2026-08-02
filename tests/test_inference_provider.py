from __future__ import annotations

import asyncio

import pytest

from src.inference import (
    GenerationParameters,
    GenerationRequest,
    InferenceMessage,
    ProviderStatus,
    ProviderUnavailableError,
    create_provider_registry,
)
from src.inference.providers import BaseQwenProvider, DohaLMAdapterProvider, MockProvider


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
        (BaseQwenProvider(), "MODEL_NOT_LOADED", ProviderStatus.NOT_LOADED),
        (DohaLMAdapterProvider(), "ADAPTER_NOT_AVAILABLE", ProviderStatus.NOT_AVAILABLE),
    ],
)
def test_placeholder_providers_fail_closed(provider, code: str, status: ProviderStatus) -> None:
    async def run() -> None:
        assert (await provider.health()).status is status
        with pytest.raises(ProviderUnavailableError) as error:
            await provider.generate(request())
        assert error.value.code == code
        with pytest.raises(ProviderUnavailableError) as stream_error:
            await anext(provider.stream(request()))
        assert stream_error.value.code == code

    asyncio.run(run())


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
