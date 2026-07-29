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

from .run_contract import ProcessingRunContract, validate_run_contract


class ProcessingApprovalError(RuntimeError):
    pass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STATES = frozenset({
    "prepared_not_issued", "issued", "consumed", "completed", "failed",
    "retired", "retired_before_consumption",
})


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    processing_run_id: str
    dataset_id: str
    component: str
    immutable_git_commit: str
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
    status: str = "prepared_not_issued"
    checksum: str = ""

    @property
    def run_id(self) -> str:
        return self.processing_run_id

    @property
    def state(self) -> str:
        return self.status

    @property
    def execution_allowed(self) -> bool:
        return self.processing_allowed and self.payload_read_allowed and self.output_write_allowed


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
    if not _GIT_COMMIT.fullmatch(record.immutable_git_commit) or any(not _SHA256.fullmatch(value) for value in fingerprints):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if not record.approved_by.strip():
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    approved = _timestamp(record.approved_at, required=True)
    issued = _timestamp(record.issued_at, required=record.status in {"issued", "consumed", "completed", "failed", "retired_before_consumption"})
    consumed = _timestamp(record.consumed_at, required=record.status in {"consumed", "completed", "failed"})
    completed = _timestamp(record.completed_at, required=record.status == "completed")
    failed = _timestamp(record.failed_at, required=record.status == "failed")
    unexpected = {
        "prepared_not_issued": (issued, consumed, completed, failed),
        "retired": (issued, consumed, completed, failed),
        "issued": (consumed, completed, failed),
        "retired_before_consumption": (consumed, completed, failed),
        "consumed": (completed, failed),
        "completed": (failed,),
        "failed": (completed,),
    }[record.status]
    if any(value is not None for value in unexpected):
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_ORDER_INVALID")
    ordered = [value for value in (approved, issued, consumed, completed or failed) if value is not None]
    if ordered != sorted(ordered):
        raise ProcessingApprovalError("APPROVAL_TIMESTAMP_ORDER_INVALID")
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
    permission = contract.processing_allowed
    if any(value is not permission for value in (
        record.processing_allowed, record.payload_read_allowed, record.output_write_allowed,
        contract.payload_read_allowed, contract.output_write_allowed, contract.execution_allowed,
    )):
        raise ProcessingApprovalError("APPROVAL_PERMISSION_ESCALATION")
    _budgets(record)
    return record


def new_approval(
    contract: ProcessingRunContract,
    *,
    immutable_git_commit: str,
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


def issue_approval(path: str | Path, record: ApprovalRecord, *, issued_at: str) -> ApprovalRecord:
    _timestamp(issued_at, required=True)
    issued = _transition(record, {"prepared_not_issued"}, "issued", issued_at=issued_at)
    _atomic_write(Path(path), issued, exclusive=True)
    return issued


def retire_approval(record: ApprovalRecord) -> ApprovalRecord:
    """Retire an unissued or unconsumed Approval without creating a runtime file."""

    if record.status == "prepared_not_issued":
        return _transition(record, {"prepared_not_issued"}, "retired")
    if record.status == "issued":
        return _transition(record, {"issued"}, "retired_before_consumption")
    if record.status in {"retired", "retired_before_consumption"}:
        raise ProcessingApprovalError("APPROVAL_RETIRED")
    raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")


def load_approval(path: str | Path) -> ApprovalRecord:
    try:
        value: Mapping[str, object] = json.loads(Path(path).read_text(encoding="utf-8"))
        return ApprovalRecord(**value)  # type: ignore[arg-type]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND") from None


def validate_approval_file(path: str | Path, contract: ProcessingRunContract) -> ApprovalRecord:
    return validate_approval(load_approval(path), contract)


def consume_approval(path: str | Path, record: ApprovalRecord, *, consumed_at: str) -> ApprovalRecord:
    target = Path(path)
    if record.status != "issued":
        raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
    if not target.is_file() or load_approval(target) != record:
        raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
    _timestamp(consumed_at, required=True)
    consumed = _transition(record, {"issued"}, "consumed", consumed_at=consumed_at)
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
