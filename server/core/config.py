"""Environment-backed API settings with fail-closed validation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOHALM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    inference_provider: str = "mock"
    request_timeout_seconds: float = Field(default=60, gt=0, le=600)
    stream_chunk_delay_ms: int = Field(default=20, ge=0, le=10_000)
    log_level: str = "INFO"
    model_cache_root: Path | None = None
    adapter_root: Path | None = None
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    @field_validator("api_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("/") or normalized == "":
            raise ValueError("API prefix must start with '/'")
        return normalized

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("CORS origins must be a list")
            return tuple(str(item).strip() for item in parsed)
        return tuple(item.strip() for item in stripped.split(",") if item.strip())

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not origin or origin == "*" for origin in value):
            raise ValueError("At least one explicit CORS origin is required")
        return value
