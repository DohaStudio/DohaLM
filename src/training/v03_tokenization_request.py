"""Synthetic-only V0.3 TokenizationExecutionRequest v1 contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from src.training.v03_run_identity import (
    V03ReservationResult,
    V03RunIdentityError,
    parse_v03_tokenization_run_id,
)
from src.training.v03_tokenization_approval import (
    APPROVAL_EXPIRED,
    LIFECYCLE_LOCK_FAILED,
    V03ApprovalLifecycleTransition,
    V03TokenizationApproval,
    V03TokenizationApprovalError,
    _atomic_write_bytes,
    _canonical,
    _fingerprint,
    _format_timestamp,
    _lifecycle_lock,
    _parse_timestamp,
    _require_git_sha,
    _require_hash,
    _require_identifier,
    _require_logical_identity,
    _validate_explicit_destination,
    _validate_lifecycle_root,
    _validate_reservation_result,
    _without,
    approval_consumption_path,
    approval_retirement_path,
    load_v03_approval_lifecycle_transition,
    load_v03_tokenization_approval,
    resolve_v03_approval_lifecycle,
    validate_v03_tokenization_approval,
)


class V03TokenizationRequestError(RuntimeError):
    """Fail-closed error whose message contains only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


REQUEST_INVALID = "V03_REQUEST_INVALID"
REQUEST_EXISTS = "V03_REQUEST_ALREADY_EXISTS"
REQUEST_EXPIRED = "V03_REQUEST_EXPIRED"
REQUEST_APPROVAL = "V03_REQUEST_APPROVAL_MISMATCH"
REQUEST_RESERVATION = "V03_REQUEST_RESERVATION_MISMATCH"
REQUEST_REPLAY = "V03_REQUEST_REPLAY_DETECTED"
REQUEST_CHECKSUM = "V03_REQUEST_CHECKSUM_MISMATCH"
EXPECTED_SET_INVALID = "V03_EXPECTED_ARTIFACT_SET_INVALID"

SCHEMA_VERSION = 1
REQUEST_TYPE = "v03_fresh_tokenization"
REQUEST_STATUSES = frozenset({"created", "validated", "consumed", "retired", "expired"})
_HMAC_HASH = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class V03ExpectedArtifact:
    logical_name: str
    relative_name: str
    required: bool
    content_type: str
    schema_version: int


@dataclass(frozen=True)
class V03TokenizationExecutionRequest:
    schema_version: int
    request_id: str
    request_type: str
    run_id: str
    reservation_id: str
    approval_id: str
    approval_fingerprint: str
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
    requested_output_root_id: str
    requested_staging_root_id: str
    requested_failure_root_id: str
    expected_artifact_set: tuple[V03ExpectedArtifact, ...]
    expected_artifact_set_fingerprint: str
    execution_environment_fingerprint: str
    predecessor_run_id: str | None
    created_at: str
    expires_at: str
    request_nonce: str
    anti_replay_token_hash: str
    request_fingerprint: str
    request_checksum: str
    status: str


@dataclass(frozen=True)
class V03RequestLifecycleState:
    request_id: str
    approval_id: str
    run_id: str
    status: str
    effective_at: str
    request_fingerprint: str


@dataclass(frozen=True)
class V03RequestWriteResult:
    request: V03TokenizationExecutionRequest
    destination_name: str
    bytes_written: int
    lifecycle_state: V03RequestLifecycleState


def _fail(code: str) -> None:
    raise V03TokenizationRequestError(code)


def canonical_v03_expected_artifact_set() -> tuple[V03ExpectedArtifact, ...]:
    """Return the exact Recovery Contract top-level package allowlist."""

    return (
        V03ExpectedArtifact(
            "tokenized_train",
            "train",
            True,
            "application/vnd.apache.arrow.dataset",
            1,
        ),
        V03ExpectedArtifact(
            "tokenized_validation",
            "validation",
            True,
            "application/vnd.apache.arrow.dataset",
            1,
        ),
        V03ExpectedArtifact(
            "row_alignment", "row-alignment.json", True, "application/json", 1
        ),
        V03ExpectedArtifact(
            "lineage", "lineage-alignment.json", True, "application/json", 1
        ),
        V03ExpectedArtifact(
            "tokenization_manifest",
            "tokenization-manifest.yaml",
            True,
            "application/yaml",
            1,
        ),
        V03ExpectedArtifact(
            "token_statistics",
            "tokenization-statistics.json",
            True,
            "application/json",
            1,
        ),
        V03ExpectedArtifact(
            "sampler_readiness",
            "sampler-readiness.yaml",
            True,
            "application/yaml",
            1,
        ),
        V03ExpectedArtifact(
            "checksum_inventory", "checksums.sha256", True, "text/plain", 1
        ),
    )


