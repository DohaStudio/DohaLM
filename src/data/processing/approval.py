"""Expanded single-use processing Approval schema and atomic lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import BinaryIO, Iterator, Mapping

from .run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RuntimeExecutionRequest,
    validate_run_contract,
    validate_runtime_request,
)


class ProcessingApprovalError(RuntimeError):
    pass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_RETIREMENT_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_STATES = frozenset({
    "prepared_not_issued", "issued", "consumed", "completed", "failed",
    "retired_not_issued", "retired_before_consumption", "retired_issue_incomplete",
})

_RETIREMENT_EVIDENCE_SUFFIX = ".retirement.json"
_LIFECYCLE_LOCK_SUFFIX = ".lifecycle.lock"
_RETIREMENT_TEMP_SUFFIX = ".retirement.tmp"
_RETIREMENT_EVIDENCE_TEMP_SUFFIX = ".retirement-evidence.tmp"
_RETIREMENT_PROBE_SUFFIX = ".retirement-link-probe"


@dataclass(frozen=True)
class ApprovalRecord:
    schema_version: int
    approval_id: str
    processing_run_id: str
    dataset_id: str
    component: str
    execution_source_commit: str
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
    def immutable_git_commit(self) -> str:
        """Read-only legacy alias; v2 serialization uses execution_source_commit."""

        return self.execution_source_commit

    @property
    def state(self) -> str:
        return self.status


@dataclass(frozen=True)
class LegacyApprovalRecord:
    """Immutable, readable representation that can never authorize execution."""

    values: Mapping[str, object]
    executable: bool = False


@dataclass(frozen=True)
class ApprovalRetirementEvidence:
    """Immutable audit evidence kept separately from ApprovalRecord schema v2."""

    schema_version: int
    approval_id: str
    processing_run_id: str
    previous_status: str
    status: str
    retired_at: str
    reason_code: str
    before_file_sha256: str
    after_file_sha256: str
    before_checksum: str
    after_checksum: str
    stable_fingerprint: str
    evidence_fingerprint: str = ""


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


def approval_fingerprint(record: ApprovalRecord) -> str:
    """Stable Approval identity fingerprint across lifecycle transitions."""

    value = asdict(record)
    for field_name in (
        "approved_at", "issued_at", "consumed_at", "completed_at", "failed_at",
        "status", "consumed", "checksum",
    ):
        value.pop(field_name)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def approval_retirement_evidence_path(path: str | Path) -> Path:
    target = Path(path)
    return target.with_name(target.stem + _RETIREMENT_EVIDENCE_SUFFIX)


def approval_retirement_evidence_fingerprint(
    evidence: ApprovalRetirementEvidence,
) -> str:
    value = asdict(evidence)
    value["evidence_fingerprint"] = ""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND") from None
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            asdict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED") from None


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
    if record.schema_version != 2 or record.status not in _STATES:
        raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")
    if record.dataset_id != "AIHUB-71748" or record.component != "SFT" or record.manifest_version != 1:
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    fingerprints = (record.manifest_sha256, record.backend_fingerprint, record.preflight_evidence_fingerprint)
    if not record.governance_record_commit:
        raise ProcessingApprovalError("APPROVAL_GOVERNANCE_COMMIT_REQUIRED")
    if (
        not _GIT_COMMIT.fullmatch(record.execution_source_commit)
        or not _GIT_COMMIT.fullmatch(record.governance_record_commit)
        or any(not _SHA256.fullmatch(value) for value in fingerprints)
    ):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    if not record.approved_by.strip():
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    approved = _timestamp(record.approved_at, required=True)
    issued = _timestamp(record.issued_at, required=record.status in {"issued", "consumed", "completed", "retired_before_consumption"})
    consumed = _timestamp(record.consumed_at, required=record.status in {"consumed", "completed"} or (record.status == "failed" and record.consumed))
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
        raise ProcessingApprovalError("APPROVAL_ARTIFACT_EXECUTION_FLAG_FORBIDDEN")
    boolean_fields = (
        record.retry_allowed, record.resume_allowed, record.overwrite_allowed,
        record.extension_allowed, record.run_id_reuse_allowed,
        record.approval_id_reuse_allowed, record.processing_allowed,
        record.payload_read_allowed, record.output_write_allowed,
        record.tokenization_allowed, record.sft_backend_allowed,
        record.training_allowed, record.execution_allowed, record.consumed,
    )
    if not all(isinstance(value, bool) for value in boolean_fields):
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
    immutable_git_commit: str | None = None,
    execution_source_commit: str | None = None,
    governance_record_commit: str,
    manifest_sha256: str,
    backend_fingerprint: str,
    preflight_evidence_fingerprint: str,
    approved_by: str,
    approved_at: str,
) -> ApprovalRecord:
    validate_run_contract(contract)
    source_commit = execution_source_commit or immutable_git_commit
    if source_commit is None or (
        immutable_git_commit is not None
        and execution_source_commit is not None
        and immutable_git_commit != execution_source_commit
    ):
        raise ProcessingApprovalError("APPROVAL_NOT_FOUND")
    record = ApprovalRecord(
        schema_version=2,
        approval_id=contract.approval_id,
        processing_run_id=contract.run_id,
        dataset_id="AIHUB-71748",
        component="SFT",
        execution_source_commit=source_commit,
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


def _canonical_record_bytes(record: ApprovalRecord) -> bytes:
    try:
        return json.dumps(
            asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ProcessingApprovalError("APPROVAL_ATOMIC_WRITE_FAILED") from None


def _directory_fsync_supported() -> bool:
    """Return the explicit platform policy for parent-directory durability.

    POSIX supports opening and syncing a directory through ``os.open``. The
    Windows Python runtime does not expose an equivalent directory handle via
    this API, so Windows uses durable file fsync plus atomic ``os.replace``.
    This branch is deliberate and covered by tests; directory-sync failures on
    supported platforms are never ignored.
    """

    return os.name != "nt"


def _sync_parent_directory(path: Path) -> None:
    if not _directory_fsync_supported():
        return
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.parent, flags)
        os.fsync(descriptor)
    except OSError:
        raise ProcessingApprovalError("APPROVAL_DIRECTORY_SYNC_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


_NO_REPLACE_UNSUPPORTED_ERRNOS = frozenset({
    errno.EXDEV,
    errno.EINVAL,
    errno.ENOSYS,
    getattr(errno, "ENOTSUP", errno.ENOSYS),
    getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
})


def _link_no_replace(temporary: Path, final: Path) -> None:
    """Atomically publish one hard link without replacement semantics."""

    try:
        os.link(temporary, final)
    except FileExistsError:
        raise ProcessingApprovalError("APPROVAL_PUBLISH_COLLISION") from None
    except OSError as exc:
        if exc.errno in _NO_REPLACE_UNSUPPORTED_ERRNOS or getattr(exc, "winerror", None) in {1, 50}:
            raise ProcessingApprovalError("APPROVAL_NO_REPLACE_UNSUPPORTED") from None
        raise ProcessingApprovalError("APPROVAL_ATOMIC_PUBLISH_FAILED") from None


def _publish_no_replace_posix(temporary: Path, final: Path) -> None:
    """POSIX atomic no-replace publish on one hard-link-capable filesystem."""

    _link_no_replace(temporary, final)


def _publish_no_replace_windows(temporary: Path, final: Path) -> None:
    """Windows atomic no-replace publish using CreateHardLink via os.link."""

    _link_no_replace(temporary, final)


def _approval_platform() -> str:
    return os.name


def _publish_no_replace(temporary: Path, final: Path) -> None:
    platform = _approval_platform()
    if platform == "posix":
        _publish_no_replace_posix(temporary, final)
    elif platform == "nt":
        _publish_no_replace_windows(temporary, final)
    else:
        raise ProcessingApprovalError("APPROVAL_NO_REPLACE_UNSUPPORTED")


def _atomic_write(path: Path, record: ApprovalRecord, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if exclusive and path.exists():
        raise ProcessingApprovalError("APPROVAL_ALREADY_ISSUED")
    payload = _canonical_record_bytes(record)
    descriptor = -1
    published = False
    try:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ProcessingApprovalError("APPROVAL_TEMPORARY_COLLISION") from None
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            written = stream.write(payload)
            if written != len(payload):
                raise OSError("short write")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            _publish_no_replace(temporary, path)
            published = True
            try:
                temporary.unlink()
            except OSError:
                raise ProcessingApprovalError("APPROVAL_ISSUANCE_INCOMPLETE") from None
        else:
            os.replace(temporary, path)
            published = True
        _sync_parent_directory(path)
    except ProcessingApprovalError:
        raise
    except (OSError, ValueError):
        raise ProcessingApprovalError("APPROVAL_ATOMIC_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                raise ProcessingApprovalError("APPROVAL_ISSUANCE_INCOMPLETE") from None


def _retirement_compare_and_swap_hook(_path: Path) -> None:
    """Deterministic race-test seam; production behavior is intentionally empty."""


def _write_complete(stream: BinaryIO, payload: bytes) -> None:
    written = stream.write(payload)
    if written != len(payload):
        raise OSError("short write")


def _flush_and_sync(stream: BinaryIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def _write_retirement_temporary(path: Path, payload: bytes) -> None:
    descriptor = -1
    created = False
    completed = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            _write_complete(stream, payload)
            _flush_and_sync(stream)
        completed = True
    except FileExistsError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_TEMPORARY_COLLISION") from None
    except OSError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if created and not completed and path.exists():
            try:
                path.unlink()
            except OSError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None


@contextmanager
def _retirement_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + _LIFECYCLE_LOCK_SUFFIX)
    nonce = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"owner_pid": os.getpid(), "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor = -1
    acquired = False
    try:
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ProcessingApprovalError("APPROVAL_RETIREMENT_LOCK_COLLISION") from None
        acquired = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            _write_complete(stream, payload)
        yield
    except ProcessingApprovalError:
        raise
    except OSError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if acquired:
            try:
                if lock_path.read_bytes() != payload:
                    raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE")
                lock_path.unlink()
            except ProcessingApprovalError:
                raise
            except OSError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None


@contextmanager
def approval_lifecycle_lock(path: str | Path) -> Iterator[None]:
    """Serialize cooperative Approval lifecycle and runtime-request writers."""

    with _retirement_lock(Path(path)):
        yield


def _cleanup_retirement_temporary(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None


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
    counters: ExecutionCounters | None = None,
) -> ApprovalRecord:
    _timestamp(issued_at, required=True)
    validated = validate_approval_issuance(record, contract)
    issued = _transition(validated, {"prepared_not_issued"}, "issued", issued_at=issued_at)
    _atomic_write(Path(path), issued, exclusive=True)
    if counters is not None:
        counters.increment("approval_issue_calls")
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
    if value.get("schema_version") != 2:
        raise ProcessingApprovalError("LEGACY_APPROVAL_NOT_EXECUTABLE")
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
    if value.get("schema_version") == 2 and all(
        name in value for name in ("execution_source_commit", "governance_record_commit", "consumed", "execution_allowed")
    ):
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
            "LEGACY_APPROVAL_NOT_EXECUTABLE",
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


def load_approval_retirement_evidence(
    path: str | Path,
) -> ApprovalRetirementEvidence:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND") from None
    expected = set(ApprovalRetirementEvidence.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != expected:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")
    try:
        evidence = ApprovalRetirementEvidence(**value)  # type: ignore[arg-type]
    except TypeError:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED") from None
    if (
        evidence.schema_version != 1
        or evidence.previous_status != "issued"
        or evidence.status != "retired_before_consumption"
        or not _RETIREMENT_REASON.fullmatch(evidence.reason_code)
        or any(
            not _SHA256.fullmatch(item)
            for item in (
                evidence.before_file_sha256,
                evidence.after_file_sha256,
                evidence.before_checksum,
                evidence.after_checksum,
                evidence.stable_fingerprint,
                evidence.evidence_fingerprint,
            )
        )
        or _timestamp(evidence.retired_at, required=True) is None
        or evidence.evidence_fingerprint
        != approval_retirement_evidence_fingerprint(evidence)
    ):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")
    return evidence


def _approval_contract(record: ApprovalRecord) -> ProcessingRunContract:
    return ProcessingRunContract(
        run_id=record.processing_run_id,
        approval_id=record.approval_id,
        processing_allowed=record.processing_allowed,
        payload_read_allowed=record.payload_read_allowed,
        output_write_allowed=record.output_write_allowed,
        execution_allowed=False,
    )


def retire_approval_file(
    path: str | Path,
    *,
    expected_approval_id: str,
    expected_run_id: str,
    expected_file_sha256: str,
    expected_checksum: str | None = None,
    expected_stable_fingerprint: str | None = None,
    retired_at: str,
    reason_code: str,
    counters: ExecutionCounters | None = None,
) -> ApprovalRecord:
    """Atomically retire one issued, unconsumed Approval artifact.

    The schema-v2 Approval remains exact. Timestamp and reason are recorded in
    a sibling canonical lifecycle evidence file. Existing lock files are never
    broken automatically; manual investigation is required for stale locks.
    """

    del counters  # Retirement must not mutate any execution counter.
    target = Path(path)
    evidence_path = approval_retirement_evidence_path(target)
    runtime_request_path = (
        target.parent.parent
        / "runtime-evidence"
        / expected_approval_id
        / "runtime-execution-request.json"
    )
    approval_temporary = target.with_name(target.name + _RETIREMENT_TEMP_SUFFIX)
    evidence_temporary = target.with_name(target.name + _RETIREMENT_EVIDENCE_TEMP_SUFFIX)
    link_probe = target.with_name(target.name + _RETIREMENT_PROBE_SUFFIX)
    if _approval_platform() not in {"posix", "nt"}:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_UNSUPPORTED")
    if not target.is_file():
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND")
    if runtime_request_path.exists():
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_STATUS_INVALID")
    if not _SHA256.fullmatch(expected_file_sha256):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")
    if expected_checksum is not None and not _SHA256.fullmatch(expected_checksum):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_CHECKSUM_MISMATCH")
    if expected_stable_fingerprint is not None and not _SHA256.fullmatch(
        expected_stable_fingerprint,
    ):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_FINGERPRINT_MISMATCH")
    if not isinstance(reason_code, str) or not _RETIREMENT_REASON.fullmatch(reason_code):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_STATUS_INVALID")
    _timestamp(retired_at, required=True)

    replaced = False
    approval_temporary_owned = False
    evidence_temporary_owned = False
    link_probe_owned = False
    try:
        with _retirement_lock(target):
            before_bytes = target.read_bytes()
            before_sha256 = hashlib.sha256(before_bytes).hexdigest()
            if before_sha256 != expected_file_sha256:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")
            try:
                record = load_approval(target)
            except ProcessingApprovalError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED") from None
            if record.checksum != approval_checksum(record):
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_CHECKSUM_MISMATCH")
            if (
                record.approval_id != expected_approval_id
                or record.processing_run_id != expected_run_id
            ):
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_IDENTITY_MISMATCH")
            if expected_checksum is not None and record.checksum != expected_checksum:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_CHECKSUM_MISMATCH")
            stable_fingerprint = approval_fingerprint(record)
            if (
                expected_stable_fingerprint is not None
                and stable_fingerprint != expected_stable_fingerprint
            ):
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_FINGERPRINT_MISMATCH")
            if record.consumed or record.status in {"consumed", "completed"}:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ALREADY_CONSUMED")
            if record.status != "issued" or record.execution_allowed:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_STATUS_INVALID")
            try:
                validate_approval(record, _approval_contract(record))
            except ProcessingApprovalError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED") from None
            if evidence_path.exists():
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")

            retired = retire_approval(record)
            validate_approval(retired, _approval_contract(retired))
            after_bytes = _canonical_record_bytes(retired)
            after_sha256 = hashlib.sha256(after_bytes).hexdigest()
            evidence = ApprovalRetirementEvidence(
                schema_version=1,
                approval_id=retired.approval_id,
                processing_run_id=retired.processing_run_id,
                previous_status=record.status,
                status=retired.status,
                retired_at=retired_at,
                reason_code=reason_code,
                before_file_sha256=before_sha256,
                after_file_sha256=after_sha256,
                before_checksum=record.checksum,
                after_checksum=retired.checksum,
                stable_fingerprint=stable_fingerprint,
            )
            evidence = replace(
                evidence,
                evidence_fingerprint=approval_retirement_evidence_fingerprint(evidence),
            )
            _write_retirement_temporary(approval_temporary, after_bytes)
            approval_temporary_owned = True
            _write_retirement_temporary(
                evidence_temporary,
                _canonical_json_bytes(evidence),
            )
            evidence_temporary_owned = True
            if link_probe.exists():
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_TEMPORARY_COLLISION")
            try:
                _publish_no_replace(evidence_temporary, link_probe)
                link_probe_owned = True
                link_probe.unlink()
                link_probe_owned = False
            except ProcessingApprovalError as exc:
                if str(exc) == "APPROVAL_NO_REPLACE_UNSUPPORTED":
                    raise ProcessingApprovalError("APPROVAL_RETIREMENT_UNSUPPORTED") from None
                raise ProcessingApprovalError(
                    "APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED",
                ) from None
            except OSError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None
            _retirement_compare_and_swap_hook(target)
            if (
                not target.is_file()
                or target.read_bytes() != before_bytes
                or _file_sha256(target) != before_sha256
                or runtime_request_path.exists()
            ):
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_CHANGED")
            try:
                os.replace(approval_temporary, target)
            except OSError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_ATOMIC_WRITE_FAILED") from None
            replaced = True
            approval_temporary_owned = False
            try:
                _publish_no_replace(evidence_temporary, evidence_path)
                evidence_temporary.unlink()
                evidence_temporary_owned = False
            except ProcessingApprovalError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None
            except OSError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None
            try:
                _sync_parent_directory(target)
            except ProcessingApprovalError:
                raise ProcessingApprovalError(
                    "APPROVAL_RETIREMENT_DIRECTORY_SYNC_FAILED",
                ) from None
            if target.read_bytes() != after_bytes:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE")
            loaded = load_approval(target)
            validate_approval(loaded, _approval_contract(loaded))
            loaded_evidence = load_approval_retirement_evidence(evidence_path)
            if (
                loaded != retired
                or loaded_evidence.after_file_sha256 != _file_sha256(target)
                or approval_fingerprint(loaded) != stable_fingerprint
            ):
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE")
            return loaded
    finally:
        for temporary, owned in (
            (approval_temporary, approval_temporary_owned),
            (evidence_temporary, evidence_temporary_owned),
            (link_probe, link_probe_owned),
        ):
            if owned:
                _cleanup_retirement_temporary(temporary)
        if replaced and target.is_file():
            try:
                current = load_approval(target)
            except ProcessingApprovalError:
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE") from None
            if current.status != "retired_before_consumption":
                raise ProcessingApprovalError("APPROVAL_RETIREMENT_INCOMPLETE")


def consume_approval(
    path: str | Path,
    record: ApprovalRecord,
    *,
    consumed_at: str,
    contract: ProcessingRunContract,
    runtime_request: RuntimeExecutionRequest,
    counters: ExecutionCounters | None = None,
) -> ApprovalRecord:
    target = Path(path)
    with approval_lifecycle_lock(target):
        validate_approval(record, contract)
        if record.status != "issued" or record.consumed:
            raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
        validate_runtime_request(
            runtime_request,
            contract,
            expected_approval_fingerprint=approval_fingerprint(record),
            expected_preflight_evidence_fingerprint=record.preflight_evidence_fingerprint,
            expected_execution_source_commit=record.execution_source_commit,
            expected_governance_record_commit=record.governance_record_commit,
            expected_manifest_sha256=record.manifest_sha256,
            expected_backend_fingerprint=record.backend_fingerprint,
            now=_timestamp(consumed_at, required=True),
        )
        if not target.is_file() or load_approval(target) != record:
            raise ProcessingApprovalError("APPROVAL_ALREADY_CONSUMED")
        consumed = _transition(
            record, {"issued"}, "consumed", consumed_at=consumed_at, consumed=True,
        )
        _atomic_write(target, consumed)
    if counters is not None:
        counters.increment("runtime_execution_gate_activations")
        counters.increment("approval_consume_calls")
    return consumed


def finalize_approval(
    path: str | Path,
    record: ApprovalRecord,
    *,
    success: bool,
    finalized_at: str,
) -> ApprovalRecord:
    target = Path(path)
    with approval_lifecycle_lock(target):
        if not target.is_file() or load_approval(target) != record:
            raise ProcessingApprovalError("APPROVAL_ALREADY_FINALIZED")
        _timestamp(finalized_at, required=True)
        field = {"completed_at": finalized_at} if success else {"failed_at": finalized_at}
        final = _transition(
            record, {"consumed"}, "completed" if success else "failed", **field,
        )
        _atomic_write(target, final)
    return final


def fail_approval(record: ApprovalRecord, *, failed_at: str) -> ApprovalRecord:
    """Create a validated failed lifecycle record without granting execution."""

    _timestamp(failed_at, required=True)
    if record.status not in {"prepared_not_issued", "issued", "consumed"}:
        raise ProcessingApprovalError("APPROVAL_STATE_TRANSITION_INVALID")
    return _transition(record, {record.status}, "failed", failed_at=failed_at)
