"""Synthetic-only V0.3 Tokenization Approval v1 and immutable lifecycle.

Approval issuance does not reserve or commit a Run and never grants execution
by itself.  Consumption is an explicit gate intended for the instant before
payload access; this module performs no payload, tokenizer, GPU, or network I/O.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_lifecycle_lock,
)
from src.data.v03_evidence import V03EvidenceBundleResult
from src.training.v03_run_identity import (
    V03ReservationResult,
    V03RunIdentityError,
    parse_v03_tokenization_run_id,
    validate_v03_ledger_entry,
    validate_v03_reservation,
)


class V03TokenizationApprovalError(RuntimeError):
    """Fail-closed error whose message contains only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


APPROVAL_INVALID = "V03_APPROVAL_INVALID"
APPROVAL_EXISTS = "V03_APPROVAL_ALREADY_EXISTS"
APPROVAL_NOT_ISSUABLE = "V03_APPROVAL_NOT_ISSUABLE"
APPROVAL_EXPIRED = "V03_APPROVAL_EXPIRED"
APPROVAL_RETIRED = "V03_APPROVAL_RETIRED"
APPROVAL_CONSUMED = "V03_APPROVAL_ALREADY_CONSUMED"
APPROVAL_INCONSISTENT = "V03_APPROVAL_STATE_INCONSISTENT"
APPROVAL_CHECKSUM = "V03_APPROVAL_CHECKSUM_MISMATCH"
APPROVAL_RESERVATION = "V03_APPROVAL_RESERVATION_MISMATCH"
REQUEST_APPROVAL = "V03_REQUEST_APPROVAL_MISMATCH"
REQUEST_REPLAY = "V03_REQUEST_REPLAY_DETECTED"
LIFECYCLE_LOCK_FAILED = "V03_LIFECYCLE_LOCK_FAILED"

SCHEMA_VERSION = 1
APPROVAL_TYPE = "v03_fresh_tokenization"
ALLOWED_ACTION = "tokenize_and_publish"
APPROVAL_STATUSES = frozenset({"draft", "issued", "consumed", "retired", "expired"})
RETIREMENT_REASONS = frozenset(
    {
        "source_commit_drift",
        "backend_fingerprint_drift",
        "dependency_fingerprint_drift",
        "tokenizer_inventory_drift",
        "chat_template_drift",
        "evidence_bundle_replaced",
        "reservation_retired",
        "runtime_request_governance_mismatch",
        "user_revoked",
        "expired_before_consumption",
    }
)

_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,255}$")
_LOGICAL_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:-]{2,255}$")
_NO_REPLACE_ERRNOS = frozenset(
    {
        errno.EXDEV,
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.ENOSYS),
        getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
    }
)


@dataclass(frozen=True)
class V03ApprovalEvidenceDecision:
    schema_version: int
    dataset_id: str
    canonical_dataset_fingerprint: str
    effective_dataset_fingerprint: str
    evidence_bundle_fingerprint: str
    tokenization_config_fingerprint: str
    tokenizer_identity: str
    tokenizer_inventory_fingerprint: str
    chat_template_fingerprint: str
    backend_fingerprint: str
    dependency_fingerprint: str
    source_commit: str
    expected_artifact_set_fingerprint: str
    overall_decision: str
    license_decision: str
    unresolved_pii: int
    unresolved_safety: int
    unresolved_leakage: int
    approval_issue_allowed: bool
    decision_fingerprint: str


@dataclass(frozen=True)
class V03TokenizationApproval:
    schema_version: int
    approval_id: str
    approval_type: str
    run_id: str
    reservation_id: str
    dataset_id: str
    canonical_dataset_fingerprint: str
    effective_dataset_fingerprint: str
    evidence_bundle_fingerprint: str
    tokenization_config_fingerprint: str
    tokenizer_identity: str
    tokenizer_inventory_fingerprint: str
    chat_template_fingerprint: str
    backend_fingerprint: str
    dependency_fingerprint: str
    source_commit: str
    allowed_action: str
    allowed_input_root_id: str
    allowed_output_root_id: str
    expected_artifact_set_fingerprint: str
    predecessor_run_id: str | None
    issued_at: str | None
    expires_at: str
    consumed_at: str | None
    retired_at: str | None
    status: str
    approver_id: str
    issue_nonce: str | None
    approval_fingerprint: str
    approval_checksum: str
    retirement_reason: str | None


V03TokenizationApprovalDraft = V03TokenizationApproval


@dataclass(frozen=True)
class V03ApprovalLifecycleTransition:
    schema_version: int
    transition_id: str
    approval_id: str
    run_id: str
    request_id: str | None
    previous_status: str
    status: str
    occurred_at: str
    reason_code: str | None
    evidence_fingerprint: str
    request_fingerprint: str | None
    anti_replay_token_hash: str | None
    approval_fingerprint: str
    transition_fingerprint: str
    transition_checksum: str


@dataclass(frozen=True)
class V03ApprovalLifecycleState:
    approval_id: str
    run_id: str
    status: str
    request_id: str | None
    effective_at: str
    reason_code: str | None
    approval_fingerprint: str


@dataclass(frozen=True)
class V03ApprovalConsumptionResult:
    approval: V03TokenizationApproval
    transition: V03ApprovalLifecycleTransition
    lifecycle_state: V03ApprovalLifecycleState


