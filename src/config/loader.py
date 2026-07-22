"""YAML 설정 로딩, 병합, CLI 재정의."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, ConfigValidationError
from .validation import validate_model_config, validate_run_config

SECRET_MARKERS = ("password", "api_key", "access_token", "secret", "credential")


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"{config_path}: 설정 파일을 읽을 수 없습니다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{config_path}: 올바른 YAML이 아닙니다: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{config_path}: 최상위 값은 매핑이어야 합니다.")
    return value


def parse_overrides(items: list[str] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ConfigError(f"CLI override [{item}]: key=value 형식이어야 합니다.")
        key, raw_value = item.split("=", 1)
        if not key or key in overrides:
            raise ConfigError(f"CLI override [{key or item}]: 키가 없거나 중복되었습니다.")
        try:
            overrides[key] = yaml.safe_load(raw_value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"CLI override [{key}]: 값을 해석할 수 없습니다.") from exc
    return overrides


def _apply_overrides(config: dict[str, Any], overrides: dict[str, Any]) -> None:
    for dotted_key, value in overrides.items():
        parts = dotted_key.split(".")
        cursor = config
        for part in parts[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                raise ConfigError(f"CLI override [{dotted_key}]: 존재하지 않는 경로입니다.")
            cursor = cursor[part]
        field = parts[-1]
        if field not in cursor:
            raise ConfigError(f"CLI override [{dotted_key}]: 존재하지 않는 필드입니다.")
        cursor[field] = value


def load_resolved_config(
    model_path: str | Path,
    run_path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
    require_complete: bool = True,
) -> dict[str, Any]:
    model = load_yaml(model_path)
    validate_model_config(model, model_path)
    resolved = {"model": deepcopy(model)}
    if run_path is not None:
        run = load_yaml(run_path)
        validate_run_config(run, run_path, require_complete=False)
        resolved["run"] = deepcopy(run)
    _apply_overrides(resolved, overrides or {})
    validate_model_config(resolved["model"], model_path)
    if run_path is not None:
        validate_run_config(resolved["run"], run_path, require_complete=require_complete)
    return resolved


def mask_secrets(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in SECRET_MARKERS):
        return "***"
    if isinstance(value, dict):
        return {item_key: mask_secrets(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value
