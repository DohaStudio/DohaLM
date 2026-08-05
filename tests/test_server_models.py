from pathlib import Path

from fastapi.testclient import TestClient

from server.core.config import APISettings
from server.main import create_app
from src.inference import ProviderRegistry
from src.inference.providers import DohaLMAdapterConfig, DohaLMAdapterProvider


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
    assert all(
        item["capabilities"] == ["chat", "streaming"] for item in value["models"]
    )
    serialized = response.text
    assert "private" not in serialized
    assert "cache" not in serialized
    assert "adapter_path" not in serialized


def test_models_exposes_only_safe_adapter_runtime_metadata() -> None:
    provider = DohaLMAdapterProvider(
        DohaLMAdapterConfig(
            manifest_path=Path("C:/private/adapter/adapter-manifest.json"),
            adapter_root=Path("C:/private/adapter"),
            base_model_path=Path("C:/private/base"),
        ),
        manifest_loader=lambda _path: type(
            "Manifest",
            (),
            {
                "adapter_name": "general-instruct",
                "adapter_version": "1.0.0",
                "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
                "base_revision": "revision",
            },
        )(),
        artifact_validator=lambda _manifest: object(),
    )
    app = create_app(
        APISettings(inference_provider="dohalm-adapter"),
        registry_factory=lambda _settings: ProviderRegistry(
            (provider,), "dohalm-adapter"
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/models")
    assert response.status_code == 200
    value = response.json()["models"][0]
    assert value["runtime_metadata"] == {
        "adapter_name": "general-instruct",
        "adapter_version": "1.0.0",
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "base_revision": "revision",
        "runtime_status": "validated_not_loaded",
    }
    assert "private" not in response.text
