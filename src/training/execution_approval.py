"""Process-local Generic Training Execution Approval boundary.

No production issuer adapter is provided here. The module-private issuance and
revocation seams are reserved for a separately approved trusted adapter and for
synthetic tests of this boundary.
"""

from __future__ import annotations

import re
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data.checksums import checksum_value, file_checksum

from .dataset_training_entry import (
    DatasetTrainingPermission,
    require_dataset_training_activation,
)
from .errors import TrainingError
from .full_pretraining import (
    FullPretrainingConfig,
    require_full_pretraining_technical_readiness,
    resolve_full_pretraining_path,
)
from .source_state import _SourceStateInspectionError, _inspect_source_state


_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class TrainingExecutionRequest:
    schema_version: int
    action: str
    dataset_version_id: str
    dataset_manifest_id: str
    dataset_pair_fingerprint: str
    config_fingerprint: str
    readiness_fingerprint: str
    run_id: str
    output_logical_root: str
    source_commit: str
    execution_mode: str
    request_fingerprint: str


@dataclass(frozen=True)
class TrainingExecutionApproval:
    authorization_id: str
    issuer_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    issued_at: str


@dataclass
class _RequestRecord:
    reference: weakref.ReferenceType[TrainingExecutionRequest]
    values: tuple[Any, ...]
    permission_reference: weakref.ReferenceType[DatasetTrainingPermission]


@dataclass
class _ApprovalRecord:
    reference: weakref.ReferenceType[TrainingExecutionApproval]
    values: tuple[Any, ...]
    request_reference: weakref.ReferenceType[TrainingExecutionRequest]
    permission_reference: weakref.ReferenceType[DatasetTrainingPermission]
    state: str


_REGISTRY_LOCK = threading.RLock()
_REQUEST_REGISTRY: dict[int, _RequestRecord] = {}
_APPROVAL_REGISTRY: dict[int, _ApprovalRecord] = {}


def _values(value: object) -> tuple[Any, ...]:
    return tuple(getattr(value, item.name) for item in fields(value))


def _invalid_request() -> TrainingError:
    return TrainingError(
        "TRAINING_EXECUTION_REQUEST_INVALID",
        "A validated immutable execution request is required.",
    )


def _validate_target(
    permission: DatasetTrainingPermission | None,
    dataset_version_id: str,
    dataset_manifest_id: str,
    dataset_pair_fingerprint: str,
) -> DatasetTrainingPermission:
    require_dataset_training_activation(
        permission,
        dataset_version_id=dataset_version_id,
        dataset_manifest_id=dataset_manifest_id,
        pair_fingerprint=dataset_pair_fingerprint,
    )
    assert permission is not None
    return permission


def _request_projection(request: TrainingExecutionRequest) -> dict[str, Any]:
    return {
        "schema_version": request.schema_version,
        "action": request.action,
        "dataset_version_id": request.dataset_version_id,
        "dataset_manifest_id": request.dataset_manifest_id,
        "dataset_pair_fingerprint": request.dataset_pair_fingerprint,
        "config_fingerprint": request.config_fingerprint,
        "readiness_fingerprint": request.readiness_fingerprint,
        "run_id": request.run_id,
        "output_logical_root": request.output_logical_root,
        "source_commit": request.source_commit,
        "execution_mode": request.execution_mode,
    }


def _current_request_record(
    request: TrainingExecutionRequest | None,
) -> _RequestRecord:
    if type(request) is not TrainingExecutionRequest:
        raise _invalid_request()
    with _REGISTRY_LOCK:
        record = _REQUEST_REGISTRY.get(id(request))
        if (
            record is None
            or record.reference() is not request
            or record.values != _values(request)
            or checksum_value(_request_projection(request))
            != request.request_fingerprint
        ):
            raise _invalid_request()
        return record


def _verified_source(expected_commit: str) -> None:
    try:
        source = _inspect_source_state()
    except _SourceStateInspectionError as exc:
        raise _invalid_request() from exc
    if source.commit != expected_commit or not source.clean:
        raise _invalid_request()