def _fail(code: str) -> None:
    raise V03TokenizationApprovalError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        _fail(APPROVAL_INVALID)


def _fingerprint(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _without(value: object, *fields: str) -> dict[str, object]:
    result = asdict(value)  # type: ignore[arg-type]
    for field in fields:
        result.pop(field)
    return result


def _format_timestamp(value: datetime, code: str = APPROVAL_INVALID) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _fail(code)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: object, code: str = APPROVAL_INVALID) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail(code)
    return parsed.astimezone(timezone.utc)


def _require_identifier(value: object, code: str = APPROVAL_INVALID) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(code)
    return value


def _require_logical_identity(value: object, code: str = APPROVAL_INVALID) -> str:
    if type(value) is not str or _LOGICAL_IDENTITY.fullmatch(value) is None:
        _fail(code)
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or "\\" in value
    ):
        _fail(code)
    return value


def _require_hash(value: object, code: str = APPROVAL_INVALID) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail(code)
    return value


def _require_git_sha(value: object, code: str = APPROVAL_INVALID) -> str:
    if type(value) is not str or _HEX40.fullmatch(value) is None:
        _fail(code)
    return value


def _approval_fingerprint_payload(value: V03TokenizationApproval) -> dict[str, object]:
    return _without(
        value,
        "status",
        "consumed_at",
        "retired_at",
        "retirement_reason",
        "approval_fingerprint",
        "approval_checksum",
    )


def _validate_evidence_decision(value: V03ApprovalEvidenceDecision) -> None:
    if type(value.schema_version) is not int or value.schema_version != SCHEMA_VERSION:
        _fail(APPROVAL_NOT_ISSUABLE)
    _require_identifier(value.dataset_id, APPROVAL_NOT_ISSUABLE)
    for item in (
        value.canonical_dataset_fingerprint,
        value.effective_dataset_fingerprint,
        value.evidence_bundle_fingerprint,
        value.tokenization_config_fingerprint,
        value.tokenizer_inventory_fingerprint,
        value.chat_template_fingerprint,
        value.backend_fingerprint,
        value.dependency_fingerprint,
        value.expected_artifact_set_fingerprint,
        value.decision_fingerprint,
    ):
        _require_hash(item, APPROVAL_NOT_ISSUABLE)
    _require_logical_identity(value.tokenizer_identity, APPROVAL_NOT_ISSUABLE)
    _require_git_sha(value.source_commit, APPROVAL_NOT_ISSUABLE)
    if value.overall_decision not in {"ready", "ready_with_conditions"}:
        _fail(APPROVAL_NOT_ISSUABLE)
    if value.license_decision not in {"ready", "ready_with_conditions"}:
        _fail(APPROVAL_NOT_ISSUABLE)
    counts = (value.unresolved_pii, value.unresolved_safety, value.unresolved_leakage)
    if any(type(item) is not int or item != 0 for item in counts):
        _fail(APPROVAL_NOT_ISSUABLE)
    if (
        type(value.approval_issue_allowed) is not bool
        or not value.approval_issue_allowed
    ):
        _fail(APPROVAL_NOT_ISSUABLE)
    if value.decision_fingerprint != _fingerprint(
        _without(value, "decision_fingerprint")
    ):
        _fail(APPROVAL_NOT_ISSUABLE)


def make_v03_approval_evidence_decision(
    *,
    bundle_result: V03EvidenceBundleResult,
    canonical_dataset_fingerprint: str,
    effective_dataset_fingerprint: str,
    tokenization_config_fingerprint: str,
    tokenizer_identity: str,
    tokenizer_inventory_fingerprint: str,
    chat_template_fingerprint: str,
    backend_fingerprint: str,
    dependency_fingerprint: str,
    source_commit: str,
    expected_artifact_set_fingerprint: str,
    license_decision: str,
    unresolved_pii: int,
    unresolved_safety: int,
    unresolved_leakage: int,
    approval_issue_allowed: bool,
) -> V03ApprovalEvidenceDecision:
    if not isinstance(bundle_result, V03EvidenceBundleResult):
        _fail(APPROVAL_NOT_ISSUABLE)
    value = V03ApprovalEvidenceDecision(
        schema_version=SCHEMA_VERSION,
        dataset_id=bundle_result.dataset_id,
        canonical_dataset_fingerprint=canonical_dataset_fingerprint,
        effective_dataset_fingerprint=effective_dataset_fingerprint,
        evidence_bundle_fingerprint=bundle_result.evidence_bundle_fingerprint,
        tokenization_config_fingerprint=tokenization_config_fingerprint,
        tokenizer_identity=tokenizer_identity,
        tokenizer_inventory_fingerprint=tokenizer_inventory_fingerprint,
        chat_template_fingerprint=chat_template_fingerprint,
        backend_fingerprint=backend_fingerprint,
        dependency_fingerprint=dependency_fingerprint,
        source_commit=source_commit,
        expected_artifact_set_fingerprint=expected_artifact_set_fingerprint,
        overall_decision=bundle_result.overall_decision,
        license_decision=license_decision,
        unresolved_pii=unresolved_pii,
        unresolved_safety=unresolved_safety,
        unresolved_leakage=unresolved_leakage,
        approval_issue_allowed=approval_issue_allowed,
        decision_fingerprint="",
    )
    value = replace(
        value,
        decision_fingerprint=_fingerprint(_without(value, "decision_fingerprint")),
    )
    _validate_evidence_decision(value)
    return value