def validate_v03_expected_artifact_set(
    value: Sequence[V03ExpectedArtifact],
) -> tuple[V03ExpectedArtifact, ...]:
    if not isinstance(value, (tuple, list)):
        _fail(EXPECTED_SET_INVALID)
    entries = tuple(value)
    if entries != canonical_v03_expected_artifact_set():
        _fail(EXPECTED_SET_INVALID)
    logical_names: set[str] = set()
    relative_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, V03ExpectedArtifact):
            _fail(EXPECTED_SET_INVALID)
        try:
            _require_identifier(entry.logical_name, EXPECTED_SET_INVALID)
        except V03TokenizationApprovalError:
            _fail(EXPECTED_SET_INVALID)
        if (
            type(entry.relative_name) is not str
            or not entry.relative_name
            or "\\" in entry.relative_name
            or PurePosixPath(entry.relative_name).is_absolute()
            or PureWindowsPath(entry.relative_name).is_absolute()
            or ".." in PurePosixPath(entry.relative_name).parts
            or ":" in entry.relative_name
        ):
            _fail(EXPECTED_SET_INVALID)
        if type(entry.required) is not bool or not entry.required:
            _fail(EXPECTED_SET_INVALID)
        if entry.content_type not in {
            "application/vnd.apache.arrow.dataset",
            "application/json",
            "application/yaml",
            "text/plain",
        }:
            _fail(EXPECTED_SET_INVALID)
        if type(entry.schema_version) is not int or entry.schema_version != 1:
            _fail(EXPECTED_SET_INVALID)
        if entry.logical_name in logical_names or entry.relative_name in relative_names:
            _fail(EXPECTED_SET_INVALID)
        logical_names.add(entry.logical_name)
        relative_names.add(entry.relative_name)
    return entries


def calculate_v03_expected_artifact_set_fingerprint(
    value: Sequence[V03ExpectedArtifact],
) -> str:
    entries = validate_v03_expected_artifact_set(value)
    return _fingerprint([asdict(entry) for entry in entries])


def calculate_v03_execution_environment_fingerprint(
    value: Mapping[str, object],
) -> str:
    """Fingerprint safe logical environment metadata without local paths."""

    forbidden_keys = {"path", "absolute_path", "secret", "token", "nonce", "credential"}

    def validate(item: object, key: str | None = None) -> None:
        if key is not None and key.lower() in forbidden_keys:
            _fail(REQUEST_INVALID)
        if type(item) is dict:
            for nested_key, nested in item.items():
                if type(nested_key) is not str or not nested_key:
                    _fail(REQUEST_INVALID)
                validate(nested, nested_key)
            return
        if type(item) in {list, tuple}:
            for nested in item:
                validate(nested)
            return
        if item is None or type(item) in {bool, int}:
            return
        if type(item) is str:
            if (
                not item
                or item != item.strip()
                or "\x00" in item
                or "\n" in item
                or PurePosixPath(item).is_absolute()
                or PureWindowsPath(item).is_absolute()
            ):
                _fail(REQUEST_INVALID)
            return
        _fail(REQUEST_INVALID)

    if type(value) is not dict or not value:
        _fail(REQUEST_INVALID)
    validate(value)
    return _fingerprint(value)


def make_v03_anti_replay_token_hash(
    *,
    token: str,
    approval_id: str,
    request_id: str,
    run_id: str,
    request_nonce: str,
) -> str:
    if type(token) is not str or len(token.encode("utf-8")) < 32:
        _fail(REQUEST_REPLAY)
    try:
        _require_identifier(approval_id, REQUEST_REPLAY)
        _require_identifier(request_id, REQUEST_REPLAY)
        parse_v03_tokenization_run_id(run_id)
    except (V03TokenizationApprovalError, RuntimeError):
        _fail(REQUEST_REPLAY)
    if _NONCE.fullmatch(request_nonce) is None:
        _fail(REQUEST_REPLAY)
    context = _canonical(
        {
            "domain": "dohalm-v03-tokenization-request-anti-replay-v1",
            "approval_id": approval_id,
            "request_id": request_id,
            "run_id": run_id,
            "request_nonce": request_nonce,
        }
    )
    digest = hmac.new(token.encode("utf-8"), context, hashlib.sha256).hexdigest()
    return "hmac-sha256:" + digest