def build_training_execution_request(
    config_path: Path,
    readiness_report: Mapping[str, Any],
    *,
    readiness_fingerprint: str,
    dataset_permission: DatasetTrainingPermission | None,
    dataset_version_id: str,
    dataset_manifest_id: str,
    dataset_pair_fingerprint: str,
) -> TrainingExecutionRequest:
    """Build and register one exact, immutable fresh execution request."""

    permission = _validate_target(
        dataset_permission,
        dataset_version_id,
        dataset_manifest_id,
        dataset_pair_fingerprint,
    )
    if not isinstance(readiness_report, Mapping):
        raise _invalid_request()
    report = dict(readiness_report)
    require_full_pretraining_technical_readiness(report)
    source_commit = report.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or _COMMIT_PATTERN.fullmatch(source_commit) is None
        or report.get("source_worktree_clean") is not True
        or not isinstance(report.get("readiness_fingerprint"), str)
        or _FINGERPRINT_PATTERN.fullmatch(report["readiness_fingerprint"]) is None
        or not isinstance(readiness_fingerprint, str)
        or _FINGERPRINT_PATTERN.fullmatch(readiness_fingerprint) is None
    ):
        raise _invalid_request()
    config = FullPretrainingConfig.from_yaml(config_path)
    if config.resume_checkpoint is not None:
        raise _invalid_request()
    _verified_source(source_commit)
    output_root = resolve_full_pretraining_path(config, config.output_dir)
    values = {
        "schema_version": 1,
        "action": "full_pretraining",
        "dataset_version_id": dataset_version_id,
        "dataset_manifest_id": dataset_manifest_id,
        "dataset_pair_fingerprint": dataset_pair_fingerprint,
        "config_fingerprint": file_checksum(config_path),
        "readiness_fingerprint": readiness_fingerprint,
        "run_id": output_root.name,
        "output_logical_root": config.output_dir,
        "source_commit": source_commit,
        "execution_mode": "fresh",
    }
    request = TrainingExecutionRequest(
        **values,
        request_fingerprint=checksum_value(values),
    )
    key = id(request)

    def discard(
        reference: weakref.ReferenceType[TrainingExecutionRequest],
        *,
        identity: int = key,
    ) -> None:
        with _REGISTRY_LOCK:
            current = _REQUEST_REGISTRY.get(identity)
            if current is not None and current.reference is reference:
                _REQUEST_REGISTRY.pop(identity, None)

    reference = weakref.ref(request, discard)
    with _REGISTRY_LOCK:
        _REQUEST_REGISTRY[key] = _RequestRecord(
            reference=reference,
            values=_values(request),
            permission_reference=weakref.ref(permission),
        )
    return request


def require_training_execution_request(
    request: TrainingExecutionRequest | None,
    config_path: Path,
    readiness_report: Mapping[str, Any],
    *,
    dataset_permission: DatasetTrainingPermission | None,
    dataset_version_id: str,
    dataset_manifest_id: str,
    dataset_pair_fingerprint: str,
) -> None:
    """Validate exact request provenance and its current non-source bindings."""

    permission = _validate_target(
        dataset_permission,
        dataset_version_id,
        dataset_manifest_id,
        dataset_pair_fingerprint,
    )
    record = _current_request_record(request)
    assert request is not None
    config = FullPretrainingConfig.from_yaml(config_path)
    if (
        record.permission_reference() is not permission
        or request.schema_version != 1
        or request.action != "full_pretraining"
        or request.dataset_version_id != dataset_version_id
        or request.dataset_manifest_id != dataset_manifest_id
        or request.dataset_pair_fingerprint != dataset_pair_fingerprint
        or request.config_fingerprint != file_checksum(config_path)
        or request.run_id
        != resolve_full_pretraining_path(config, config.output_dir).name
        or request.output_logical_root != config.output_dir
        or request.source_commit != readiness_report.get("source_commit")
        or readiness_report.get("source_worktree_clean") is not True
        or request.execution_mode != "fresh"
        or config.resume_checkpoint is not None
    ):
        raise _invalid_request()


