"""Read-only permission boundary for an immutable Common Dataset pair."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.data.checksums import canonical_json_bytes, checksum_value
from src.data.common_dataset_contracts import (
    CommonContractRuntimeError,
    CommonDatasetValidationError,
    validate_dataset_manifest,
    validate_dataset_publication_scenario,
    validate_dataset_version,
    verify_common_contract_runtime,
)

from .errors import TrainingError
from .full_pretraining import require_full_pretraining_approval


@dataclass(frozen=True)
class DatasetTrainingPermission:
    """Immutable, non-activating decision for one explicit Dataset pair."""

    allowed: bool
    reason_codes: tuple[str, ...]
    dataset_version_id: str = ""
    dataset_manifest_id: str = ""
    pair_fingerprint: str = ""
    _validated: bool = field(default=False, init=False, repr=False, compare=False)


def evaluate_dataset_training_entry(
    dataset_version: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    *,
    upstream_objects: Sequence[Mapping[str, Any]],
    evaluated_at: str,
    readiness_report: Mapping[str, Any],
    expected_split_id: str,
    artifact_references: Sequence[Mapping[str, Any]],
) -> DatasetTrainingPermission:
    """Validate explicit immutable inputs without reading data or activating training."""

    try:
        verify_common_contract_runtime()
    except CommonContractRuntimeError:
        return _blocked("COMMON_CONTRACT_RUNTIME_UNAVAILABLE")

    try:
        version = _snapshot_mapping(dataset_version)
        manifest = _snapshot_mapping(dataset_manifest)
        upstream = _snapshot_sequence(upstream_objects)
        readiness = _snapshot_mapping(readiness_report)
        artifacts = _snapshot_sequence(artifact_references)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _blocked("DATASET_TRAINING_INPUT_INVALID")

    try:
        validate_dataset_version(version)
    except (CommonContractRuntimeError, CommonDatasetValidationError):
        return _blocked("DATASET_VERSION_INVALID")
    try:
        validate_dataset_manifest(manifest)
    except (CommonContractRuntimeError, CommonDatasetValidationError):
        return _blocked("DATASET_MANIFEST_INVALID")

    if version.get("status") != "frozen" or version.get("frozen") is not True:
        return _blocked("DATASET_VERSION_NOT_FROZEN")
    if manifest.get("manifest_status") != "issued":
        return _blocked("DATASET_MANIFEST_NOT_ISSUED")
    if (
        version.get("approved") is not True
        or version.get("training_allowed") is not True
        or manifest.get("training_allowed") is not True
    ):
        return _blocked("DATASET_TRAINING_NOT_ALLOWED")

    if not _identity_matches(version, manifest):
        return _blocked("DATASET_PAIR_IDENTITY_MISMATCH")
    if not _checksums_match(version, manifest):
        return _blocked("DATASET_PAIR_CHECKSUM_MISMATCH")

    try:
        validate_dataset_publication_scenario(
            {"evaluated_at": evaluated_at, "objects": [*upstream, version, manifest]}
        )
    except (CommonContractRuntimeError, CommonDatasetValidationError):
        return _blocked("DATASET_PUBLICATION_SCENARIO_INVALID")

    if (
        version.get("rights_summary") != {"status": "pass", "exception_count": 0}
        or manifest.get("dataset_domain") != "lm"
        or manifest.get("deletion_status") != "active"
    ):
        return _blocked("DATASET_DOMAIN_READINESS_INVALID")

    try:
        require_full_pretraining_approval(readiness)
    except TrainingError:
        return _blocked("FULL_PRETRAINING_READINESS_BLOCKED")
    if (
        readiness.get("inspection_only") is not True
        or readiness.get("training_started") is not False
        or readiness.get("blocking_codes") != []
    ):
        return _blocked("FULL_PRETRAINING_READINESS_INVALID")

    if expected_split_id != manifest.get("split_id"):
        return _blocked("DATASET_SPLIT_REFERENCE_MISMATCH")
    if artifacts != manifest.get("object_file_artifact_refs"):
        return _blocked("DATASET_ARTIFACT_REFERENCE_MISMATCH")

    permission = DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id=version["object_id"],
        dataset_manifest_id=manifest["dataset_manifest_id"],
        pair_fingerprint=checksum_value(
            {"dataset_manifest": manifest, "dataset_version": version}
        ),
    )
    object.__setattr__(permission, "_validated", True)
    return permission


def require_dataset_training_activation(
    permission: DatasetTrainingPermission | None,
    *,
    dataset_version_id: str,
    dataset_manifest_id: str,
    pair_fingerprint: str,
) -> None:
    """Consume one validated permission for an explicit execution target."""

    if (
        type(permission) is not DatasetTrainingPermission
        or permission._validated is not True
    ):
        raise TrainingError(
            "DATASET_TRAINING_PERMISSION_INVALID",
            "A validated immutable Dataset permission is required.",
        )
    if permission.allowed is not True or permission.reason_codes != ():
        raise TrainingError(
            "DATASET_TRAINING_PERMISSION_DENIED",
            "The Dataset permission does not allow training entry.",
        )
    if (
        not all(
            isinstance(value, str) and value
            for value in (dataset_version_id, dataset_manifest_id, pair_fingerprint)
        )
        or re.fullmatch(r"sha256:[0-9a-f]{64}", pair_fingerprint) is None
    ):
        raise TrainingError(
            "DATASET_TRAINING_TARGET_INVALID",
            "Explicit immutable Dataset target identity is required.",
        )
    if (
        permission.dataset_version_id != dataset_version_id
        or permission.dataset_manifest_id != dataset_manifest_id
        or permission.pair_fingerprint != pair_fingerprint
    ):
        raise TrainingError(
            "DATASET_TRAINING_PERMISSION_TARGET_MISMATCH",
            "The Dataset permission does not match the execution target.",
        )


def _snapshot_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("mapping required")
    snapshot = json.loads(canonical_json_bytes(value))
    if not isinstance(snapshot, dict):
        raise TypeError("object required")
    return snapshot


def _snapshot_sequence(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)):
        raise TypeError("sequence required")
    return [_snapshot_mapping(value) for value in values]


def _identity_matches(version: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    return all(
        left == right
        for left, right in (
            (version.get("dataset_manifest_id"), manifest.get("object_id")),
            (version.get("dataset_manifest_id"), manifest.get("dataset_manifest_id")),
            (version.get("object_id"), manifest.get("source_dataset_version_id")),
            (version.get("dataset_id"), manifest.get("dataset_id")),
            (version.get("dataset_version"), manifest.get("dataset_version")),
            (version.get("candidate_count"), manifest.get("item_count")),
        )
    )


def _checksums_match(version: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    projection = dict(manifest)
    manifest_checksum = projection.pop("manifest_checksum", None)
    return manifest.get("source_dataset_version_checksum") == version.get(
        "content_fingerprint"
    ) and manifest_checksum == checksum_value(projection)


def _blocked(code: str) -> DatasetTrainingPermission:
    permission = DatasetTrainingPermission(allowed=False, reason_codes=(code,))
    object.__setattr__(permission, "_validated", True)
    return permission


__all__ = [
    "DatasetTrainingPermission",
    "evaluate_dataset_training_entry",
    "require_dataset_training_activation",
]