def _request_fingerprint_payload(
    value: V03TokenizationExecutionRequest,
) -> dict[str, object]:
    return _without(value, "status", "request_fingerprint", "request_checksum")


def validate_v03_tokenization_execution_request(
    value: V03TokenizationExecutionRequest,
) -> V03TokenizationExecutionRequest:
    if not isinstance(value, V03TokenizationExecutionRequest):
        _fail(REQUEST_INVALID)
    if type(value.schema_version) is not int or value.schema_version != SCHEMA_VERSION:
        _fail(REQUEST_INVALID)
    if value.request_type != REQUEST_TYPE or value.status not in REQUEST_STATUSES:
        _fail(REQUEST_INVALID)
    try:
        for item in (
            value.request_id,
            value.reservation_id,
            value.approval_id,
            value.dataset_id,
        ):
            _require_identifier(item, REQUEST_INVALID)
        parse_v03_tokenization_run_id(value.run_id)
        if value.predecessor_run_id is not None:
            parse_v03_tokenization_run_id(value.predecessor_run_id)
            if value.predecessor_run_id == value.run_id:
                _fail(REQUEST_INVALID)
        for item in (
            value.approval_fingerprint,
            value.canonical_dataset_fingerprint,
            value.effective_dataset_fingerprint,
            value.evidence_bundle_fingerprint,
            value.tokenization_config_fingerprint,
            value.tokenizer_inventory_fingerprint,
            value.chat_template_fingerprint,
            value.backend_fingerprint,
            value.dependency_fingerprint,
            value.expected_artifact_set_fingerprint,
            value.execution_environment_fingerprint,
            value.request_fingerprint,
            value.request_checksum,
        ):
            _require_hash(item, REQUEST_INVALID)
        _require_logical_identity(value.tokenizer_identity, REQUEST_INVALID)
        for item in (
            value.requested_output_root_id,
            value.requested_staging_root_id,
            value.requested_failure_root_id,
        ):
            _require_logical_identity(item, REQUEST_INVALID)
        _require_git_sha(value.source_commit, REQUEST_INVALID)
    except (V03TokenizationApprovalError, V03RunIdentityError):
        _fail(REQUEST_INVALID)
    roots = {
        value.requested_output_root_id,
        value.requested_staging_root_id,
        value.requested_failure_root_id,
    }
    if len(roots) != 3:
        _fail(REQUEST_INVALID)
    entries = validate_v03_expected_artifact_set(value.expected_artifact_set)
    if (
        value.expected_artifact_set_fingerprint
        != calculate_v03_expected_artifact_set_fingerprint(entries)
    ):
        _fail(EXPECTED_SET_INVALID)
    created = _parse_timestamp(value.created_at, REQUEST_INVALID)
    expires = _parse_timestamp(value.expires_at, REQUEST_INVALID)
    if expires <= created or expires - created > timedelta(hours=1):
        _fail(REQUEST_INVALID)
    if (
        _NONCE.fullmatch(value.request_nonce) is None
        or _HMAC_HASH.fullmatch(value.anti_replay_token_hash) is None
    ):
        _fail(REQUEST_INVALID)
    if value.request_fingerprint != _fingerprint(_request_fingerprint_payload(value)):
        _fail(REQUEST_CHECKSUM)
    if value.request_checksum != _fingerprint(_without(value, "request_checksum")):
        _fail(REQUEST_CHECKSUM)
    return value


def _seal_request(
    value: V03TokenizationExecutionRequest,
) -> V03TokenizationExecutionRequest:
    try:
        value = replace(value, request_fingerprint="", request_checksum="")
        value = replace(
            value,
            request_fingerprint=_fingerprint(_request_fingerprint_payload(value)),
        )
        value = replace(
            value, request_checksum=_fingerprint(_without(value, "request_checksum"))
        )
    except V03TokenizationApprovalError:
        _fail(REQUEST_INVALID)
    return validate_v03_tokenization_execution_request(value)