def validate_v03_tokenization_approval(
    value: V03TokenizationApproval,
) -> V03TokenizationApproval:
    if not isinstance(value, V03TokenizationApproval):
        _fail(APPROVAL_INVALID)
    if type(value.schema_version) is not int or value.schema_version != SCHEMA_VERSION:
        _fail(APPROVAL_INVALID)
    if value.approval_type != APPROVAL_TYPE or value.allowed_action != ALLOWED_ACTION:
        _fail(APPROVAL_INVALID)
    if value.status not in APPROVAL_STATUSES:
        _fail(APPROVAL_INVALID)
    _require_identifier(value.approval_id)
    _require_identifier(value.reservation_id)
    _require_identifier(value.dataset_id)
    _require_identifier(value.approver_id)
    try:
        parse_v03_tokenization_run_id(value.run_id)
        if value.predecessor_run_id is not None:
            parse_v03_tokenization_run_id(value.predecessor_run_id)
            if value.predecessor_run_id == value.run_id:
                _fail(APPROVAL_INVALID)
    except V03RunIdentityError:
        _fail(APPROVAL_INVALID)
    for item in (
        value.canonical_dataset_fingerprint,
        value.effective_dataset_fingerprint,
        value.evidence_bundle_fingerprint,
        value.tokenization_config_fingerprint,
        value.tokenizer_inventory_fingerprint,
        value.chat_template_fingerprint,
        value.backend_fingerprint,
        value.dependency_fingerprint,
        value.expected_artifact_set_fingerprint,
    ):
        _require_hash(item)
    _require_logical_identity(value.tokenizer_identity)
    _require_logical_identity(value.allowed_input_root_id)
    _require_logical_identity(value.allowed_output_root_id)
    if value.allowed_input_root_id == value.allowed_output_root_id:
        _fail(APPROVAL_INVALID)
    _require_git_sha(value.source_commit)
    expires_at = _parse_timestamp(value.expires_at)
    issued_at = (
        _parse_timestamp(value.issued_at) if value.issued_at is not None else None
    )
    consumed_at = (
        _parse_timestamp(value.consumed_at) if value.consumed_at is not None else None
    )
    retired_at = (
        _parse_timestamp(value.retired_at) if value.retired_at is not None else None
    )
    if issued_at is not None and expires_at <= issued_at:
        _fail(APPROVAL_INVALID)
    if value.status == "draft":
        if any(
            item is not None
            for item in (
                value.issued_at,
                value.consumed_at,
                value.retired_at,
                value.issue_nonce,
                value.retirement_reason,
            )
        ):
            _fail(APPROVAL_INVALID)
    elif value.status == "issued":
        if (
            issued_at is None
            or value.issue_nonce is None
            or any(
                item is not None
                for item in (
                    value.consumed_at,
                    value.retired_at,
                    value.retirement_reason,
                )
            )
        ):
            _fail(APPROVAL_INVALID)
    elif value.status == "consumed":
        if issued_at is None or consumed_at is None or value.issue_nonce is None:
            _fail(APPROVAL_INVALID)
        if retired_at is not None or value.retirement_reason is not None:
            _fail(APPROVAL_INVALID)
    elif value.status == "retired":
        if (
            issued_at is None
            or retired_at is None
            or value.issue_nonce is None
            or value.retirement_reason not in RETIREMENT_REASONS
            or consumed_at is not None
        ):
            _fail(APPROVAL_INVALID)
    else:
        if (
            issued_at is None
            or retired_at is not None
            or value.issue_nonce is None
            or value.retirement_reason != "expired_before_consumption"
            or consumed_at is not None
        ):
            _fail(APPROVAL_INVALID)
    if value.issue_nonce is not None and _NONCE.fullmatch(value.issue_nonce) is None:
        _fail(APPROVAL_INVALID)
    if consumed_at is not None and (
        issued_at is None or consumed_at < issued_at or consumed_at > expires_at
    ):
        _fail(APPROVAL_INVALID)
    if retired_at is not None and issued_at is not None and retired_at < issued_at:
        _fail(APPROVAL_INVALID)
    if value.approval_fingerprint != _fingerprint(_approval_fingerprint_payload(value)):
        _fail(APPROVAL_CHECKSUM)
    if value.approval_checksum != _fingerprint(_without(value, "approval_checksum")):
        _fail(APPROVAL_CHECKSUM)
    return value


def _seal_approval(value: V03TokenizationApproval) -> V03TokenizationApproval:
    value = replace(value, approval_fingerprint="", approval_checksum="")
    value = replace(
        value,
        approval_fingerprint=_fingerprint(_approval_fingerprint_payload(value)),
    )
    value = replace(
        value,
        approval_checksum=_fingerprint(_without(value, "approval_checksum")),
    )
    return validate_v03_tokenization_approval(value)


