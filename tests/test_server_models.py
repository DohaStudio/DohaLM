from fastapi.testclient import TestClient

from server.core.config import APISettings
from server.main import create_app


def test_models_returns_three_safe_provider_records() -> None:
    settings = APISettings(
        stream_chunk_delay_ms=0,
        model_cache_root="C:/private/model/cache",
        adapter_root="C:/private/adapter",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/models")
    assert response.status_code == 200
    value = response.json()
    assert value["active_provider"] == "mock"
    assert [(item["provider"], item["status"]) for item in value["models"]] == [
        ("mock", "ready"),
        ("base-qwen", "not_loaded"),
        ("dohalm-adapter", "not_available"),
    ]
    assert all(item["capabilities"] == ["chat", "streaming"] for item in value["models"])
    serialized = response.text
    assert "private" not in serialized
    assert "cache" not in serialized
    assert "adapter_path" not in serialized
