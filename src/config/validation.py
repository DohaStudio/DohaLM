"""설정 스키마와 승인된 불변 조건 검증."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .errors import ConfigValidationError, DisabledConfigError
from .schema import MODEL_SCHEMA, RUN_SCHEMA, TINY_INVARIANTS


def _location(source: str | Path, field: str | None = None) -> str:
    return f"{source}" + (f" [{field}]" if field else "")


def _validate_schema(
    data: Mapping[str, Any],
    schema: Mapping[str, tuple],
    source: str | Path,
    *,
    optional_fields: frozenset[str] = frozenset(),
) -> None:
    unknown = sorted(set(data) - set(schema))
    if unknown:
        raise ConfigValidationError(f"{_location(source, unknown[0])}: 알 수 없는 필드입니다.")
    missing = sorted(set(schema) - set(data) - optional_fields)
    if missing:
        raise ConfigValidationError(f"{_location(source, missing[0])}: 필수 필드가 없습니다.")

    for field, (expected_type, nullable) in schema.items():
        if field not in data:
            continue
        value = data[field]
        if value is None and nullable:
            continue
        bool_as_number = isinstance(value, bool) and (
            expected_type in (int, float) or (isinstance(expected_type, tuple) and int in expected_type)
        )
        if value is None or not isinstance(value, expected_type) or bool_as_number:
            types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
            expected = ", ".join(item.__name__ for item in types)
            raise ConfigValidationError(f"{_location(source, field)}: {expected} 형식이어야 합니다.")


def validate_model_config(data: Mapping[str, Any], source: str | Path) -> None:
    if data.get("config_status") == "disabled":
        raise DisabledConfigError(f"{source}: 승인되지 않아 비활성화된 모델 설정입니다.")
    _validate_schema(data, MODEL_SCHEMA, source)
    for field, expected in TINY_INVARIANTS.items():
        if data[field] != expected:
            raise ConfigValidationError(
                f"{_location(source, field)}: 승인값 {expected!r}와 일치해야 합니다."
            )
    if data["hidden_size"] != data["num_attention_heads"] * data["head_dim"]:
        raise ConfigValidationError(
            f"{_location(source, 'head_dim')}: hidden_size와 head 구성이 일치하지 않습니다."
        )
    dropout = data["dropout"]
    if dropout is not None and not 0 <= dropout < 1:
        raise ConfigValidationError(f"{_location(source, 'dropout')}: 0 이상 1 미만이어야 합니다.")


def validate_run_config(
    data: Mapping[str, Any], source: str | Path, *, require_complete: bool = True
) -> None:
    _validate_schema(data, RUN_SCHEMA, source, optional_fields=frozenset({"data"}))
    if "data" in data:
        from src.data.config import validate_data_config

        validate_data_config(data["data"], require_inputs=False)
    if require_complete:
        unresolved = [
            field
            for field, value in data.items()
            if value is None and field not in {"resume_checkpoint", "max_steps", "token_budget"}
        ]
        if unresolved:
            field = sorted(unresolved)[0]
            raise ConfigValidationError(f"{_location(source, field)}: 실행 전에 값을 확정해야 합니다.")
        if data["max_steps"] is None and data["token_budget"] is None:
            raise ConfigValidationError(
                f"{_location(source, 'max_steps')}: max_steps 또는 token_budget 중 하나가 필요합니다."
            )
        if data["max_steps"] is not None and data["token_budget"] is not None:
            raise ConfigValidationError(
                f"{_location(source, 'token_budget')}: max_steps와 동시에 지정할 수 없습니다."
            )

    for field in (
        "micro_batch",
        "gradient_accumulation",
        "learning_rate",
        "max_steps",
        "token_budget",
        "checkpoint_interval",
        "evaluation_interval",
    ):
        value = data[field]
        if value is not None and value <= 0:
            raise ConfigValidationError(f"{_location(source, field)}: 0보다 커야 합니다.")
    for field in ("warmup", "weight_decay"):
        value = data[field]
        if value is not None and value < 0:
            raise ConfigValidationError(f"{_location(source, field)}: 0 이상이어야 합니다.")
    for field in ("output_directory", "resume_checkpoint"):
        value = data[field]
        if value is None:
            continue
        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value)
        if windows_path.is_absolute() or posix_path.is_absolute() or ".." in windows_path.parts:
            raise ConfigValidationError(
                f"{_location(source, field)}: 저장소 내부 상대 경로만 허용됩니다."
            )