def _issue_training_execution_approval_from_trusted_adapter(
    request: TrainingExecutionRequest,
    *,
    dataset_permission: DatasetTrainingPermission,
    decision: str,
    authorization_id: str,
    issuer_id: str,
    approver_reference: str,
    evidence_reference: str,
    request_fingerprint: str,
    issued_at: str,
) -> TrainingExecutionApproval:
    """Internal seam for a future trusted adapter; not a production issuer."""

    if decision != "approved":
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_DENIED",
            "The accountable issuer denied this execution request.",
        )
    request_record = _current_request_record(request)
    if request_record.permission_reference() is not dataset_permission:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
            "The approval target does not match the execution request.",
        )
    if request_fingerprint != request.request_fingerprint:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
            "The approval target does not match the execution request.",
        )
    evidence_values = (
        authorization_id,
        issuer_id,
        approver_reference,
        evidence_reference,
        request_fingerprint,
        issued_at,
    )
    if not all(isinstance(value, str) and value.strip() for value in evidence_values):
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_INVALID",
            "Validated external authorization evidence is required.",
        )
    try:
        timestamp = datetime.fromisoformat(issued_at)
    except ValueError as exc:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_INVALID",
            "Validated external authorization evidence is required.",
        ) from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_INVALID",
            "Validated external authorization evidence is required.",
        )
    approval = TrainingExecutionApproval(*evidence_values)
    key = id(approval)

    def discard(
        reference: weakref.ReferenceType[TrainingExecutionApproval],
        *,
        identity: int = key,
    ) -> None:
        with _REGISTRY_LOCK:
            current = _APPROVAL_REGISTRY.get(identity)
            if current is not None and current.reference is reference:
                _APPROVAL_REGISTRY.pop(identity, None)

    reference = weakref.ref(approval, discard)
    with _REGISTRY_LOCK:
        _APPROVAL_REGISTRY[key] = _ApprovalRecord(
            reference=reference,
            values=_values(approval),
            request_reference=weakref.ref(request),
            permission_reference=weakref.ref(dataset_permission),
            state="issued",
        )
    return approval


def _dataset_permission_for_training_execution_request(
    request: TrainingExecutionRequest,
) -> DatasetTrainingPermission:
    """Resolve the exact permission bound to an evaluator-issued request."""

    record = _current_request_record(request)
    permission = record.permission_reference()
    if permission is None:
        raise _invalid_request()
    return permission


def _approval_record(
    approval: TrainingExecutionApproval | None,
) -> _ApprovalRecord:
    if approval is None:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_REQUIRED",
            "A training execution approval is required.",
        )
    if type(approval) is not TrainingExecutionApproval:
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_INVALID",
            "A valid training execution approval is required.",
        )
    with _REGISTRY_LOCK:
        record = _APPROVAL_REGISTRY.get(id(approval))
        if (
            record is None
            or record.reference() is not approval
            or record.values != _values(approval)
        ):
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_INVALID",
                "A valid training execution approval is required.",
            )
        if record.state == "consumed":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_CONSUMED",
                "The training execution approval was already consumed.",
            )
        if record.state == "revoked":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_REVOKED",
                "The training execution approval was revoked.",
            )
        return record


def consume_training_execution_approval(
    approval: TrainingExecutionApproval | None,
    request: TrainingExecutionRequest | None,
    *,
    dataset_permission: DatasetTrainingPermission | None,
    dataset_version_id: str,
    dataset_manifest_id: str,
    dataset_pair_fingerprint: str,
) -> None:
    """Validate final source state, then atomically consume exact approval."""

    permission = _validate_target(
        dataset_permission,
        dataset_version_id,
        dataset_manifest_id,
        dataset_pair_fingerprint,
    )
    request_record = _current_request_record(request)
    record = _approval_record(approval)
    assert request is not None and approval is not None
    if (
        request_record.permission_reference() is not permission
        or record.request_reference() is not request
        or record.permission_reference() is not permission
        or approval.request_fingerprint != request.request_fingerprint
    ):
        raise TrainingError(
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
            "The approval does not match the execution target.",
        )
    _verified_source(request.source_commit)
    with _REGISTRY_LOCK:
        current = _APPROVAL_REGISTRY.get(id(approval))
        if current is None or current.reference() is not approval:
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_INVALID",
                "A valid training execution approval is required.",
            )
        if current.state == "consumed":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_CONSUMED",
                "The training execution approval was already consumed.",
            )
        if current.state == "revoked":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_REVOKED",
                "The training execution approval was revoked.",
            )
        current.state = "consumed"


def _revoke_training_execution_approval_from_trusted_adapter(
    approval: TrainingExecutionApproval,
) -> None:
    """Internal terminal transition for a future trusted adapter."""

    _approval_record(approval)
    with _REGISTRY_LOCK:
        current = _APPROVAL_REGISTRY.get(id(approval))
        if current is None or current.reference() is not approval:
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_INVALID",
                "A valid training execution approval is required.",
            )
        if current.state == "consumed":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_CONSUMED",
                "The training execution approval was already consumed.",
            )
        if current.state == "revoked":
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_REVOKED",
                "The training execution approval was revoked.",
            )
        current.state = "revoked"


__all__ = [
    "TrainingExecutionApproval",
    "TrainingExecutionRequest",
    "build_training_execution_request",
    "consume_training_execution_approval",
    "require_training_execution_request",
]
