"""Run identity, registry, and single-use execution counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Mapping


RETIRED_RUN_IDS = frozenset({
    "AIHUB-71748-SFT-PROCESSING-20260729-0001",
    "AIHUB-71748-SFT-PROCESSING-20260729-0002",
    "AIHUB-71748-SFT-PROCESSING-20260729-0003",
    "AIHUB-71748-SFT-PROCESSING-20260729-0004",
    "AIHUB-71748-SFT-PROCESSING-20260730-0005",
    "AIHUB-71748-SFT-PROCESSING-20260730-0006",
    "AIHUB-71748-SFT-PROCESSING-20260730-0007",
})
RETIRED_APPROVAL_IDS = frozenset({
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0003",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0004",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0005",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0006",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0007",
})
RETIRED_RUN_STATES = {
    "AIHUB-71748-SFT-PROCESSING-20260729-0001": "retired",
    "AIHUB-71748-SFT-PROCESSING-20260729-0002": "retired_failed_closed_before_consumption",
    "AIHUB-71748-SFT-PROCESSING-20260729-0003": "retired_failed_closed_before_approval",
    "AIHUB-71748-SFT-PROCESSING-20260729-0004": "retired_execution_source_tree_drift",
    "AIHUB-71748-SFT-PROCESSING-20260730-0005": "retired_preflight_validator_failure",
    "AIHUB-71748-SFT-PROCESSING-20260730-0006": "retired_approval_contract_failure",
    "AIHUB-71748-SFT-PROCESSING-20260730-0007": "retired_contract_mismatch_before_start",
}
RETIRED_APPROVAL_STATES = {
    approval_id: "retired_not_issued" for approval_id in RETIRED_APPROVAL_IDS
}
RUN_STATES = frozenset({
    "unused", "reserved_preflight", "preflight_passed", "preflight_failed_closed",
    "approval_issued", "processing_started", "processing_completed", "processing_failed",
    "retired", *RETIRED_RUN_STATES.values(),
})
_RUN = re.compile(r"^AIHUB-71748-SFT-PROCESSING-\d{8}-\d{4}$")
_APPROVAL = re.compile(r"^AIHUB-71748-SFT-PROCESSING-APPROVAL-\d{8}-\d{4}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class RunContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessingRunContract:
    run_id: str
    approval_id: str
    retry_allowed: bool = False
    resume_allowed: bool = False
    overwrite_allowed: bool = False
    extension_allowed: bool = False
    processing_allowed: bool = False
    payload_read_allowed: bool = False
    output_write_allowed: bool = False
    execution_allowed: bool = False
    maximum_processing_calls: int = 1
    maximum_payload_open_sessions: int = 1
    synthetic: bool = False


@dataclass(frozen=True)
class RuntimeExecutionRequest:
    schema_version: int
    request_id: str
    run_id: str
    approval_id: str
    approval_fingerprint: str
    preflight_evidence_fingerprint: str
    execution_source_commit: str
    governance_record_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    execution_allowed: bool
    maximum_processing_calls: int
    maximum_payload_open_sessions: int
    requested_by: str
    requested_at: str
    expires_at: str
    nonce: str
    request_fingerprint: str = ""


def runtime_request_fingerprint(request: RuntimeExecutionRequest) -> str:
    payload = {
        **request.__dict__,
        "request_fingerprint": "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def deserialize_runtime_request(value: Mapping[str, object]) -> RuntimeExecutionRequest:
    expected = set(RuntimeExecutionRequest.__dataclass_fields__)
    if set(value) != expected:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    try:
        return RuntimeExecutionRequest(**value)  # type: ignore[arg-type]
    except TypeError:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT") from None


def validate_runtime_request(
    request: RuntimeExecutionRequest,
    contract: ProcessingRunContract,
    *,
    expected_approval_fingerprint: str | None = None,
    expected_preflight_evidence_fingerprint: str | None = None,
    expected_execution_source_commit: str | None = None,
    expected_governance_record_commit: str | None = None,
    expected_manifest_sha256: str | None = None,
    expected_backend_fingerprint: str | None = None,
    now: datetime | None = None,
    used_fingerprints: set[str] | None = None,
) -> None:
    if request.schema_version != 1:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if request.run_id != contract.run_id:
        raise RunContractError("RUNTIME_REQUEST_RUN_MISMATCH")
    if request.approval_id != contract.approval_id:
        raise RunContractError("RUNTIME_REQUEST_APPROVAL_MISMATCH")
    if not isinstance(request.execution_allowed, bool):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if not request.execution_allowed:
        raise RunContractError("RUNTIME_EXECUTION_NOT_APPROVED")
    if not all((
        contract.processing_allowed,
        contract.payload_read_allowed,
        contract.output_write_allowed,
    )):
        raise RunContractError("APPROVAL_CAPABILITY_INSUFFICIENT")
    if (
        isinstance(request.maximum_processing_calls, bool)
        or isinstance(request.maximum_payload_open_sessions, bool)
        or request.maximum_processing_calls != 1
        or request.maximum_payload_open_sessions != 1
    ):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (
            request.request_id, request.approval_fingerprint,
            request.preflight_evidence_fingerprint, request.execution_source_commit,
            request.governance_record_commit, request.manifest_sha256,
            request.backend_fingerprint, request.requested_by, request.nonce,
        )
    ):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if (
        any(not _SHA256.fullmatch(value) for value in (
            request.approval_fingerprint, request.preflight_evidence_fingerprint,
            request.manifest_sha256, request.backend_fingerprint,
        ))
        or not _COMMIT.fullmatch(request.execution_source_commit)
        or not _COMMIT.fullmatch(request.governance_record_commit)
    ):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    try:
        requested = datetime.fromisoformat(request.requested_at)
        expires = datetime.fromisoformat(request.expires_at)
    except (TypeError, ValueError):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT") from None
    if (
        requested.tzinfo is None or requested.utcoffset() is None
        or expires.tzinfo is None or expires.utcoffset() is None
        or expires <= requested or expires - requested > timedelta(hours=1)
    ):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if request.request_fingerprint != runtime_request_fingerprint(request):
        raise RunContractError("RUNTIME_REQUEST_FINGERPRINT_MISMATCH")
    if used_fingerprints is not None and request.request_fingerprint in used_fingerprints:
        raise RunContractError("RUNTIME_REQUEST_REUSED")
    if (now or datetime.now(requested.tzinfo)) > expires:
        raise RunContractError("RUNTIME_REQUEST_EXPIRED")
    expected = {
        "approval_fingerprint": expected_approval_fingerprint,
        "preflight_evidence_fingerprint": expected_preflight_evidence_fingerprint,
        "execution_source_commit": expected_execution_source_commit,
        "governance_record_commit": expected_governance_record_commit,
        "manifest_sha256": expected_manifest_sha256,
        "backend_fingerprint": expected_backend_fingerprint,
    }
    for field_name, expected_value in expected.items():
        if expected_value is not None and getattr(request, field_name) != expected_value:
            code = (
                "RUNTIME_REQUEST_APPROVAL_MISMATCH"
                if field_name == "approval_fingerprint"
                else "RUNTIME_PERMISSION_CONFLICT"
            )
            raise RunContractError(code)
    if not request.request_id.strip() or not request.requested_by.strip() or not request.nonce.strip():
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")


def new_runtime_execution_request(
    contract: ProcessingRunContract,
    *,
    request_id: str,
    approval_fingerprint: str,
    preflight_evidence_fingerprint: str,
    execution_source_commit: str,
    governance_record_commit: str,
    manifest_sha256: str,
    backend_fingerprint: str,
    requested_by: str,
    requested_at: str,
    expires_at: str,
    nonce: str,
    counters: "ExecutionCounters | None" = None,
) -> RuntimeExecutionRequest:
    request = RuntimeExecutionRequest(
        schema_version=1,
        request_id=request_id,
        run_id=contract.run_id,
        approval_id=contract.approval_id,
        approval_fingerprint=approval_fingerprint,
        preflight_evidence_fingerprint=preflight_evidence_fingerprint,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=manifest_sha256,
        backend_fingerprint=backend_fingerprint,
        execution_allowed=True,
        maximum_processing_calls=1,
        maximum_payload_open_sessions=1,
        requested_by=requested_by,
        requested_at=requested_at,
        expires_at=expires_at,
        nonce=nonce,
    )
    request = RuntimeExecutionRequest(**{**request.__dict__, "request_fingerprint": runtime_request_fingerprint(request)})
    validate_runtime_request(request, contract, now=datetime.fromisoformat(requested_at))
    if counters is not None:
        counters.increment("runtime_request_creations")
    return request


def validate_run_contract(contract: ProcessingRunContract) -> None:
    if contract.run_id in RETIRED_RUN_IDS:
        raise RunContractError("RUN_ID_RETIRED")
    if contract.approval_id in RETIRED_APPROVAL_IDS:
        raise RunContractError("APPROVAL_RETIRED")
    synthetic_identity = (
        contract.synthetic
        and contract.run_id.startswith("SYNTHETIC-")
        and contract.approval_id.startswith("SYNTHETIC-")
    )
    if not synthetic_identity and (not _RUN.fullmatch(contract.run_id) or not _APPROVAL.fullmatch(contract.approval_id)):
        raise RunContractError("RUN_ID_ALREADY_USED")
    suffix = contract.run_id.rsplit("-", 2)[-2:]
    if not synthetic_identity and contract.approval_id.rsplit("-", 2)[-2:] != suffix:
        raise RunContractError("RUN_ID_ALREADY_USED")
    if any((contract.retry_allowed, contract.resume_allowed, contract.overwrite_allowed, contract.extension_allowed)):
        raise RunContractError("RUN_ID_ALREADY_USED")
    capabilities = (
        contract.processing_allowed,
        contract.payload_read_allowed,
        contract.output_write_allowed,
    )
    if not all(isinstance(value, bool) for value in (*capabilities, contract.execution_allowed)):
        raise RunContractError("APPROVAL_PERMISSION_ESCALATION")
    if len(set(capabilities)) != 1:
        raise RunContractError("APPROVAL_CAPABILITY_INSUFFICIENT")
    if contract.execution_allowed and not all(capabilities):
        raise RunContractError("APPROVAL_CAPABILITY_INSUFFICIENT")
    if contract.maximum_processing_calls != 1 or contract.maximum_payload_open_sessions != 1:
        raise RunContractError("RUN_ID_ALREADY_USED")


@dataclass
class ExecutionCounters:
    maximum_processing_calls: int = 1
    maximum_payload_open_sessions: int = 1
    approval_issue_calls: int = 0
    approval_consume_calls: int = 0
    runtime_request_creations: int = 0
    runtime_execution_gate_activations: int = 0
    processing_engine_calls: int = 0
    payload_sessions: int = 0
    zip_entry_opens: int = 0
    archive_member_enumerations: int = 0
    json_parser_calls: int = 0
    record_parser_calls: int = 0
    join_calls: int = 0
    policy_dispatch_calls: int = 0
    output_writer_calls: int = 0
    checksum_calls: int = 0
    atomic_finalization_calls: int = 0
    active_payload_sessions: int = 0

    @property
    def processing_calls(self) -> int:
        return self.processing_engine_calls

    @property
    def payload_open_sessions(self) -> int:
        return self.payload_sessions

    def increment(self, name: str) -> None:
        allowed = set(self.snapshot())
        if name not in allowed:
            raise RunContractError("RUNTIME_COUNTER_UNKNOWN")
        value = getattr(self, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RunContractError("RUNTIME_COUNTER_INVALID")
        setattr(self, name, value + 1)

    def snapshot(self) -> dict[str, int]:
        names = (
            "approval_issue_calls", "approval_consume_calls",
            "runtime_request_creations", "runtime_execution_gate_activations",
            "processing_engine_calls", "payload_sessions", "zip_entry_opens",
            "archive_member_enumerations", "json_parser_calls", "record_parser_calls",
            "join_calls", "policy_dispatch_calls", "output_writer_calls",
            "checksum_calls", "atomic_finalization_calls",
        )
        result = {name: getattr(self, name) for name in names}
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in result.values()):
            raise RunContractError("RUNTIME_COUNTER_INVALID")
        return result

    def begin_processing(self) -> None:
        if self.processing_engine_calls >= self.maximum_processing_calls:
            raise RunContractError("PROCESSING_CALL_LIMIT_EXCEEDED")
        self.increment("processing_engine_calls")

    def open_payload_session(self) -> None:
        if self.active_payload_sessions:
            raise RunContractError("PAYLOAD_SESSION_ALREADY_ACTIVE")
        if self.payload_sessions >= self.maximum_payload_open_sessions:
            raise RunContractError("PAYLOAD_SESSION_LIMIT_EXCEEDED")
        self.increment("payload_sessions")
        self.active_payload_sessions = 1

    def close_payload_session(self) -> None:
        if self.active_payload_sessions != 1:
            raise RunContractError("PAYLOAD_SESSION_NOT_ACTIVE")
        self.active_payload_sessions = 0

    def validate_closed(self) -> None:
        if self.active_payload_sessions:
            raise RunContractError("PAYLOAD_SESSION_NOT_CLOSED")


@contextmanager
def payload_session(counters: ExecutionCounters):
    counters.open_payload_session()
    try:
        yield
    finally:
        counters.close_payload_session()


@dataclass
class RunRegistry:
    states: dict[str, str] = field(default_factory=lambda: dict(RETIRED_RUN_STATES))

    def register(self, run_id: str, state: str) -> None:
        if run_id in self.states:
            raise RunContractError("RUN_ID_ALREADY_USED")
        if state not in RUN_STATES:
            raise RunContractError("RUN_STATE_INVALID")
        self.states[run_id] = state

    def transition(self, run_id: str, expected: str, target: str) -> None:
        if target not in RUN_STATES or self.states.get(run_id) != expected:
            raise RunContractError("RUN_STATE_TRANSITION_INVALID")
        self.states[run_id] = target

    def snapshot(self) -> Mapping[str, str]:
        return dict(sorted(self.states.items()))