def new_v03_tokenization_execution_request(
    *,
    request_id: str,
    approval: V03TokenizationApproval,
    requested_staging_root_id: str,
    requested_failure_root_id: str,
    execution_environment_fingerprint: str,
    created_at: datetime,
    expires_at: datetime,
    request_nonce: str,
    anti_replay_token: str,
    expected_artifact_set: Sequence[V03ExpectedArtifact] | None = None,
) -> V03TokenizationExecutionRequest:
    approval = validate_v03_tokenization_approval(approval)
    entries = tuple(expected_artifact_set or canonical_v03_expected_artifact_set())
    anti_replay_hash = make_v03_anti_replay_token_hash(
        token=anti_replay_token,
        approval_id=approval.approval_id,
        request_id=request_id,
        run_id=approval.run_id,
        request_nonce=request_nonce,
    )
    return _seal_request(
        V03TokenizationExecutionRequest(
            schema_version=SCHEMA_VERSION,
            request_id=request_id,
            request_type=REQUEST_TYPE,
            run_id=approval.run_id,
            reservation_id=approval.reservation_id,
            approval_id=approval.approval_id,
            approval_fingerprint=approval.approval_fingerprint,
            dataset_id=approval.dataset_id,
            canonical_dataset_fingerprint=approval.canonical_dataset_fingerprint,
            effective_dataset_fingerprint=approval.effective_dataset_fingerprint,
            evidence_bundle_fingerprint=approval.evidence_bundle_fingerprint,
            tokenization_config_fingerprint=approval.tokenization_config_fingerprint,
            tokenizer_identity=approval.tokenizer_identity,
            tokenizer_inventory_fingerprint=approval.tokenizer_inventory_fingerprint,
            chat_template_fingerprint=approval.chat_template_fingerprint,
            backend_fingerprint=approval.backend_fingerprint,
            dependency_fingerprint=approval.dependency_fingerprint,
            source_commit=approval.source_commit,
            requested_output_root_id=approval.allowed_output_root_id,
            requested_staging_root_id=requested_staging_root_id,
            requested_failure_root_id=requested_failure_root_id,
            expected_artifact_set=entries,
            expected_artifact_set_fingerprint=calculate_v03_expected_artifact_set_fingerprint(
                entries
            ),
            execution_environment_fingerprint=execution_environment_fingerprint,
            predecessor_run_id=approval.predecessor_run_id,
            created_at=_format_timestamp(created_at, REQUEST_INVALID),
            expires_at=_format_timestamp(expires_at, REQUEST_INVALID),
            request_nonce=request_nonce,
            anti_replay_token_hash=anti_replay_hash,
            request_fingerprint="",
            request_checksum="",
            status="created",
        )
    )


def serialize_v03_tokenization_execution_request(
    value: V03TokenizationExecutionRequest,
) -> bytes:
    request = validate_v03_tokenization_execution_request(value)
    return _canonical(asdict(request))


def deserialize_v03_tokenization_execution_request(
    value: Mapping[str, object],
) -> V03TokenizationExecutionRequest:
    fields = set(V03TokenizationExecutionRequest.__dataclass_fields__)
    if type(value) is not dict or set(value) != fields:
        _fail(REQUEST_INVALID)
    raw_entries = value.get("expected_artifact_set")
    if type(raw_entries) is not list:
        _fail(EXPECTED_SET_INVALID)
    entries: list[V03ExpectedArtifact] = []
    expected_fields = set(V03ExpectedArtifact.__dataclass_fields__)
    for raw_entry in raw_entries:
        if type(raw_entry) is not dict or set(raw_entry) != expected_fields:
            _fail(EXPECTED_SET_INVALID)
        try:
            entries.append(V03ExpectedArtifact(**raw_entry))
        except TypeError:
            _fail(EXPECTED_SET_INVALID)
    converted = dict(value)
    converted["expected_artifact_set"] = tuple(entries)
    try:
        request = V03TokenizationExecutionRequest(**converted)  # type: ignore[arg-type]
    except TypeError:
        _fail(REQUEST_INVALID)
    return validate_v03_tokenization_execution_request(request)


def _reject_duplicate_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            _fail(REQUEST_INVALID)
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail(REQUEST_INVALID)


