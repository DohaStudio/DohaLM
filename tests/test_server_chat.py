from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from server.core.config import APISettings
from server.main import create_app
from src.inference import (
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderRegistry,
    ProviderStatus,
)


def client(**overrides) -> TestClient:
    return TestClient(
        create_app(
            APISettings(
                stream_chunk_delay_ms=0,
                request_timeout_seconds=1,
                **overrides,
            )
        )
    )


def payload(content: str = "DohaLM은 무엇인가요?") -> dict[str, object]:
    return {"messages": [{"role": "user", "content": content}]}


def test_chat_is_deterministic_structured_and_accepts_multi_turn() -> None:
    with client() as api:
        first = api.post("/api/v1/chat", json=payload())
        second = api.post("/api/v1/chat", json=payload())
        multi = api.post(
            "/api/v1/chat",
            json={
                "messages": [
                    {"role": "system", "content": "간결하게 답하세요."},
                    {"role": "user", "content": "첫 질문"},
                    {"role": "assistant", "content": "첫 답변"},
                    {"role": "user", "content": "두 번째 질문"},
                ]
            },
        )
    assert first.status_code == second.status_code == multi.status_code == 200
    assert first.json()["message"] == second.json()["message"]
    assert first.json()["id"].startswith("chatcmpl_")
    assert first.json()["model"] == "dohalm-mock-v1"
    assert first.json()["provider"] == "mock"
    assert first.json()["finish_reason"] == "stop"
    assert first.json()["usage"] == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }
    assert multi.json()["message"]["content"].endswith('"두 번째 질문"입니다.')


@pytest.mark.parametrize(
    "body",
    [
        {"messages": []},
        {"messages": [{"role": "assistant", "content": "끝"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": [{"role": "tool", "content": "금지"}]},
        {"messages": [{"role": "user", "content": "x" * 8001}]},
        {"messages": [{"role": "user", "content": "x"}], "generation": {"max_new_tokens": 0}},
        {"messages": [{"role": "user", "content": "x"}], "generation": {"top_p": 0}},
        {"messages": [{"role": "user", "content": "x"}], "unknown": True},
    ],
)
def test_invalid_chat_requests_use_safe_structured_validation_error(body) -> None:
    with client() as api:
        response = api.post("/api/v1/chat", json=body)
    assert response.status_code == 422
    value = response.json()["error"]
    assert value["code"] == "VALIDATION_ERROR"
    assert value["request_id"].startswith("req_")
    assert "traceback" not in response.text.lower()
    assert "input" not in response.text.lower()


def test_message_count_total_length_and_body_size_limits() -> None:
    with client() as api:
        too_many = api.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "x"}] * 51},
        )
        total = api.post(
            "/api/v1/chat",
            json={"messages": [{"role": "system", "content": "x" * 8000}] * 4 + [{"role": "user", "content": "x"}]},
        )
        oversized = api.post(
            "/api/v1/chat",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "2000000"},
        )
    assert too_many.status_code == total.status_code == 422
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "VALIDATION_ERROR"


def test_request_id_accepts_only_safe_shape() -> None:
    with client() as api:
        accepted = api.post(
            "/api/v1/chat",
            json=payload(),
            headers={"X-Request-ID": "req_abcdefgh"},
        )
        rejected = api.post(
            "/api/v1/chat",
            json=payload(),
            headers={"X-Request-ID": "../../secret"},
        )
    assert accepted.headers["X-Request-ID"] == "req_abcdefgh"
    assert rejected.headers["X-Request-ID"].startswith("req_")
    assert rejected.headers["X-Request-ID"] != "../../secret"


def test_placeholder_chat_error_does_not_expose_local_paths() -> None:
    with client(inference_provider="base-qwen") as api:
        response = api.post("/api/v1/chat", json=payload())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_LOADED"
    assert "C:\\" not in response.text
    assert "/home/" not in response.text


class SlowProvider:
    provider_name = "slow"
    model_id = "slow-test"

    async def health(self):
        return ProviderHealth(self.provider_name, self.model_id, ProviderStatus.READY)

    async def generate(self, request: GenerationRequest):
        del request
        await asyncio.sleep(10)
        return GenerationResult("unreachable")

    async def stream(self, request: GenerationRequest):
        del request
        await asyncio.sleep(10)
        if False:
            yield

    async def close(self):
        return None


def test_regular_chat_timeout_is_504_and_cancels_provider_task() -> None:
    def factory(_settings):
        return ProviderRegistry((SlowProvider(),), active_provider="slow")

    app = create_app(
        APISettings(request_timeout_seconds=0.01, stream_chunk_delay_ms=0),
        registry_factory=factory,
    )
    with TestClient(app) as api:
        response = api.post("/api/v1/chat", json=payload())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "INFERENCE_TIMEOUT"


def test_prompt_and_response_are_not_logged(capsys) -> None:
    secret_prompt = "PROMPT_SHOULD_NOT_APPEAR_4f8c"
    with client() as api:
        response = api.post("/api/v1/chat", json=payload(secret_prompt))
    assert response.status_code == 200
    captured = capsys.readouterr()
    assert secret_prompt not in captured.out
    assert secret_prompt not in captured.err


class FailingProvider(SlowProvider):
    provider_name = "failing"
    model_id = "failing-test"

    async def generate(self, request: GenerationRequest):
        del request
        raise RuntimeError("C:/private/model/cache traceback secret")


def test_unexpected_provider_failure_is_sanitized() -> None:
    def factory(_settings):
        return ProviderRegistry((FailingProvider(),), active_provider="failing")

    app = create_app(
        APISettings(request_timeout_seconds=1, stream_chunk_delay_ms=0),
        registry_factory=factory,
    )
    with TestClient(app) as api:
        response = api.post("/api/v1/chat", json=payload())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INFERENCE_FAILED"
    assert "private" not in response.text
    assert "traceback" not in response.text.lower()