def new_v03_tokenization_approval_draft(
    *,
    approval_id: str,
    run_id: str,
    reservation_id: str,
    dataset_id: str,
    canonical_dataset_fingerprint: str,
    effective_dataset_fingerprint: str,
    evidence_bundle_fingerprint: str,
    tokenization_config_fingerprint: str,
    tokenizer_identity: str,
    tokenizer_inventory_fingerprint: str,
    chat_template_fingerprint: str,
    backend_fingerprint: str,
    dependency_fingerprint: str,
    source_commit: str,
    allowed_input_root_id: str,
    allowed_output_root_id: str,
    expected_artifact_set_fingerprint: str,
    predecessor_run_id: str | None,
    expires_at: datetime,
    approver_id: str,
) -> V03TokenizationApprovalDraft:
    return _seal_approval(
        V03TokenizationApproval(
            schema_version=SCHEMA_VERSION,
            approval_id=approval_id,
            approval_type=APPROVAL_TYPE,
            run_id=run_id,
            reservation_id=reservation_id,
            dataset_id=dataset_id,
            canonical_dataset_fingerprint=canonical_dataset_fingerprint,
            effective_dataset_fingerprint=effective_dataset_fingerprint,
            evidence_bundle_fingerprint=evidence_bundle_fingerprint,
            tokenization_config_fingerprint=tokenization_config_fingerprint,
            tokenizer_identity=tokenizer_identity,
            tokenizer_inventory_fingerprint=tokenizer_inventory_fingerprint,
            chat_template_fingerprint=chat_template_fingerprint,
            backend_fingerprint=backend_fingerprint,
            dependency_fingerprint=dependency_fingerprint,
            source_commit=source_commit,
            allowed_action=ALLOWED_ACTION,
            allowed_input_root_id=allowed_input_root_id,
            allowed_output_root_id=allowed_output_root_id,
            expected_artifact_set_fingerprint=expected_artifact_set_fingerprint,
            predecessor_run_id=predecessor_run_id,
            issued_at=None,
            expires_at=_format_timestamp(expires_at),
            consumed_at=None,
            retired_at=None,
            status="draft",
            approver_id=approver_id,
            issue_nonce=None,
            approval_fingerprint="",
            approval_checksum="",
            retirement_reason=None,
        )
    )


def serialize_v03_tokenization_approval(value: V03TokenizationApproval) -> bytes:
    validated = validate_v03_tokenization_approval(value)
    return _canonical(asdict(validated))


def _reject_duplicate_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            _fail(APPROVAL_INVALID)
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail(APPROVAL_INVALID)


def deserialize_v03_tokenization_approval(
    value: Mapping[str, object],
) -> V03TokenizationApproval:
    fields = set(V03TokenizationApproval.__dataclass_fields__)
    if type(value) is not dict or set(value) != fields:
        _fail(APPROVAL_INVALID)
    try:
        approval = V03TokenizationApproval(**value)  # type: ignore[arg-type]
    except TypeError:
        _fail(APPROVAL_INVALID)
    return validate_v03_tokenization_approval(approval)


def load_v03_tokenization_approval(path: Path) -> V03TokenizationApproval:
    if not isinstance(path, Path):
        _fail(APPROVAL_INVALID)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            _fail(APPROVAL_INVALID)
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except V03TokenizationApprovalError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        _fail(APPROVAL_INVALID)
    approval = deserialize_v03_tokenization_approval(value)
    if payload != serialize_v03_tokenization_approval(approval):
        _fail(APPROVAL_INVALID)
    if path.name != f"{approval.approval_id}.json":
        _fail(APPROVAL_INVALID)
    return approval


def _validate_explicit_destination(path: Path, expected_name: str, code: str) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name != expected_name
    ):
        _fail(code)
    try:
        if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
            _fail(code)
        parent = path.parent.resolve(strict=True)
        if path.resolve(strict=False).parent != parent:
            _fail(code)
    except V03TokenizationApprovalError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail(code)
    return path.parent


def _sync_parent_directory(path: Path, code: str) -> None:
    if os.name == "nt":
        return
    descriptor = -1
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        _fail(code)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_write_bytes(
    destination: Path,
    payload: bytes,
    *,
    exists_code: str,
    invalid_code: str,
) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    if destination.exists():
        _fail(exists_code)
    if temporary.exists() or temporary.is_symlink():
        _fail(invalid_code)
    descriptor = -1
    temporary_owned = False
    published = False
    try:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            temporary_owned = True
        except FileExistsError:
            _fail(invalid_code)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            if stream.write(payload) != len(payload):
                raise OSError
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _fail(exists_code)
        except OSError as error:
            if error.errno in _NO_REPLACE_ERRNOS or getattr(
                error, "winerror", None
            ) in {1, 50}:
                _fail(invalid_code)
            _fail(invalid_code)
        published = True
        try:
            temporary.unlink()
            temporary_owned = False
        except OSError:
            _fail(invalid_code)
        _sync_parent_directory(destination, invalid_code)
    except V03TokenizationApprovalError:
        raise
    except (OSError, ValueError):
        _fail(invalid_code)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_owned:
            try:
                temporary.unlink()
            except OSError:
                if not published:
                    _fail(invalid_code)


@contextmanager
def _lifecycle_lock(path: Path) -> Iterator[None]:
    try:
        with approval_lifecycle_lock(path):
            yield
    except V03TokenizationApprovalError:
        raise
    except (ProcessingApprovalError, OSError):
        _fail(LIFECYCLE_LOCK_FAILED)