def load_v03_tokenization_execution_request(
    path: Path,
) -> V03TokenizationExecutionRequest:
    if not isinstance(path, Path):
        _fail(REQUEST_INVALID)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            _fail(REQUEST_INVALID)
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except V03TokenizationRequestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        _fail(REQUEST_INVALID)
    request = deserialize_v03_tokenization_execution_request(value)
    if payload != serialize_v03_tokenization_execution_request(request):
        _fail(REQUEST_INVALID)
    if path.name != f"{request.request_id}.json":
        _fail(REQUEST_INVALID)
    return request


def validate_v03_approval_request_exact_match(
    approval: V03TokenizationApproval,
    request: V03TokenizationExecutionRequest,
) -> None:
    try:
        approval = validate_v03_tokenization_approval(approval)
    except V03TokenizationApprovalError:
        _fail(REQUEST_APPROVAL)
    request = validate_v03_tokenization_execution_request(request)
    pairs = (
        (request.run_id, approval.run_id),
        (request.reservation_id, approval.reservation_id),
        (request.approval_id, approval.approval_id),
        (request.approval_fingerprint, approval.approval_fingerprint),
        (request.dataset_id, approval.dataset_id),
        (request.canonical_dataset_fingerprint, approval.canonical_dataset_fingerprint),
        (request.effective_dataset_fingerprint, approval.effective_dataset_fingerprint),
        (request.evidence_bundle_fingerprint, approval.evidence_bundle_fingerprint),
        (
            request.tokenization_config_fingerprint,
            approval.tokenization_config_fingerprint,
        ),
        (request.tokenizer_identity, approval.tokenizer_identity),
        (
            request.tokenizer_inventory_fingerprint,
            approval.tokenizer_inventory_fingerprint,
        ),
        (request.chat_template_fingerprint, approval.chat_template_fingerprint),
        (request.backend_fingerprint, approval.backend_fingerprint),
        (request.dependency_fingerprint, approval.dependency_fingerprint),
        (request.source_commit, approval.source_commit),
        (request.requested_output_root_id, approval.allowed_output_root_id),
        (
            request.expected_artifact_set_fingerprint,
            approval.expected_artifact_set_fingerprint,
        ),
        (request.predecessor_run_id, approval.predecessor_run_id),
    )
    if any(left != right for left, right in pairs):
        _fail(REQUEST_APPROVAL)


def _validate_request_reservation(
    request: V03TokenizationExecutionRequest,
    reservation: V03ReservationResult,
) -> None:
    try:
        _validate_reservation_result(
            reservation,
            run_id=request.run_id,
            reservation_id=request.reservation_id,
            dataset_id=request.dataset_id,
            canonical_dataset_fingerprint=request.canonical_dataset_fingerprint,
            source_commit=request.source_commit,
            predecessor_run_id=request.predecessor_run_id,
        )
    except V03TokenizationApprovalError:
        _fail(REQUEST_RESERVATION)


def resolve_v03_request_lifecycle(
    *,
    request: V03TokenizationExecutionRequest,
    issued_approval: V03TokenizationApproval,
    consumption_artifact: V03ApprovalLifecycleTransition | None = None,
    retirement_artifact: V03ApprovalLifecycleTransition | None = None,
    current_time: datetime,
) -> V03RequestLifecycleState:
    request = validate_v03_tokenization_execution_request(request)
    validate_v03_approval_request_exact_match(issued_approval, request)
    try:
        approval_state = resolve_v03_approval_lifecycle(
            issued_approval=issued_approval,
            consumption_artifact=consumption_artifact,
            retirement_artifact=retirement_artifact,
            current_time=current_time,
        )
    except V03TokenizationApprovalError as error:
        _fail(error.code if error.code == LIFECYCLE_LOCK_FAILED else REQUEST_APPROVAL)
    if approval_state.status == "consumed":
        if approval_state.request_id != request.request_id:
            _fail(REQUEST_APPROVAL)
        status = "consumed"
        effective_at = approval_state.effective_at
    elif approval_state.status == "retired":
        status = "retired"
        effective_at = approval_state.effective_at
    elif approval_state.status == "expired":
        status = "expired"
        effective_at = approval_state.effective_at
    elif _parse_timestamp(
        _format_timestamp(current_time), REQUEST_INVALID
    ) > _parse_timestamp(request.expires_at, REQUEST_INVALID):
        status = "expired"
        effective_at = request.expires_at
    else:
        status = request.status
        effective_at = request.created_at
    return V03RequestLifecycleState(
        request.request_id,
        request.approval_id,
        request.run_id,
        status,
        effective_at,
        request.request_fingerprint,
    )


