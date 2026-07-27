"""Logical artifact registry and read-only checkpoint validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import checksum_value, file_checksum
from src.training.checkpoint import CheckpointManager
from src.training.errors import TrainingError

from .config import EvaluationConfig, EvaluationError


ALLOWED_ELIGIBILITY = {"eligible", "missing", "checksum_mismatch", "fingerprint_mismatch", "not_approved", "superseded", "evaluation_blocked"}


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


@dataclass(frozen=True)
class EvaluationArtifact:
    artifact_id: str
    value: dict[str, Any]

    @property
    def identity_fingerprint(self) -> str:
        return checksum_value({"artifact_id": self.artifact_id, **self.value})

    @property
    def is_initial(self) -> bool:
        return self.value.get("artifact_type") == "deterministic_initialization"


class ArtifactRegistry:
    def __init__(self, artifacts: dict[str, EvaluationArtifact]):
        self.artifacts = artifacts

    @classmethod
    def load(cls, path: Path) -> "ArtifactRegistry":
        try:
            root = yaml.safe_load(path.read_text(encoding="utf-8"))
            values = root["artifacts"]
        except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
            raise EvaluationError("ARTIFACT_REGISTRY_INVALID", "artifact registry could not be read") from exc
        if not isinstance(values, dict) or not values:
            raise EvaluationError("ARTIFACT_REGISTRY_INVALID", "artifact registry is empty")
        required = {
            "display_name", "artifact_type", "model_version", "training_stage", "run_id", "checkpoint_step",
            "consumed_tokens", "equivalent_epoch", "dataset_version", "dataset_fingerprint",
            "source_lineage_fingerprint", "pii_fingerprint", "split_fingerprint",
            "tokenizer_version", "tokenizer_fingerprint", "model_fingerprint", "config_fingerprint",
            "checkpoint_training_config_fingerprint", "checkpoint_checksum", "checkpoint_bundle_bytes", "logical_external_path",
            "approval_status", "evaluation_eligibility", "publication_status",
        }
        artifacts: dict[str, EvaluationArtifact] = {}
        for artifact_id, value in values.items():
            if not isinstance(artifact_id, str) or not isinstance(value, dict) or set(value) != required:
                raise EvaluationError("ARTIFACT_REGISTRY_INVALID", f"invalid artifact record: {artifact_id}")
            if value["evaluation_eligibility"] not in ALLOWED_ELIGIBILITY:
                raise EvaluationError("ARTIFACT_REGISTRY_INVALID", f"invalid eligibility: {artifact_id}")
            artifacts[artifact_id] = EvaluationArtifact(artifact_id, value)
        return cls(artifacts)

    def get(self, artifact_id: str) -> EvaluationArtifact:
        try:
            return self.artifacts[artifact_id]
        except KeyError as exc:
            raise EvaluationError("ARTIFACT_NOT_REGISTERED", f"unregistered artifact: {artifact_id}") from exc

    def inspect(self, config: EvaluationConfig, artifact_id: str, *, require_eligible: bool = False) -> dict[str, Any]:
        artifact = self.get(artifact_id)
        declared = artifact.value["evaluation_eligibility"]
        if require_eligible and declared != "eligible":
            raise EvaluationError("ARTIFACT_EVALUATION_BLOCKED", f"artifact is {declared}")
        if artifact.is_initial:
            return {"artifact_id": artifact_id, "status": "eligible", "identity_fingerprint": artifact.identity_fingerprint, "checkpoint": None}
        logical = artifact.value["logical_external_path"]
        if not logical:
            return {"artifact_id": artifact_id, "status": "missing", "identity_fingerprint": artifact.identity_fingerprint, "checkpoint": None}
        path = config.external_path(logical)
        if not path.is_dir():
            return {"artifact_id": artifact_id, "status": "missing", "identity_fingerprint": artifact.identity_fingerprint, "checkpoint": None}
        try:
            inspection = CheckpointManager.inspect(path)
        except (TrainingError, OSError) as exc:
            return {"artifact_id": artifact_id, "status": "checksum_mismatch", "error_code": getattr(exc, "code", None), "identity_fingerprint": artifact.identity_fingerprint, "checkpoint": None}
        actual_checksum = file_checksum(path / "checksums.json")
        bundle_bytes = _directory_bytes(path)
        expected_checksum = artifact.value["checkpoint_checksum"]
        if expected_checksum is not None and actual_checksum != expected_checksum:
            status = "checksum_mismatch"
        elif bundle_bytes != artifact.value["checkpoint_bundle_bytes"]:
            status = "checksum_mismatch"
        elif inspection.global_step != artifact.value["checkpoint_step"]:
            status = "fingerprint_mismatch"
        elif inspection.training_config_fingerprint != artifact.value["checkpoint_training_config_fingerprint"]:
            status = "fingerprint_mismatch"
        elif inspection.tokenizer_fingerprint != artifact.value["tokenizer_fingerprint"] or inspection.model_config_fingerprint != artifact.value["model_fingerprint"]:
            status = "fingerprint_mismatch"
        elif inspection.dataset_fingerprint != artifact.value["dataset_fingerprint"]:
            status = "fingerprint_mismatch"
        elif declared != "eligible":
            status = declared
        else:
            status = "eligible"
        return {
            "artifact_id": artifact_id, "status": status, "identity_fingerprint": artifact.identity_fingerprint,
            "checkpoint": inspection.to_dict(), "checksums_manifest_sha256": actual_checksum,
            "checkpoint_bundle_bytes": bundle_bytes,
        }