def _validate_reservation_result(
    result: V03ReservationResult,
    *,
    run_id: str,
    reservation_id: str,
    dataset_id: str,
    canonical_dataset_fingerprint: str,
    source_commit: str,
    predecessor_run_id: str | None,
) -> None:
    if not isinstance(result, V03ReservationResult):
        _fail(APPROVAL_RESERVATION)
    try:
        validate_v03_reservation(result.reservation)
        validate_v03_ledger_entry(result.ledger_entry)
    except V03RunIdentityError:
        _fail(APPROVAL_RESERVATION)
    reservation = result.reservation
    entry = result.ledger_entry
    if (
        reservation.status != "active"
        or entry.status != "reserved"
        or entry.run_kind != "canonical_execution"
        or reservation.run_id != run_id
        or entry.run_id != run_id
        or reservation.reservation_id != reservation_id
        or entry.reservation_id != reservation_id
        or reservation.dataset_id != dataset_id
        or entry.dataset_id != dataset_id
        or reservation.dataset_fingerprint != canonical_dataset_fingerprint
        or entry.dataset_fingerprint != canonical_dataset_fingerprint
        or reservation.source_commit != source_commit
        or entry.source_commit != source_commit
        or reservation.predecessor_run_id != predecessor_run_id
        or entry.predecessor_run_id != predecessor_run_id
        or entry.reservation_checksum != reservation.reservation_checksum
        or _HASH.fullmatch(result.ledger_fingerprint) is None
    ):
        _fail(APPROVAL_RESERVATION)


def _decision_matches_draft(
    decision: V03ApprovalEvidenceDecision,
    draft: V03TokenizationApproval,
) -> bool:
    pairs = (
        (decision.dataset_id, draft.dataset_id),
        (decision.canonical_dataset_fingerprint, draft.canonical_dataset_fingerprint),
        (decision.effective_dataset_fingerprint, draft.effective_dataset_fingerprint),
        (decision.evidence_bundle_fingerprint, draft.evidence_bundle_fingerprint),
        (
            decision.tokenization_config_fingerprint,
            draft.tokenization_config_fingerprint,
        ),
        (decision.tokenizer_identity, draft.tokenizer_identity),
        (
            decision.tokenizer_inventory_fingerprint,
            draft.tokenizer_inventory_fingerprint,
        ),
        (decision.chat_template_fingerprint, draft.chat_template_fingerprint),
        (decision.backend_fingerprint, draft.backend_fingerprint),
        (decision.dependency_fingerprint, draft.dependency_fingerprint),
        (decision.source_commit, draft.source_commit),
        (
            decision.expected_artifact_set_fingerprint,
            draft.expected_artifact_set_fingerprint,
        ),
    )
    return all(left == right for left, right in pairs)


def issue_v03_tokenization_approval(
    *,
    destination: Path,
    draft: V03TokenizationApprovalDraft,
    reservation: V03ReservationResult,
    evidence_decision: V03ApprovalEvidenceDecision,
    issued_at: datetime,
    issue_nonce: str | None = None,
    used_approval_ids: frozenset[str] = frozenset(),
    used_issue_nonces: frozenset[str] = frozenset(),
) -> V03TokenizationApproval:
    validate_v03_tokenization_approval(draft)
    if draft.status != "draft":
        _fail(APPROVAL_NOT_ISSUABLE)
    parent = _validate_explicit_destination(
        destination, f"{draft.approval_id}.json", APPROVAL_INVALID
    )
    del parent
    current = _format_timestamp(issued_at, APPROVAL_NOT_ISSUABLE)
    issued_instant = _parse_timestamp(current, APPROVAL_NOT_ISSUABLE)
    if issued_instant >= _parse_timestamp(draft.expires_at, APPROVAL_NOT_ISSUABLE):
        _fail(APPROVAL_NOT_ISSUABLE)
    _validate_evidence_decision(evidence_decision)
    if not _decision_matches_draft(evidence_decision, draft):
        _fail(APPROVAL_NOT_ISSUABLE)
    _validate_reservation_result(
        reservation,
        run_id=draft.run_id,
        reservation_id=draft.reservation_id,
        dataset_id=draft.dataset_id,
        canonical_dataset_fingerprint=draft.canonical_dataset_fingerprint,
        source_commit=draft.source_commit,
        predecessor_run_id=draft.predecessor_run_id,
    )
    if issued_instant >= _parse_timestamp(
        reservation.reservation.expires_at, APPROVAL_NOT_ISSUABLE
    ) or _parse_timestamp(draft.expires_at, APPROVAL_NOT_ISSUABLE) > _parse_timestamp(
        reservation.reservation.expires_at, APPROVAL_NOT_ISSUABLE
    ):
        _fail(APPROVAL_NOT_ISSUABLE)
    from src.training.v03_tokenization_request import (
        calculate_v03_expected_artifact_set_fingerprint,
        canonical_v03_expected_artifact_set,
    )

    expected_fingerprint = calculate_v03_expected_artifact_set_fingerprint(
        canonical_v03_expected_artifact_set()
    )
    if draft.expected_artifact_set_fingerprint != expected_fingerprint:
        _fail(APPROVAL_NOT_ISSUABLE)
    nonce = issue_nonce or secrets.token_hex(32)
    if _NONCE.fullmatch(nonce) is None:
        _fail(APPROVAL_INVALID)
    if draft.approval_id in used_approval_ids or nonce in used_issue_nonces:
        _fail(APPROVAL_NOT_ISSUABLE)
    issued = _seal_approval(
        replace(draft, issued_at=current, status="issued", issue_nonce=nonce)
    )
    payload = serialize_v03_tokenization_approval(issued)
    with _lifecycle_lock(destination):
        if destination.exists():
            _fail(APPROVAL_EXISTS)
        _atomic_write_bytes(
            destination,
            payload,
            exists_code=APPROVAL_EXISTS,
            invalid_code=APPROVAL_INVALID,
        )
        loaded = load_v03_tokenization_approval(destination)
        if loaded != issued or destination.read_bytes() != payload:
            _fail(APPROVAL_INVALID)
    return issued


