"""Fail-closed configuration for reproducible, evaluation-only execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from src.data.checksums import checksum_value, file_checksum
from src.runtime.paths import repository_root


class EvaluationError(RuntimeError):
    """Evaluation contract violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationError("EVALUATION_CONFIG_INVALID", f"{field} must be a mapping")
    return value


def _logical_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError("EVALUATION_CONFIG_INVALID", f"{field} must be a non-empty logical path")
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute() or ".." in PureWindowsPath(value).parts:
        raise EvaluationError("ABSOLUTE_PATH_BLOCKED", f"{field} must not be absolute or escape its root")
    return value.replace("\\", "/")


@dataclass(frozen=True)
class EvaluationProfile:
    name: str
    maximum_sequences: int
    batch_size: int
    timeout_seconds: int
    generation_enabled: bool
    continuation_enabled: bool
    fp32_comparison_sequences: int


@dataclass(frozen=True)
class EvaluationConfig:
    path: Path
    profile: EvaluationProfile
    artifact_registry: str
    prompt_set: str
    local_dataset_config: str
    dataset_manifest: str
    split_manifest: str
    evaluation_dataset: str
    tokenizer_model: str
    output_root: str
    dataset_identity: dict[str, Any]
    device: str
    precision: str
    seed: int
    deterministic_algorithms: bool
    raw_text_storage: bool
    token_id_storage: bool
    overwrite: bool
    external_benchmark: str
    metrics: dict[str, bool]
    generation: dict[str, Any]
    resource_limits: dict[str, int]

    @classmethod
    def from_yaml(cls, path: str | Path, *, profile: str | None = None) -> "EvaluationConfig":
        source = Path(path).resolve()
        try:
            value = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise EvaluationError("EVALUATION_CONFIG_INVALID", "evaluation config could not be read") from exc
        root = _mapping(value, "config")
        selected = profile or root.get("profile", "quick")
        profiles = _mapping(root.get("profiles"), "profiles")
        details = _mapping(profiles.get(selected), f"profiles.{selected}")
        if selected not in {"quick", "full"}:
            raise EvaluationError("EVALUATION_PROFILE_BLOCKED", "only quick and full profiles are supported")
        if root.get("raw_text_storage") is not False or root.get("token_id_storage") is not False:
            raise EvaluationError("EVALUATION_PRIVACY_POLICY", "raw text and token ID storage must remain disabled")
        if root.get("overwrite") is not False:
            raise EvaluationError("EVALUATION_OVERWRITE_BLOCKED", "evaluation outputs are immutable")
        if root.get("external_benchmark") != "disabled":
            raise EvaluationError("BENCHMARK_NOT_APPROVED", "external benchmarks are disabled")
        if root.get("execution_mode") not in {"inspection_only", "quick"}:
            raise EvaluationError("TRAINING_OPTION_BLOCKED", "unsupported execution mode")
        evaluation_profile = EvaluationProfile(
            name=selected,
            maximum_sequences=int(details["maximum_sequences"]),
            batch_size=int(details["batch_size"]),
            timeout_seconds=int(details["timeout_seconds"]),
            generation_enabled=bool(details["generation_enabled"]),
            continuation_enabled=bool(details["continuation_enabled"]),
            fp32_comparison_sequences=int(details["fp32_comparison_sequences"]),
        )
        if evaluation_profile.maximum_sequences <= 0 or evaluation_profile.batch_size <= 0:
            raise EvaluationError("EVALUATION_CONFIG_INVALID", "profile sizes must be positive")
        if selected == "full" and (
            evaluation_profile.maximum_sequences != 14329
            or evaluation_profile.timeout_seconds != 900
        ):
            raise EvaluationError(
                "FULL_PROFILE_INVALID",
                "full profile must evaluate all 14,329 sequences with a 900-second timeout",
            )
        identity = _mapping(root.get("dataset_identity"), "dataset_identity")
        required_identity = {
            "records": 4799,
            "packed_sequences": 14329,
            "target_tokens": 3653719,
            "split_fingerprint": "sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f",
            "original_validation_used": False,
        }
        for key, expected in required_identity.items():
            if identity.get(key) != expected:
                raise EvaluationError("EVALUATION_DATASET_MISMATCH", f"dataset_identity.{key} mismatch")
        return cls(
            path=source,
            profile=evaluation_profile,
            artifact_registry=_logical_path(root.get("artifact_registry"), "artifact_registry"),
            prompt_set=_logical_path(root.get("prompt_set"), "prompt_set"),
            local_dataset_config=_logical_path(root.get("local_dataset_config"), "local_dataset_config"),
            dataset_manifest=_logical_path(root.get("dataset_manifest"), "dataset_manifest"),
            split_manifest=_logical_path(root.get("split_manifest"), "split_manifest"),
            evaluation_dataset=_logical_path(root.get("evaluation_dataset"), "evaluation_dataset"),
            tokenizer_model=_logical_path(root.get("tokenizer_model"), "tokenizer_model"),
            output_root=_logical_path(root.get("output_root"), "output_root"),
            dataset_identity=identity,
            device=str(root.get("device")), precision=str(root.get("precision")), seed=int(root.get("seed")),
            deterministic_algorithms=bool(root.get("deterministic_algorithms")),
            raw_text_storage=False, token_id_storage=False, overwrite=False,
            external_benchmark="disabled",
            metrics={key: bool(item) for key, item in _mapping(root.get("metrics"), "metrics").items()},
            generation=_mapping(root.get("generation"), "generation"),
            resource_limits={key: int(item) for key, item in _mapping(root.get("resource_limits"), "resource_limits").items()},
        )

    @property
    def fingerprint(self) -> str:
        return file_checksum(self.path)

    @property
    def profile_fingerprint(self) -> str:
        return checksum_value({
            "name": self.profile.name,
            "maximum_sequences": self.profile.maximum_sequences,
            "batch_size": self.profile.batch_size,
            "timeout_seconds": self.profile.timeout_seconds,
            "generation_enabled": self.profile.generation_enabled,
            "continuation_enabled": self.profile.continuation_enabled,
            "fp32_comparison_sequences": self.profile.fp32_comparison_sequences,
            "device": self.device,
            "precision": self.precision,
            "seed": self.seed,
            "deterministic_algorithms": self.deterministic_algorithms,
            "metrics": self.metrics,
            "generation": self.generation,
        })

    def repository_path(self, logical: str) -> Path:
        return (repository_root() / _logical_path(logical, "repository path")).resolve()

    def external_root(self) -> Path:
        local = self.repository_path(self.local_dataset_config)
        try:
            value = yaml.safe_load(local.read_text(encoding="utf-8"))
            raw = value["datasets"]["external_root"]
        except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
            raise EvaluationError("LOCAL_PATH_MAPPING_INVALID", "external root mapping is unavailable") from exc
        root = Path(raw).resolve()
        if not root.is_dir():
            raise EvaluationError("LOCAL_PATH_MAPPING_INVALID", "configured external root does not exist")
        return root

    def external_path(self, logical: str) -> Path:
        root = self.external_root()
        path = (root / _logical_path(logical, "external path")).resolve()
        if root != path and root not in path.parents:
            raise EvaluationError("ABSOLUTE_PATH_BLOCKED", "external path escapes configured root")
        return path
