"""Fail-closed issuance and persistence for RuntimeExecutionRequest v1."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Callable, Mapping

from src.data.aihub_71748_approval_refresh import (
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
    deserialize_approval_refresh_evidence,
    fingerprints_for_refresh,
    validate_approval_refresh_evidence,
    validate_governance_refresh_checkout,
    validate_previous_preflight_evidence,
)

from .approval import (
    ApprovalRecord,
    approval_fingerprint,
    load_approval,
    validate_approval,
)
from .run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RuntimeExecutionRequest,
    deserialize_runtime_request,
    new_runtime_execution_request,
    runtime_request_fingerprint,
    validate_runtime_request,
)


class RuntimeRequestArtifactError(RuntimeError):
    """Fail-closed request issuance error without payload or local path details."""


RUNTIME_REQUEST_FILENAME = "runtime-execution-request.json"
RUNTIME_REQUEST_TTL = timedelta(hours=1)
_NONCE = re.compile(r"^[A-Za-z0-9_-]{43,}$")
_REQUEST = re.compile(
    r"^AIHUB-71748-SFT-RUNTIME-REQUEST-\d{8}-\d{4}-[0-9a-f]{16}$"
)
_NO_REPLACE_UNSUPPORTED_ERRNOS = frozenset({
    errno.EXDEV,
    errno.EINVAL,
    errno.ENOSYS,
    getattr(errno, "ENOTSUP", errno.ENOSYS),
    getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
})

_INITIAL_OUTER_FIELDS = set(  # canonical Preflight wrapper fields
    (
        "approval_consumed", "approval_draft", "approval_draft_fingerprint",
        "approval_issued", "execution_allowed", "fingerprint",
        "lineage_validation", "output_writes", "payload_reads",
        "processing_calls", "status",
    )
)
_REFRESH_OUTER_FIELDS = set(
    (
        "fingerprint", "approval_draft", "status", "approval_issued",
        "approval_consumed", "runtime_request_created", "payload_reads",
        "processing_calls", "output_writes", "execution_allowed",
    )
)


def canonical_runtime_request_path(processed_root: str | Path, approval_id: str) -> Path:
    return Path(processed_root) / "runtime-evidence" / approval_id / RUNTIME_REQUEST_FILENAME


def _read_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeRequestArtifactError(code) from None
    if not isinstance(value, dict):
        raise RuntimeRequestArtifactError(code)
    return value


def _canonical_bytes(request: RuntimeExecutionRequest) -> bytes:
    try:
        return json.dumps(
            asdict(request), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ATOMIC_WRITE_FAILED") from None


def _directory_fsync_supported() -> bool:
    return os.name != "nt"


def _sync_parent_directory(path: Path) -> None:
    if not _directory_fsync_supported():
        return
    descriptor = -1
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_DIRECTORY_SYNC_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_no_replace(temporary: Path, final: Path) -> None:
    if os.name not in {"nt", "posix"}:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NO_REPLACE_UNSUPPORTED")
    try:
        os.link(temporary, final)
    except FileExistsError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ALREADY_EXISTS") from None
    except OSError as exc:
        if exc.errno in _NO_REPLACE_UNSUPPORTED_ERRNOS or getattr(exc, "winerror", None) in {1, 50}:
            raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NO_REPLACE_UNSUPPORTED") from None
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ATOMIC_WRITE_FAILED") from None


def _write_runtime_request(path: Path, request: RuntimeExecutionRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if path.exists():
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ALREADY_EXISTS")
    payload = _canonical_bytes(request)
    descriptor = -1
    published = False
    try:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RuntimeRequestArtifactError("RUNTIME_REQUEST_TEMPORARY_COLLISION") from None
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            if stream.write(payload) != len(payload):
                raise OSError("short write")
            stream.flush()
            os.fsync(stream.fileno())
        _publish_no_replace(temporary, path)
        published = True
        try:
            temporary.unlink()
        except OSError:
            raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ISSUANCE_INCOMPLETE") from None
        _sync_parent_directory(path)
    except RuntimeRequestArtifactError:
        raise
    except (OSError, ValueError):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ATOMIC_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ISSUANCE_INCOMPLETE") from None


def load_runtime_execution_request(path: str | Path) -> RuntimeExecutionRequest:
    value = _read_json(Path(path), "RUNTIME_REQUEST_SCHEMA_INVALID")
    try:
        return deserialize_runtime_request(value)
    except RuntimeError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_SCHEMA_INVALID") from None


def validate_runtime_execution_request_artifact(
    path: str | Path,
    contract: ProcessingRunContract,
    *,
    expected_approval_fingerprint: str,
    expected_refresh_fingerprint: str,
    expected_execution_source_commit: str,
    expected_governance_record_commit: str,
    expected_manifest_sha256: str,
    expected_backend_fingerprint: str,
    now: datetime | None = None,
    used_fingerprints: set[str] | None = None,
) -> RuntimeExecutionRequest:
    target = Path(path)
    request = load_runtime_execution_request(target)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_STALE")
    try:
        validate_runtime_request(
            request,
            contract,
            expected_approval_fingerprint=expected_approval_fingerprint,
            expected_preflight_evidence_fingerprint=expected_refresh_fingerprint,
            expected_execution_source_commit=expected_execution_source_commit,
            expected_governance_record_commit=expected_governance_record_commit,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_backend_fingerprint=expected_backend_fingerprint,
            now=current,
            used_fingerprints=used_fingerprints,
        )
    except RuntimeError as exc:
        raise RuntimeRequestArtifactError(str(exc)) from None
    if target.read_bytes() != _canonical_bytes(request):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_SCHEMA_INVALID")
    if not _REQUEST.fullmatch(request.request_id):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ID_REQUIRED")
    if not _NONCE.fullmatch(request.nonce):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NONCE_INVALID")
    issued = datetime.fromisoformat(request.requested_at)
    expires = datetime.fromisoformat(request.expires_at)
    if issued > current or expires != issued + RUNTIME_REQUEST_TTL or current > expires:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_STALE")
    return request


def validate_runtime_execution_request(
    path: str | Path,
    contract: ProcessingRunContract,
    **expected: object,
) -> RuntimeExecutionRequest:
    """Public artifact validator paired with the existing in-memory validator."""

    return validate_runtime_execution_request_artifact(path, contract, **expected)  # type: ignore[arg-type]


def _validate_initial_evidence(
    value: Mapping[str, object],
    *,
    fingerprint: str,
    contract: ProcessingRunContract,
    execution_source_commit: str,
) -> None:
    from src.data.aihub_71748_processing_preflight import PreflightEvidence

    if set(value) != set(PreflightEvidence.__dataclass_fields__) | _INITIAL_OUTER_FIELDS:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_PREFLIGHT_FINGERPRINT_MISMATCH")
    try:
        validate_previous_preflight_evidence(
            value,
            expected_fingerprint=fingerprint,
            run_id=contract.run_id,
            approval_id=contract.approval_id,
            execution_source_commit=execution_source_commit,
        )
    except RuntimeError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_PREFLIGHT_FINGERPRINT_MISMATCH") from None


def _validate_refresh_evidence(
    value: Mapping[str, object],
    *,
    fingerprint: str,
    initial_fingerprint: str,
    approval: ApprovalRecord,
    contract: ProcessingRunContract,
) -> None:
    fields = set(ApprovalRefreshEvidence.__dataclass_fields__)
    if set(value) != fields | _REFRESH_OUTER_FIELDS:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH")
    if value.get("fingerprint") != fingerprint:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH")
    try:
        evidence = deserialize_approval_refresh_evidence({key: value[key] for key in fields})
        generated = datetime.fromisoformat(evidence.generated_at)
        validate_approval_refresh_evidence(
            evidence,
            expected_fingerprint=fingerprint,
            expected_run_id=contract.run_id,
            expected_approval_id=contract.approval_id,
            expected_execution_source_commit=approval.execution_source_commit,
            expected_governance_record_commit=approval.governance_record_commit,
            expected_manifest_sha256=approval.manifest_sha256,
            expected_backend_fingerprint=approval.backend_fingerprint,
            expected_previous_preflight_fingerprint=initial_fingerprint,
            now=generated,
        )
    except (RuntimeError, ValueError):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH") from None
    if approval_refresh_evidence_fingerprint(evidence) != fingerprint:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH")
    # Refresh freshness was consumed by Approval issuance. Runtime issuance creates
    # a new one-hour authorization window while preserving this immutable lineage.


def _request_id(run_id: str, nonce: str) -> str:
    try:
        date, sequence = run_id.rsplit("-", 2)[-2:]
    except ValueError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ID_REQUIRED") from None
    suffix = hashlib.sha256(nonce.encode("ascii")).hexdigest()[:16]
    value = f"AIHUB-71748-SFT-RUNTIME-REQUEST-{date}-{sequence}-{suffix}"
    if not _REQUEST.fullmatch(value):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ID_REQUIRED")
    return value


def _existing_request_identities(processed_root: Path) -> tuple[set[str], set[str]]:
    request_ids: set[str] = set()
    nonces: set[str] = set()
    evidence_root = processed_root / "runtime-evidence"
    if not evidence_root.exists():
        return request_ids, nonces
    for path in evidence_root.glob(f"*/{RUNTIME_REQUEST_FILENAME}"):
        request = load_runtime_execution_request(path)
        request_ids.add(request.request_id)
        nonces.add(request.nonce)
    return request_ids, nonces


def validate_runtime_execution_request_issuance(
    *,
    repository_root: str | Path,
    processed_root: str | Path,
    contract: ProcessingRunContract,
    approval_path: str | Path,
    initial_evidence_path: str | Path,
    refresh_evidence_path: str | Path,
    initial_evidence_fingerprint: str,
    refresh_evidence_fingerprint: str,
    lineage_validator: Callable[..., object] | None = None,
) -> ApprovalRecord:
    processed = Path(processed_root).resolve()
    if not contract.synthetic:
        canonical_paths = (
            processed / "approvals" / f"{contract.approval_id}.json",
            processed / "runtime-evidence" / contract.run_id / "preflight-evidence.json",
            processed / "runtime-evidence" / contract.run_id / "approval-refresh-evidence.json",
        )
        supplied_paths = tuple(
            Path(path).resolve()
            for path in (approval_path, initial_evidence_path, refresh_evidence_path)
        )
        if supplied_paths != canonical_paths:
            raise RuntimeRequestArtifactError("RUNTIME_REQUEST_SCHEMA_INVALID")
    try:
        approval = load_approval(approval_path)
    except RuntimeError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_NOT_ISSUED") from None
    if approval.consumed:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_ALREADY_CONSUMED")
    if approval.execution_allowed:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_EXECUTION_FLAG_REQUIRED")
    if approval.status != "issued":
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_NOT_ISSUED")
    try:
        validate_approval(approval, contract)
    except RuntimeError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_FINGERPRINT_MISMATCH") from None
    if approval.preflight_evidence_fingerprint != refresh_evidence_fingerprint:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH")
    initial = _read_json(Path(initial_evidence_path), "RUNTIME_REQUEST_PREFLIGHT_FINGERPRINT_MISMATCH")
    refresh = _read_json(Path(refresh_evidence_path), "RUNTIME_REQUEST_REFRESH_FINGERPRINT_MISMATCH")
    _validate_initial_evidence(
        initial,
        fingerprint=initial_evidence_fingerprint,
        contract=contract,
        execution_source_commit=approval.execution_source_commit,
    )
    _validate_refresh_evidence(
        refresh,
        fingerprint=refresh_evidence_fingerprint,
        initial_fingerprint=initial_evidence_fingerprint,
        approval=approval,
        contract=contract,
    )
    validator = lineage_validator or validate_governance_refresh_checkout
    if lineage_validator is not None and not contract.synthetic:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH")
    try:
        lineage = validator(
            repository_root,
            execution_source_commit=approval.execution_source_commit,
            governance_record_commit=approval.governance_record_commit,
        )
        if not getattr(lineage, "valid") or not getattr(lineage, "execution_surface_blobs_equal"):
            raise RuntimeError
        if lineage_validator is None and fingerprints_for_refresh(
            repository_root,
            approval.execution_source_commit,
            approval.governance_record_commit,
        ) != (approval.manifest_sha256, approval.backend_fingerprint):
            raise RuntimeError
    except RuntimeError:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH") from None
    collisions = (
        processed / contract.run_id,
        processed / f"{contract.run_id}.staging",
        processed / f"{contract.run_id}.failed",
        processed / "quarantine" / contract.run_id,
    )
    if any(path.exists() for path in collisions):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ALREADY_EXISTS")
    return approval


def issue_runtime_execution_request(
    *,
    repository_root: str | Path,
    processed_root: str | Path,
    contract: ProcessingRunContract,
    approval_path: str | Path,
    initial_evidence_path: str | Path,
    refresh_evidence_path: str | Path,
    initial_evidence_fingerprint: str,
    refresh_evidence_fingerprint: str,
    requested_by: str,
    now: datetime | None = None,
    counters: ExecutionCounters | None = None,
    nonce: str | None = None,
    lineage_validator: Callable[..., object] | None = None,
) -> tuple[Path, RuntimeExecutionRequest]:
    if not isinstance(requested_by, str) or not requested_by.strip():
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_SCHEMA_INVALID")
    if now is not None and not contract.synthetic:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_STALE")
    approval = validate_runtime_execution_request_issuance(
        repository_root=repository_root,
        processed_root=processed_root,
        contract=contract,
        approval_path=approval_path,
        initial_evidence_path=initial_evidence_path,
        refresh_evidence_path=refresh_evidence_path,
        initial_evidence_fingerprint=initial_evidence_fingerprint,
        refresh_evidence_fingerprint=refresh_evidence_fingerprint,
        lineage_validator=lineage_validator,
    )
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_STALE")
    if nonce is not None and not contract.synthetic:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NONCE_INVALID")
    request_nonce = nonce or secrets.token_urlsafe(32)
    if not _NONCE.fullmatch(request_nonce):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NONCE_INVALID")
    request_id = _request_id(contract.run_id, request_nonce)
    request_ids, nonces = _existing_request_identities(Path(processed_root))
    if request_id in request_ids:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ID_ALREADY_USED")
    if request_nonce in nonces:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_NONCE_REUSED")
    target = canonical_runtime_request_path(processed_root, contract.approval_id)
    if target.exists():
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_ALREADY_EXISTS")
    try:
        request = new_runtime_execution_request(
            contract,
            request_id=request_id,
            approval_fingerprint=approval_fingerprint(approval),
            preflight_evidence_fingerprint=refresh_evidence_fingerprint,
            execution_source_commit=approval.execution_source_commit,
            governance_record_commit=approval.governance_record_commit,
            manifest_sha256=approval.manifest_sha256,
            backend_fingerprint=approval.backend_fingerprint,
            requested_by=requested_by.strip(),
            requested_at=current.isoformat(),
            expires_at=(current + RUNTIME_REQUEST_TTL).isoformat(),
            nonce=request_nonce,
        )
        validate_runtime_request(
            request,
            contract,
            expected_approval_fingerprint=approval_fingerprint(approval),
            expected_preflight_evidence_fingerprint=refresh_evidence_fingerprint,
            expected_execution_source_commit=approval.execution_source_commit,
            expected_governance_record_commit=approval.governance_record_commit,
            expected_manifest_sha256=approval.manifest_sha256,
            expected_backend_fingerprint=approval.backend_fingerprint,
            now=current,
        )
    except RuntimeError as exc:
        raise RuntimeRequestArtifactError(str(exc)) from None
    approval_before = Path(approval_path).read_bytes()
    _write_runtime_request(target, request)
    if Path(approval_path).read_bytes() != approval_before:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_FINGERPRINT_MISMATCH")
    if counters is not None:
        counters.increment("runtime_request_creations")
    validated = validate_runtime_execution_request_artifact(
        target,
        contract,
        expected_approval_fingerprint=approval_fingerprint(approval),
        expected_refresh_fingerprint=refresh_evidence_fingerprint,
        expected_execution_source_commit=approval.execution_source_commit,
        expected_governance_record_commit=approval.governance_record_commit,
        expected_manifest_sha256=approval.manifest_sha256,
        expected_backend_fingerprint=approval.backend_fingerprint,
        now=current,
    )
    return target, validated


def runtime_request_integrity_checksum(request: RuntimeExecutionRequest) -> str:
    """Return the v1 deterministic fingerprint used as its integrity checksum."""

    return runtime_request_fingerprint(request)