def approval_consumption_path(root: Path, approval_id: str) -> Path:
    return root / f"{approval_id}.consumption.json"


def approval_retirement_path(root: Path, approval_id: str) -> Path:
    return root / f"{approval_id}.retirement.json"


def _validate_lifecycle_root(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute():
        _fail(APPROVAL_INVALID)
    try:
        if root.is_symlink() or not root.is_dir():
            _fail(APPROVAL_INVALID)
    except OSError:
        _fail(APPROVAL_INVALID)
    return root


def _transition_fingerprint_payload(
    value: V03ApprovalLifecycleTransition,
) -> dict[str, object]:
    return _without(value, "transition_fingerprint", "transition_checksum")


def _seal_transition(
    value: V03ApprovalLifecycleTransition,
) -> V03ApprovalLifecycleTransition:
    value = replace(value, transition_fingerprint="", transition_checksum="")
    value = replace(
        value,
        transition_fingerprint=_fingerprint(_transition_fingerprint_payload(value)),
    )
    value = replace(
        value,
        transition_checksum=_fingerprint(_without(value, "transition_checksum")),
    )
    return validate_v03_approval_lifecycle_transition(value)


def validate_v03_approval_lifecycle_transition(
    value: V03ApprovalLifecycleTransition,
) -> V03ApprovalLifecycleTransition:
    if not isinstance(value, V03ApprovalLifecycleTransition):
        _fail(APPROVAL_INCONSISTENT)
    if type(value.schema_version) is not int or value.schema_version != SCHEMA_VERSION:
        _fail(APPROVAL_INCONSISTENT)
    for item in (value.transition_id, value.approval_id):
        _require_identifier(item, APPROVAL_INCONSISTENT)
    parse_v03_tokenization_run_id(value.run_id)
    if value.request_id is not None:
        _require_identifier(value.request_id, APPROVAL_INCONSISTENT)
    if value.previous_status != "issued" or value.status not in {
        "consumed",
        "retired",
        "expired",
    }:
        _fail(APPROVAL_INCONSISTENT)
    _parse_timestamp(value.occurred_at, APPROVAL_INCONSISTENT)
    for item in (
        value.evidence_fingerprint,
        value.approval_fingerprint,
        value.transition_fingerprint,
        value.transition_checksum,
    ):
        _require_hash(item, APPROVAL_INCONSISTENT)
    if value.status == "consumed":
        if (
            value.request_id is None
            or value.reason_code is not None
            or value.request_fingerprint is None
            or value.anti_replay_token_hash is None
        ):
            _fail(APPROVAL_INCONSISTENT)
        _require_hash(value.request_fingerprint, APPROVAL_INCONSISTENT)
        if not value.anti_replay_token_hash.startswith(
            "hmac-sha256:"
        ) or not re.fullmatch(
            r"hmac-sha256:[0-9a-f]{64}", value.anti_replay_token_hash
        ):
            _fail(APPROVAL_INCONSISTENT)
    else:
        if (
            value.request_id is not None
            or value.request_fingerprint is not None
            or value.anti_replay_token_hash is not None
            or value.reason_code not in RETIREMENT_REASONS
        ):
            _fail(APPROVAL_INCONSISTENT)
        if (
            value.status == "expired"
            and value.reason_code != "expired_before_consumption"
        ):
            _fail(APPROVAL_INCONSISTENT)
    if value.transition_fingerprint != _fingerprint(
        _transition_fingerprint_payload(value)
    ):
        _fail(APPROVAL_INCONSISTENT)
    if value.transition_checksum != _fingerprint(
        _without(value, "transition_checksum")
    ):
        _fail(APPROVAL_CHECKSUM)
    return value


def serialize_v03_approval_lifecycle_transition(
    value: V03ApprovalLifecycleTransition,
) -> bytes:
    return _canonical(asdict(validate_v03_approval_lifecycle_transition(value)))


def load_v03_approval_lifecycle_transition(
    path: Path,
) -> V03ApprovalLifecycleTransition:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            _fail(APPROVAL_INCONSISTENT)
        payload = path.read_bytes()
        data = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except V03TokenizationApprovalError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        _fail(APPROVAL_INCONSISTENT)
    fields = set(V03ApprovalLifecycleTransition.__dataclass_fields__)
    if type(data) is not dict or set(data) != fields:
        _fail(APPROVAL_INCONSISTENT)
    try:
        transition = V03ApprovalLifecycleTransition(**data)
    except TypeError:
        _fail(APPROVAL_INCONSISTENT)
    transition = validate_v03_approval_lifecycle_transition(transition)
    if payload != serialize_v03_approval_lifecycle_transition(transition):
        _fail(APPROVAL_INCONSISTENT)
    return transition


def _new_transition(
    *,
    approval: V03TokenizationApproval,
    status: str,
    occurred_at: str,
    request_id: str | None,
    reason_code: str | None,
    evidence_fingerprint: str,
    request_fingerprint: str | None,
    anti_replay_token_hash: str | None,
) -> V03ApprovalLifecycleTransition:
    identity = {
        "approval_id": approval.approval_id,
        "status": status,
        "occurred_at": occurred_at,
        "request_id": request_id,
    }
    return _seal_transition(
        V03ApprovalLifecycleTransition(
            schema_version=SCHEMA_VERSION,
            transition_id="approval-transition-v1-"
            + hashlib.sha256(_canonical(identity)).hexdigest(),
            approval_id=approval.approval_id,
            run_id=approval.run_id,
            request_id=request_id,
            previous_status="issued",
            status=status,
            occurred_at=occurred_at,
            reason_code=reason_code,
            evidence_fingerprint=evidence_fingerprint,
            request_fingerprint=request_fingerprint,
            anti_replay_token_hash=anti_replay_token_hash,
            approval_fingerprint=approval.approval_fingerprint,
            transition_fingerprint="",
            transition_checksum="",
        )
    )


def resolve_v03_approval_lifecycle(
    *,
    issued_approval: V03TokenizationApproval,
    consumption_artifact: V03ApprovalLifecycleTransition | None = None,
    retirement_artifact: V03ApprovalLifecycleTransition | None = None,
    current_time: datetime,
) -> V03ApprovalLifecycleState:
    approval = validate_v03_tokenization_approval(issued_approval)
    if approval.status != "issued" or approval.issued_at is None:
        _fail(APPROVAL_INCONSISTENT)
    now = _parse_timestamp(_format_timestamp(current_time), APPROVAL_INVALID)
    if consumption_artifact is not None and retirement_artifact is not None:
        _fail(APPROVAL_INCONSISTENT)
    transition = consumption_artifact or retirement_artifact
    if transition is not None:
        validate_v03_approval_lifecycle_transition(transition)
        if (
            transition.approval_id != approval.approval_id
            or transition.run_id != approval.run_id
            or transition.approval_fingerprint != approval.approval_fingerprint
            or _parse_timestamp(transition.occurred_at, APPROVAL_INCONSISTENT)
            < _parse_timestamp(approval.issued_at, APPROVAL_INCONSISTENT)
        ):
            _fail(APPROVAL_INCONSISTENT)
        return V03ApprovalLifecycleState(
            approval_id=approval.approval_id,
            run_id=approval.run_id,
            status=transition.status,
            request_id=transition.request_id,
            effective_at=transition.occurred_at,
            reason_code=transition.reason_code,
            approval_fingerprint=approval.approval_fingerprint,
        )
    if now > _parse_timestamp(approval.expires_at, APPROVAL_INVALID):
        return V03ApprovalLifecycleState(
            approval.approval_id,
            approval.run_id,
            "expired",
            None,
            approval.expires_at,
            "expired_before_consumption",
            approval.approval_fingerprint,
        )
    return V03ApprovalLifecycleState(
        approval.approval_id,
        approval.run_id,
        "issued",
        None,
        approval.issued_at,
        None,
        approval.approval_fingerprint,
    )


def consume_v03_tokenization_approval(
    *,
    approval_path: Path,
    request: object,
    lifecycle_root: Path,
    consumed_at: datetime,
    consumed_anti_replay_token_hashes: frozenset[str] = frozenset(),
) -> V03ApprovalConsumptionResult:
    root = _validate_lifecycle_root(lifecycle_root)
    consumed_text = _format_timestamp(consumed_at, APPROVAL_INVALID)
    from src.training.v03_tokenization_request import (
        V03TokenizationExecutionRequest,
        validate_v03_approval_request_exact_match,
        validate_v03_tokenization_execution_request,
    )

    if not isinstance(request, V03TokenizationExecutionRequest):
        _fail(REQUEST_APPROVAL)
    validate_v03_tokenization_execution_request(request)
    consumption_path = approval_consumption_path(root, request.approval_id)
    retirement_path = approval_retirement_path(root, request.approval_id)
    with _lifecycle_lock(approval_path):
        approval = load_v03_tokenization_approval(approval_path)
        if retirement_path.exists():
            retirement = load_v03_approval_lifecycle_transition(retirement_path)
            if retirement.status == "expired":
                _fail(APPROVAL_EXPIRED)
            _fail(APPROVAL_RETIRED)
        if consumption_path.exists():
            existing = load_v03_approval_lifecycle_transition(consumption_path)
            if (
                existing.status == "consumed"
                and existing.request_id == request.request_id
                and existing.request_fingerprint == request.request_fingerprint
                and existing.anti_replay_token_hash == request.anti_replay_token_hash
                and existing.occurred_at == consumed_text
            ):
                state = resolve_v03_approval_lifecycle(
                    issued_approval=approval,
                    consumption_artifact=existing,
                    current_time=consumed_at,
                )
                return V03ApprovalConsumptionResult(approval, existing, state)
            _fail(APPROVAL_CONSUMED)
        state = resolve_v03_approval_lifecycle(
            issued_approval=approval, current_time=consumed_at
        )
        if state.status == "expired":
            _fail(APPROVAL_EXPIRED)
        if request.anti_replay_token_hash in consumed_anti_replay_token_hashes:
            _fail(REQUEST_REPLAY)
        try:
            validate_v03_approval_request_exact_match(approval, request)
        except Exception as error:
            if isinstance(error, V03TokenizationApprovalError):
                raise
            _fail(REQUEST_APPROVAL)
        if _parse_timestamp(request.expires_at, REQUEST_APPROVAL) < _parse_timestamp(
            consumed_text, REQUEST_APPROVAL
        ):
            _fail(APPROVAL_EXPIRED)
        transition = _new_transition(
            approval=approval,
            status="consumed",
            occurred_at=consumed_text,
            request_id=request.request_id,
            reason_code=None,
            evidence_fingerprint=request.request_fingerprint,
            request_fingerprint=request.request_fingerprint,
            anti_replay_token_hash=request.anti_replay_token_hash,
        )
        _validate_explicit_destination(
            consumption_path,
            f"{approval.approval_id}.consumption.json",
            APPROVAL_INCONSISTENT,
        )
        before = approval_path.read_bytes()
        _atomic_write_bytes(
            consumption_path,
            serialize_v03_approval_lifecycle_transition(transition),
            exists_code=APPROVAL_CONSUMED,
            invalid_code=APPROVAL_INCONSISTENT,
        )
        loaded = load_v03_approval_lifecycle_transition(consumption_path)
        if loaded != transition or approval_path.read_bytes() != before:
            _fail(APPROVAL_INCONSISTENT)
        final_state = resolve_v03_approval_lifecycle(
            issued_approval=approval,
            consumption_artifact=loaded,
            current_time=consumed_at,
        )
        return V03ApprovalConsumptionResult(approval, loaded, final_state)


def _retire_or_expire(
    *,
    approval_path: Path,
    lifecycle_root: Path,
    reason_code: str,
    evidence_fingerprint: str,
    occurred_at: datetime,
    target_status: str,
) -> V03ApprovalLifecycleTransition:
    if reason_code not in RETIREMENT_REASONS:
        _fail(APPROVAL_INVALID)
    _require_hash(evidence_fingerprint)
    root = _validate_lifecycle_root(lifecycle_root)
    occurred_text = _format_timestamp(occurred_at)
    with _lifecycle_lock(approval_path):
        approval = load_v03_tokenization_approval(approval_path)
        consumption_path = approval_consumption_path(root, approval.approval_id)
        retirement_path = approval_retirement_path(root, approval.approval_id)
        if consumption_path.exists():
            load_v03_approval_lifecycle_transition(consumption_path)
            _fail(APPROVAL_CONSUMED)
        if retirement_path.exists():
            load_v03_approval_lifecycle_transition(retirement_path)
            _fail(APPROVAL_RETIRED)
        state = resolve_v03_approval_lifecycle(
            issued_approval=approval, current_time=occurred_at
        )
        expires = _parse_timestamp(approval.expires_at)
        current = _parse_timestamp(occurred_text)
        if target_status == "expired":
            if reason_code != "expired_before_consumption" or current <= expires:
                _fail(APPROVAL_INVALID)
        elif state.status == "expired":
            _fail(APPROVAL_EXPIRED)
        transition = _new_transition(
            approval=approval,
            status=target_status,
            occurred_at=occurred_text,
            request_id=None,
            reason_code=reason_code,
            evidence_fingerprint=evidence_fingerprint,
            request_fingerprint=None,
            anti_replay_token_hash=None,
        )
        _validate_explicit_destination(
            retirement_path,
            f"{approval.approval_id}.retirement.json",
            APPROVAL_INCONSISTENT,
        )
        before = approval_path.read_bytes()
        _atomic_write_bytes(
            retirement_path,
            serialize_v03_approval_lifecycle_transition(transition),
            exists_code=APPROVAL_RETIRED,
            invalid_code=APPROVAL_INCONSISTENT,
        )
        loaded = load_v03_approval_lifecycle_transition(retirement_path)
        if loaded != transition or approval_path.read_bytes() != before:
            _fail(APPROVAL_INCONSISTENT)
        return loaded


def retire_v03_tokenization_approval(
    *,
    approval_path: Path,
    lifecycle_root: Path,
    reason_code: str,
    evidence_fingerprint: str,
    retired_at: datetime,
) -> V03ApprovalLifecycleTransition:
    return _retire_or_expire(
        approval_path=approval_path,
        lifecycle_root=lifecycle_root,
        reason_code=reason_code,
        evidence_fingerprint=evidence_fingerprint,
        occurred_at=retired_at,
        target_status="retired",
    )


def expire_v03_tokenization_approval(
    *,
    approval_path: Path,
    lifecycle_root: Path,
    evidence_fingerprint: str,
    current_time: datetime,
) -> V03ApprovalLifecycleTransition:
    return _retire_or_expire(
        approval_path=approval_path,
        lifecycle_root=lifecycle_root,
        reason_code="expired_before_consumption",
        evidence_fingerprint=evidence_fingerprint,
        occurred_at=current_time,
        target_status="expired",
    )
