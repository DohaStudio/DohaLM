from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from server.api.v1.chat import stream_chat
from server.core.config import APISettings
from server.main import create_app
from server.schemas.chat import ChatRequest
from server.services.inference import InferenceService
from src.inference import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderStatus,
)


def events(text: str) -> list[tuple[str, dict[str, object]]]:
    values = []
    blocks = [block for block in text.split("\n\n") if block]
    for block in blocks:
        lines = block.splitlines()
        values.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return values


def test_stream_has_start_deltas_and_exactly_one_done() -> None:
    app = create_app(APISettings(stream_chunk_delay_ms=0, request_timeout_seconds=1))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"messages": [{"role": "user", "content": "스트리밍 테스트"}]},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = events(response.text)
    names = [name for name, _ in parsed]
    assert names[0] == "start"
    assert "delta" in names
    assert names.count("done") == 1
    assert "error" not in names


def test_placeholder_stream_has_exactly_one_error_and_no_done() -> None:
    app = create_app(
        APISettings(
            inference_provider="dohalm-adapter",
            stream_chunk_delay_ms=0,
            request_timeout_seconds=1,
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
    parsed = events(response.text)
    names = [name for name, _ in parsed]
    assert names.count("error") == 1
    assert "done" not in names
    assert parsed[-1][1]["code"] == "ADAPTER_NOT_AVAILABLE"
    assert str(parsed[-1][1]["request_id"]).startswith("req_")


class CancellableProvider:
    provider_name = "cancellable"
    model_id = "cancellable-test"

    def __init__(self) -> None:
        self.cancelled = False

    async def health(self):
        return ProviderHealth(self.provider_name, self.model_id, ProviderStatus.READY)

    async def generate(self, request: GenerationRequest):
        del request
        return GenerationResult("unused")

    async def stream(self, request: GenerationRequest):
        del request
        try:
            await asyncio.sleep(10)
            yield GenerationChunk("unreachable")
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def close(self):
        return None


def test_stream_timeout_emits_error_and_client_cancellation_propagates() -> None:
    async def run() -> None:
        provider = CancellableProvider()
        service = InferenceService(provider, timeout_seconds=1)
        body = ChatRequest(messages=[{"role": "user", "content": "cancel"}])
        response = await stream_chat(
            body,
            service,
            APISettings(request_timeout_seconds=0.01, stream_chunk_delay_ms=0),
            "req_abcdefgh",
            logging.getLogger("test.stream"),
        )
        iterator = response.body_iterator
        assert "event: start" in await anext(iterator)
        timeout_event = await anext(iterator)
        assert "event: error" in timeout_event
        assert "INFERENCE_TIMEOUT" in timeout_event
        assert provider.cancelled is True

        provider = CancellableProvider()
        response = await stream_chat(
            body,
            InferenceService(provider, timeout_seconds=1),
            APISettings(request_timeout_seconds=10, stream_chunk_delay_ms=0),
            "req_abcdefgh",
            logging.getLogger("test.stream"),
        )
        iterator = response.body_iterator
        await anext(iterator)
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert provider.cancelled is True

    asyncio.run(run())
