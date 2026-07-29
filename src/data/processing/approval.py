"""Expanded single-use processing Approval schema and atomic lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from .run_contract import (
    ProcessingRunContract,
    RuntimeExecutionRequest,
    validate_run_contract,
    validate_runtime_request,
)


class ProcessingApprovalError(RuntimeError):
    pass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STATES = frozenset({
    "prepared_not_issued", "issued", "consumed", "completed", "failed",
    "retired_not_issued", "retired_before_consumption", "retired_issue_incomplete",
})


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    processing_run_id: str
    dataset_id: str
    component: str
    immutable_git_commit: str
    governance_record_commit: str
    manifest_version: int
    manifest_sha256: str
    backend_fingerprint: str
    preflight_evidence_fingerprint: str
    approved_by: str
    approved_at: str
    issued_at: str | None = None
    consumed_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    maximum_runs: int = 1
    maximum_processing_calls: int = 1
    maximum_payload_open_sessions: int = 1
    retry_allowed: bool = False
    resume_allowed: bool = False
    overwrite_allowed: bool = False
    extension_allowed: bool = False
    run_id_reuse_allowed: bool = False
    approval_id_reuse_allowed: bool = False
    runtime_budget: Mapping[str, object] | None = None
    memory_budget: Mapping[str, object] | None = None
    disk_budget: Mapping[str, object] | None = None
    record_budget: Mapping[str, object] | None = None
    output_budget: Mapping[str, object] | None = None
    processing_allowed: bool = False
    payload_read_allowed: bool = False
    output_write_allowed: bool = False
    tokenization_allowed: bool = False
    sft_backend_allowed: bool = False
    training_allowed: bool = False
    execution_allowed: bool = False
    status: str = "prepared_not_issued"
    consumed: bool = False
    checksum: str = ""

    @property
    def run_id(self) -> str:
        return self.processing_run_id

    @property
    def state(self) -> str:
        return self.status


@dataclass(frozen=True)
class LegacyApprovalRecord:
    """Immutable, readable representation that can never authorize execution."""

    values: Mapping[str, object]
    executable: bool = False


def _timestamp(value: str | None, *, required: bool) -> datetime | None:
    if value is None:
        if required:
            raise ProcessingApprovalError("APPROVAL_TIMESTAMP_REQUIRED")
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_INVALID")
    return parsed


def _payload(record: ApprovalRecord) -> dict[str, object]:
    value = asdict(record)
    value["checksum"] = ""
    return value


def approval_checksum(record: ApprovalRecord) -> str:
    encoded = json.dumps(_payload(record), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _budgets(record: ApprovalRecord) -> None:
    expected = {
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        "record_budget": {"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        "output_budget": {"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
    }
    if any(dict(getattr(record, name) or {}) != value for name, value in expected.items()):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")


def validate_approval(record: ApprovalRecord, contract: ProcessingRunContract) -> ApprovalRecord:
    validate_run_contract(contract)
    if record.approval_id != contract.approval_id or record.processing_run_id != contract.run_id:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if record.checksum != approval_checksum(record):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if record.status not in _STATES:
        raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")
    if record.dataset_id != "AIHUB-71748" or record.component != "SFT" or record.manifest_version != 1:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    fingerprints = (record.manifest_sha256, record.backend_fingerprint, record.preflight_evidence_fingerprint)
    if not record.governance_record_commit:
        raise ProcessingApprovalError("APPROVAL_GOVERNANCE_COMMIT_REQUIRED")
    if (
        not _GIT_COMMIT.fullmatch(record.immutable_git_commit)
        or not _GIT_COMMIT.fullmatch(record.governance_record_commit)
        or any(not _SHA256.fullmatch(value) for value in fingerprints)
    ):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if not record.approved_by.strip():
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    approved = _timestamp(record.approved_at, required=True)
    issued = _timestamp(record.issued_at, required=record.status in {"issued", "consumed", "completed", "failed", "retired_before_consumption", "retired_issue_incomplete"})
    consumed = _timestamp(record.consumed_at, required=record.status in {"consumed", "completed", "failed"})
    completed = _timestamp(record.completed_at, required=record.status == "completed")
    failed = _timestamp(record.failed_at, required=record.status == "failed")
    unexpected = {
        "prepared_not_issued": (issued, consumed, completed, failed),
        "retired_not_issued": (issued, consumed, completed, failed),
        "issued": (consumed, completed, failed),
        "retired_before_consumption": (consumed, completed, failed),
        "retired_issue_incomplete": (consumed, completed, failed),
        "consumed": (completed, failed),
        "completed": (failed,),
        "failed": (completed,),
    }[record.status]
    if any(value is not None for value in unexpected):
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_ORDER_INVALID")
    ordered = [value for value in (approved, issued, consumed, completed or failed) if value is not None]
    if ordered != sorted(ordered):
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_ORDER_INVALID")
    if not isinstance(record.consumed, bool):
        raise ProcessingApprovalError("APPROVAL_CONSUMED_FIELD_REQUIRED")
    if not isinstance(record.execution_allowed, bool):
        raise ProcessingApprovalError("APPROVAL_EXECUTION_ALLOWED_FIELD_REQUIRED")
    expected_consumed = record.status in {"consumed", "completed"}
    if record.status == "failed":
        expected_consumed = record.consumed
    if record.status != "failed" and record.consumed is not expected_consumed:
        raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")
    if record.execution_allowed:
        raise ProcessingApprovalError("APPROVAL_PERMISSION_ESCALATION")
    if any((
        record.maximum_runs != 1,
        record.maximum_processing_calls != 1,
        record.maximum_payload_open_sessions != 1,
        record.retry_allowed,
        record.resume_allowed,
        record.overwrite_allowed,
        record.extension_allowed,
        record.run_id_reuse_allowed,
        record.approval_id_reuse_allowed,
        record.tokenization_allowed,
        record.sft_backend_allowed,
        record.training_allowed,
    )):
        raise ProcessingApprovalError("APPROVAL_PERMISSION_ESCALATION")
    capabilities = contract.processing_allowed
    if any(value is not capabilities for value in (
        record.processing_allowed, record.payload_read_allowed, record.output_write_allowed,
        contract.payload_read_allowed, contract.output_write_allowed,
    )):
        raise ProcessingApprovalError("APPROVAL_PERMISSION_ESCALATION")
    if contract.execution_allowed and not capabilities:
        raise ProcessingApprovalError("APPROVAL_CAPABILITY_INSUFFICIENT")
    _budgets(record)
    return record


def new_approval(
    contract: ProcessingRunContract,
    *,
    immutable_git_commit: str,
    governance_record_commit: str,
    manifest_sha256: str,
    backend_fingerprint: str,
    preflight_evidence_fingerprint: str,
    approved_by: str,
    approved_at: str,
) -> ApprovalRecord:
    validate_run_contract(contract)
    record = ApprovalRecord(
        approval_id=contract.approval_id,
        processing_run_id=contract.run_id,
        dataset_id="AIHUB-71748",
        component="SFT",
        immutable_git_commit=immutable_git_commit,
        governance_record_commit=governance_record_commit,
        manifest_version=1,
        manifest_sha256=manifest_sha256,
        backend_fingerprint=backend_fingerprint,
        preflight_evidence_fingerprint=preflight_evidence_fingerprint,
        approved_by=approved_by,
        approved_at=approved_at,
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        processing_allowed=contract.processing_allowed,
        payload_read_allowed=contract.payload_read_allowed,
        output_write_allowed=contract.output_write_allowed,
    )
    record = replace(record, checksum=approval_checksum(record))
    return validate_approval(record, contract)


def _atomic_write(path: Path, record: ApprovalRecord, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists() or (exclusive and path.exists()):
        raise ProcessingApprovalError("APPROVAL_ALREADY_ISSUED")
    temporary.write_text(json.dumps(asdict(record), sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _transition(record: ApprovalRecord, expected: set[str], target: str, **timestamps: str | None) -> ApprovalRecord:
    if record.status not in expected:
        code = "APPROVAL_ALREADY_FINALIZED" if record.status in {"completed", "failed", "retired"} else "APPROVAL_STATE_TRANSITION_INVALID"
        raise ProcessingApprovalError(code)
    updated = replace(record, status=target, **timestamps, checksum="")
    return replace(updated, checksum=approval_checksum(updated))


def validate_approval_issuance(
    record: ApprovalRecord,
    contract: ProcessingRunContract,
) -> ApprovalRecord:
    validated = validate_approval(record, contract)
    if validated.status != "prepared_not_issued":
        raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")
    if not all((
        validated.processing_allowed,
        validated.payload_read_allowed,
        validated.output_write_allowed,
    )):
        raise ProcessingApprovalError("APPROVAL_CAPABILITY_INSUFFICIENT")
    if validated.execution_allowed or validated.consumed:
        raise ProcessingApprovalError("APPROVAL_PERMISSION_ESCALATION")
    return validated


def issue_approval(
    path: str | Path,
    record: ApprovalRecord,
    *,
    issued_at: str,
    contract: ProcessingRunContract,
) -> ApprovalRecord:
    _timestamp(issued_at, required=True)
    validated = validate_approval_issuance(record, contract)
    issued = _transition(validated, {"prepared_not_issued"}, "issued", issued_at=issued_at)
    _atomic_write(Path(path), issued, exclusive=True)
    return issued


def retire_approval(record: ApprovalRecord) -> ApprovalRecord:
    """Retire an unissued or unconsumed Approval without creating a runtime file."""

    if record.status == "prepared_not_issued":
        return _transition(record, {"prepared_not_issued"}, "retired_not_issued")
    if record.status == "issued":
        return _transition(record, {"issued"}, "retired_before_consumption")
    if record.status in {"retired_not_issued", "retired_before_consumption", "retired_issue_incomplete"}:
        raise ProcessingApprovalError("APPROVAL_RETIRED")
    raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")


def deserialize_approval(value: Mapping[str, object]) -> ApprovalRecord:
    expected = {field.name for field in ApprovalRecord.__dataclass_fields__.values()}
    missing = expected - set(value)
    if "governance_record_commit" in missing:
        raise ProcessingApprovalError("APPROVAL_GOVERNANCE_COMMIT_REQUIRED")
    if "consumed" in missing:
        raise ProcessingApprovalError("APPROVAL_CONSUMED_FIELD_REQUIRED")
    if "execution_allowed" in missing:
        raise ProcessingApprovalError("APPROVAL_EXECUTION_ALLOWED_FIELD_REQUIRED")
    if missing:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if set(value) - expected:
        raise ProcessingApprovalError("APPROVAL_UNKNOWN_FIELD")
    try:
        return ApprovalRecord(**value)  # type: ignore[arg-type]
    except TypeError:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND") from None


def load_legacy_approval(path: str | Path) -> LegacyApprovalRecord:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND") from None
    if not isinstance(value, dict):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if all(name in value for name in ("governance_record_commit", "consumed", "execution_allowed")):
        raise ProcessingApprovalError("APPROVAL_NOT_LEGACY")
    return LegacyApprovalRecord(values=dict(value))


def load_approval(path: str | Path) -> ApprovalRecord:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError
        return deserialize_approval(value)
    except ProcessingApprovalError as exc:
        if str(exc) in {
            "APPROVAL_GOVERNANCE_COMMIT_REQUIRED",
            "APPROVAL_CONSUMED_FIELD_REQUIRED",
            "APPROVAL_EXECUTION_ALLOWED_FIELD_REQUIRED",
        }:
            raise ProcessingApprovalError("LEGACY_APPROVAL_NOT_EXECUTABLE") from None
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND") from None


def validate_approval_file(path: str | Path, contract: ProcessingRunContract) -> ApprovalRecord:
    return validate_approval(load_approval(path), contract)


def consume_approval(
    path: str | Path,
    record: ApprovalRecord,
    *,
    consumed_at: str,
    contract: ProcessingRunContract,
    runtime_request: RuntimeExecutionRequest,
) -> ApprovalRecord:
    target = Path(path)
    validate_approval(record, contract)
    validate_runtime_request(runtime_request, contract)
    if record.status != "issued":
        raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
    if not target.is_file() or load_approval(target) != record:
        raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
    _timestamp(consumed_at, required=True)
    consumed = _transition(record, {"issued"}, "consumed", consumed_at=consumed_at, consumed=True)
    _atomic_write(target, consumed)
    return consumed


def finalize_approval(
    path: str | Path,
    record: ApprovalRecord,
    *,
    success: bool,
    finalized_at: str,
) -> ApprovalRecord:
    target = Path(path)
    if not target.is_file() or load_approval(target) != record:
        raise ProcessingApprovalError("APPROVAL_ALREADY_FINALIZED")
    _timestamp(finalized_at, required=True)
    field = {"completed_at": finalized_at} if success else {"failed_at": finalized_at}
    final = _transition(record, {"consumed"}, "completed" if success else "failed", **field)
    _atomic_write(target, final)
    return final
