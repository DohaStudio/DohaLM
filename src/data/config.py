"""Phase 1 data pipeline configuration contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.config.errors import ConfigError, ConfigValidationError


@dataclass(frozen=True)
class DataConfig:
    dataset_id: str
    dataset_version: str
    input_paths: tuple[str, ...]
    output_dir: str
    license_status: str = "approved"
    approval_status: str = "approved"
    pii_status: str = "clear"
    max_text_chars: int = 1_000_000
    metadata_max_depth: int = 5
    split_seed: int = 42
    train_ratio: float = 0.8
    validation_ratio: float = 0.1
    test_ratio: float = 0.1
    split_tolerance: float = 1e-9
    checksum_algorithm: str = "sha256"
    normalization: str = "NFC"
    encoding: str = "utf-8"
    allowed_formats: tuple[str, ...] = (".txt", ".jsonl")
    reject_unknown_fields: bool = True
    write_empty_split_files: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "input_paths": sorted(path.replace("\\", "/") for path in self.input_paths),
            "allowed_formats": list(self.allowed_formats),
            "output_dir": self.output_dir,
            "encoding": self.encoding,
            "unicode_normalization": self.normalization,
            "max_text_chars": self.max_text_chars,
            "metadata_max_depth": self.metadata_max_depth,
            "reject_unknown_fields": self.reject_unknown_fields,
            "write_empty_split_files": self.write_empty_split_files,
            "checksum_algorithm": self.checksum_algorithm,
            "split": {
                "seed": self.split_seed,
                "train_ratio": self.train_ratio,
                "validation_ratio": self.validation_ratio,
                "test_ratio": self.test_ratio,
                "ratio_tolerance": self.split_tolerance,
            },
            "source": {
                "license_status": self.license_status,
                "approval_status": self.approval_status,
                "pii_status": self.pii_status,
            },
        }


_FIELDS = frozenset(DataConfig.__dataclass_fields__)


def _require_type(data: Mapping[str, Any], field: str, expected: type | tuple[type, ...]) -> Any:
    if field not in data:
        raise ConfigValidationError(f"data [{field}]: 필수 필드가 없습니다.")
    value = data[field]
    if isinstance(value, bool) and expected in (int, float):
        raise ConfigValidationError(f"data [{field}]: 올바른 형식이 아닙니다.")
    if not isinstance(value, expected):
        raise ConfigValidationError(f"data [{field}]: 올바른 형식이 아닙니다.")
    return value


def validate_data_config(data: Mapping[str, Any], *, require_inputs: bool = True) -> DataConfig:
    if not isinstance(data, Mapping):
        raise ConfigValidationError("data: 매핑이어야 합니다.")
    data = dict(data)
    aliases = {
        "encoding": "encoding",
        "unicode_normalization": "normalization",
        "checksum_algorithm": "checksum_algorithm",
    }
    for source_name, target_name in aliases.items():
        if source_name in data and source_name != target_name:
            data[target_name] = data.pop(source_name)
    split = data.pop("split", None)
    if split is not None:
        if not isinstance(split, Mapping):
            raise ConfigValidationError("data [split]: 매핑이어야 합니다.")
        expected_split = {"seed", "train_ratio", "validation_ratio", "test_ratio", "ratio_tolerance"}
        if set(split) - expected_split:
            raise ConfigValidationError("data [split]: 알 수 없는 필드입니다.")
        data.update(
            split_seed=split.get("seed"),
            train_ratio=split.get("train_ratio"),
            validation_ratio=split.get("validation_ratio"),
            test_ratio=split.get("test_ratio"),
            split_tolerance=split.get("ratio_tolerance"),
        )
    source = data.pop("source", None)
    if source is not None:
        if not isinstance(source, Mapping):
            raise ConfigValidationError("data [source]: 매핑이어야 합니다.")
        expected_source = {"license_status", "approval_status", "pii_status"}
        if set(source) - expected_source:
            raise ConfigValidationError("data [source]: 알 수 없는 필드입니다.")
        missing_source = expected_source - set(source)
        if missing_source:
            raise ConfigValidationError(f"data [source.{sorted(missing_source)[0]}]: 필수 필드가 없습니다.")
        data.update(source)
    elif not {"license_status", "approval_status", "pii_status"}.issubset(data):
        raise ConfigValidationError("data [source]: license·approval·PII 상태를 명시해야 합니다.")
    unknown = sorted(set(data) - _FIELDS)
    if unknown:
        raise ConfigValidationError(f"data [{unknown[0]}]: 알 수 없는 필드입니다.")

    dataset_id = _require_type(data, "dataset_id", str).strip()
    input_paths = _require_type(data, "input_paths", list)
    dataset_version = _require_type(data, "dataset_version", str).strip()
    output_dir = _require_type(data, "output_dir", str).strip()
    if not dataset_id or not dataset_version or not output_dir or (require_inputs and not input_paths) or not all(
        isinstance(item, str) and item.strip() for item in input_paths
    ):
        raise ConfigValidationError("data: dataset_id, input_paths, output_directory는 비어 있을 수 없습니다.")

    merged = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "input_paths": tuple(item.strip() for item in input_paths),
        "output_dir": output_dir,
    }
    for name, field in DataConfig.__dataclass_fields__.items():
        if name in merged:
            continue
        merged[name] = data.get(name, field.default)
    merged["allowed_formats"] = tuple(merged["allowed_formats"])

    config = DataConfig(**merged)
    integer_fields = ("max_text_chars", "metadata_max_depth", "split_seed")
    if any(isinstance(getattr(config, name), bool) or not isinstance(getattr(config, name), int) for name in integer_fields):
        raise ConfigValidationError("data: 정수 설정값 형식이 올바르지 않습니다.")
    numeric_fields = ("train_ratio", "validation_ratio", "test_ratio", "split_tolerance")
    if any(isinstance(getattr(config, name), bool) or not isinstance(getattr(config, name), (int, float)) for name in numeric_fields):
        raise ConfigValidationError("data: split 수치 형식이 올바르지 않습니다.")
    if config.license_status not in {"approved", "pending", "rejected", "unknown"}:
        raise ConfigValidationError("data [license_status]: 지원하지 않는 상태입니다.")
    if config.approval_status not in {"approved", "pending", "rejected"}:
        raise ConfigValidationError("data [approval_status]: 지원하지 않는 상태입니다.")
    if config.pii_status not in {"clear", "suspected", "confirmed", "unknown"}:
        raise ConfigValidationError("data [pii_status]: 지원하지 않는 상태입니다.")
    if config.max_text_chars != 1_000_000 or config.metadata_max_depth != 5:
        raise ConfigValidationError("data: Phase 1 고정 제한값과 일치하지 않습니다.")
    if config.split_seed != 42 or config.split_tolerance != 1e-9:
        raise ConfigValidationError("data: Phase 1 split 고정값과 일치하지 않습니다.")
    ratios = (config.train_ratio, config.validation_ratio, config.test_ratio)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 for value in ratios):
        raise ConfigValidationError("data: split 비율은 0 이상의 수여야 합니다.")
    if config.train_ratio <= 0 or abs(sum(ratios) - 1.0) > config.split_tolerance:
        raise ConfigValidationError("data: train 비율은 양수이고 split 합은 1이어야 합니다.")
    fixed = {
        "checksum_algorithm": "sha256",
        "normalization": "NFC",
        "encoding": "utf-8",
        "allowed_formats": (".txt", ".jsonl"),
        "reject_unknown_fields": True,
        "write_empty_split_files": True,
    }
    for name, expected in fixed.items():
        actual = tuple(config.allowed_formats) if name == "allowed_formats" else getattr(config, name)
        if actual != expected:
            raise ConfigValidationError(f"data [{name}]: Phase 1 고정값 {expected!r}와 일치하지 않습니다.")
    return config


def load_data_config(path: str | Path) -> DataConfig:
    config_path = Path(path)
    try:
        value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{config_path}: 설정 파일을 읽을 수 없습니다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{config_path}: 올바른 YAML이 아닙니다: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ConfigValidationError(f"{config_path}: 최상위 값은 매핑이어야 합니다.")
    data = value.get("data", value)
    return validate_data_config(data, require_inputs=True)
