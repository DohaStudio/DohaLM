"""Single-use processing approval state machine with atomic persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    run_id: str
    manifest_sha256: str
    backend_git_commit: str
    state: str = "created"
    single_use: bool = True
    processing_allowed: bool = False
    training_allowed: bool = False
    execution_allowed: bool = False
    checksum: str = ""


def _payload(record: ApprovalRecord) -> dict[str, object]:
    value = asdict(record)
    value["checksum"] = ""
    return value


def approval_checksum(record: ApprovalRecord) -> str:
    encoded = json.dumps(_payload(record), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def new_approval(
    contract: ProcessingRunContract,
    *,
    manifest_sha256: str,
    backend_git_commit: str,
) -> ApprovalRecord:
    validate_run_contract(contract)
    if not _SHA256.fullmatch(manifest_sha256) or not _GIT_COMMIT.fullmatch(backend_git_commit):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    record = ApprovalRecord(
        approval_id=contract.approval_id,
        run_id=contract.run_id,
        manifest_sha256=manifest_sha256,
        backend_git_commit=backend_git_commit,
        processing_allowed=contract.processing_allowed,
        execution_allowed=contract.execution_allowed,
    )
    return replace(record, checksum=approval_checksum(record))


def validate_approval(record: ApprovalRecord, contract: ProcessingRunContract) -> ApprovalRecord:
    validate_run_contract(contract)
    if record.approval_id != contract.approval_id or record.run_id != contract.run_id:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if record.checksum != approval_checksum(record):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if record.state not in {"created", "validated", "consumed", "completed_or_failed"}:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if (
        record.single_use is not True
        or record.training_allowed
        or record.processing_allowed is not record.execution_allowed
        or record.processing_allowed is not contract.processing_allowed
    ):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    updated = replace(record, state="validated")
    return replace(updated, checksum=approval_checksum(updated))


def _atomic_write(path: Path, record: ApprovalRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ProcessingApprovalError("APPROVAL_ID_ALREADY_USED")
    temporary.write_text(json.dumps(asdict(record), sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def issue_approval(path: str | Path, record: ApprovalRecord) -> None:
    if record.state != "created" or Path(path).exists():
        raise ProcessingApprovalError("APPROVAL_ID_ALREADY_USED")
    _atomic_write(Path(path), record)


def _replace_state(path: Path, record: ApprovalRecord) -> None:
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ProcessingApprovalError("APPROVAL_ID_ALREADY_USED")
    temporary.write_text(json.dumps(asdict(record), sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def validate_approval_file(path: str | Path, contract: ProcessingRunContract) -> ApprovalRecord:
    target = Path(path)
    record = validate_approval(load_approval(target), contract)
    _replace_state(target, record)
    return record


def consume_approval(path: str | Path, record: ApprovalRecord) -> ApprovalRecord:
    """Atomically transition validated to consumed; never reuse an existing consume."""

    target = Path(path)
    if record.state != "validated" or not target.is_file() or load_approval(target) != record:
        raise ProcessingApprovalError("APPROVAL_NOT_CONSUMED")
    consumed = replace(record, state="consumed")
    consumed = replace(consumed, checksum=approval_checksum(consumed))
    _replace_state(target, consumed)
    return consumed


def load_approval(path: str | Path) -> ApprovalRecord:
    try:
        value: Mapping[str, object] = json.loads(Path(path).read_text(encoding="utf-8"))
        return ApprovalRecord(**value)  # type: ignore[arg-type]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND") from None


def finalize_approval(path: str | Path, record: ApprovalRecord) -> ApprovalRecord:
    target = Path(path)
    if record.state != "consumed" or not target.is_file():
        raise ProcessingApprovalError("APPROVAL_NOT_CONSUMED")
    completed = replace(record, state="completed_or_failed")
    completed = replace(completed, checksum=approval_checksum(completed))
    _replace_state(target, completed)
    return completed
