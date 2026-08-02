from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.core.config import APISettings
from server.main import create_app


def settings(**overrides) -> APISettings:
    return APISettings(
        stream_chunk_delay_ms=0,
        request_timeout_seconds=1,
        **overrides,
    )


def test_application_metadata_lifespan_health_and_readiness() -> None:
    app = create_app(settings())
    assert app.title == "DohaLM API"
    assert app.version == "0.1.0"
    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "service": "dohalm-api",
            "version": "0.1.0",
        }
        assert ready.status_code == 200
        assert ready.json()["provider"] == {
            "name": "mock",
            "model_id": "dohalm-mock-v1",
            "status": "ready",
        }
        assert health.headers["X-Request-ID"].startswith("req_")


def test_readiness_is_503_for_unloaded_provider() -> None:
    with TestClient(create_app(settings(inference_provider="base-qwen"))) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROVIDER_NOT_READY"


def test_unknown_provider_fails_during_startup() -> None:
    app = create_app(settings(inference_provider="unknown"))
    try:
        with TestClient(app):
            pass
    except ValueError as exc:
        assert str(exc) == "UNKNOWN_INFERENCE_PROVIDER"
    else:  # pragma: no cover
        raise AssertionError("unknown provider did not fail closed")


def test_openapi_documents_all_mvp_endpoints() -> None:
    with TestClient(create_app(settings())) as client:
        document = client.get("/openapi.json").json()
        assert client.get("/docs").status_code == 200
    assert {
        "/health",
        "/ready",
        "/api/v1/models",
        "/api/v1/chat",
        "/api/v1/chat/stream",
    } <= set(document["paths"])
    assert (
        "text/event-stream"
        in document["paths"]["/api/v1/chat/stream"]["post"]["responses"]["200"][
            "content"
        ]
    )


def test_cors_uses_explicit_development_origin_without_credentials() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.options(
            "/api/v1/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type,X-Request-ID",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_rejects_wildcard_origin() -> None:
    try:
        settings(cors_origins=("*",))
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("wildcard CORS origin did not fail closed")


def test_settings_load_environment_without_local_path_disclosure(monkeypatch) -> None:
    monkeypatch.setenv("DOHALM_API_PORT", "8123")
    monkeypatch.setenv("DOHALM_CORS_ORIGINS", '["http://localhost:3100"]')
    monkeypatch.setenv("DOHALM_MODEL_CACHE_ROOT", "C:/private/cache")
    value = APISettings(_env_file=None)
    assert value.api_port == 8123
    assert value.cors_origins == ("http://localhost:3100",)
    with TestClient(create_app(value)) as client:
        serialized = client.get("/api/v1/models").text
    assert "private" not in serialized


def test_base_qwen_settings_defaults_and_environment(monkeypatch) -> None:
    defaults = APISettings(_env_file=None)
    assert defaults.base_model_quantization == "nf4"
    assert defaults.max_concurrent_generations == 1
    assert defaults.model_load_timeout_seconds == 300
    assert defaults.generation_timeout_seconds == 120
    assert defaults.model_unload_on_shutdown is True
    monkeypatch.setenv("DOHALM_BASE_MODEL_QUANTIZATION", "BF16")
    monkeypatch.setenv("DOHALM_GENERATION_TIMEOUT_SECONDS", "30")
    configured = APISettings(_env_file=None)
    assert configured.base_model_quantization == "bf16"
    assert configured.generation_timeout_seconds == 30