def write_v03_tokenization_execution_request(
    *,
    destination: Path,
    approval_path: Path,
    lifecycle_root: Path,
    request: V03TokenizationExecutionRequest,
    approval: V03TokenizationApproval,
    reservation: V03ReservationResult,
    current_time: datetime,
    used_request_ids: frozenset[str] = frozenset(),
    used_request_nonces: frozenset[str] = frozenset(),
    used_anti_replay_token_hashes: frozenset[str] = frozenset(),
) -> V03RequestWriteResult:
    request = validate_v03_tokenization_execution_request(request)
    if request.status != "created":
        _fail(REQUEST_INVALID)
    try:
        approval = validate_v03_tokenization_approval(approval)
    except V03TokenizationApprovalError:
        _fail(REQUEST_APPROVAL)
    _validate_request_reservation(request, reservation)
    validate_v03_approval_request_exact_match(approval, request)
    try:
        _validate_explicit_destination(
            destination, f"{request.request_id}.json", REQUEST_INVALID
        )
        root = _validate_lifecycle_root(lifecycle_root)
    except V03TokenizationApprovalError:
        _fail(REQUEST_INVALID)
    now_text = _format_timestamp(current_time, REQUEST_INVALID)
    now = _parse_timestamp(now_text, REQUEST_INVALID)
    created = _parse_timestamp(request.created_at, REQUEST_INVALID)
    expires = _parse_timestamp(request.expires_at, REQUEST_INVALID)
    approval_expires = _parse_timestamp(approval.expires_at, REQUEST_APPROVAL)
    if created > now or now > expires:
        _fail(REQUEST_EXPIRED)
    if expires > approval_expires or created < _parse_timestamp(
        approval.issued_at, REQUEST_APPROVAL
    ):
        _fail(REQUEST_APPROVAL)
    if request.request_id in used_request_ids:
        _fail(REQUEST_REPLAY)
    if request.request_nonce in used_request_nonces:
        _fail(REQUEST_REPLAY)
    if request.anti_replay_token_hash in used_anti_replay_token_hashes:
        _fail(REQUEST_REPLAY)
    payload = serialize_v03_tokenization_execution_request(request)
    try:
        with _lifecycle_lock(approval_path):
            loaded_approval = load_v03_tokenization_approval(approval_path)
            if loaded_approval != approval:
                _fail(REQUEST_APPROVAL)
            consumption_path = approval_consumption_path(root, approval.approval_id)
            retirement_path = approval_retirement_path(root, approval.approval_id)
            consumption = (
                load_v03_approval_lifecycle_transition(consumption_path)
                if consumption_path.exists()
                else None
            )
            retirement = (
                load_v03_approval_lifecycle_transition(retirement_path)
                if retirement_path.exists()
                else None
            )
            lifecycle = resolve_v03_approval_lifecycle(
                issued_approval=approval,
                consumption_artifact=consumption,
                retirement_artifact=retirement,
                current_time=current_time,
            )
            if lifecycle.status != "issued":
                if lifecycle.status == "expired":
                    _fail(REQUEST_EXPIRED)
                _fail(REQUEST_APPROVAL)
            if destination.exists():
                _fail(REQUEST_EXISTS)
            before = approval_path.read_bytes()
            _atomic_write_bytes(
                destination,
                payload,
                exists_code=REQUEST_EXISTS,
                invalid_code=REQUEST_INVALID,
            )
            loaded = load_v03_tokenization_execution_request(destination)
            if loaded != request or approval_path.read_bytes() != before:
                _fail(REQUEST_INVALID)
    except V03TokenizationApprovalError as error:
        if error.code == LIFECYCLE_LOCK_FAILED:
            _fail(LIFECYCLE_LOCK_FAILED)
        if error.code == APPROVAL_EXPIRED:
            _fail(REQUEST_EXPIRED)
        _fail(REQUEST_APPROVAL)
    state = resolve_v03_request_lifecycle(
        request=request,
        issued_approval=approval,
        current_time=current_time,
    )
    state = replace(state, status="validated", effective_at=now_text)
    return V03RequestWriteResult(request, destination.name, len(payload), state)
