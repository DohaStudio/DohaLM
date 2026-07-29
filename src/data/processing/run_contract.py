"""Run identity, registry, and single-use execution counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime
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
})
RETIRED_APPROVAL_IDS = frozenset({
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0003",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0004",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0005",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0006",
})
RETIRED_RUN_STATES = {
    "AIHUB-71748-SFT-PROCESSING-20260729-0001": "retired",
    "AIHUB-71748-SFT-PROCESSING-20260729-0002": "retired_failed_closed_before_consumption",
    "AIHUB-71748-SFT-PROCESSING-20260729-0003": "retired_failed_closed_before_approval",
    "AIHUB-71748-SFT-PROCESSING-20260729-0004": "retired_execution_source_tree_drift",
    "AIHUB-71748-SFT-PROCESSING-20260730-0005": "retired_preflight_validator_failure",
    "AIHUB-71748-SFT-PROCESSING-20260730-0006": "retired_approval_contract_failure",
}
RETIRED_APPROVAL_STATES = {
    approval_id: "retired_not_issued" for approval_id in RETIRED_APPROVAL_IDS
}
RUN_STATES = frozenset({
    "reserved", "preflight_passed", "approval_issued", "approval_consumed",
    "processing", "completed", "failed_closed_before_consumption",
    "failed_closed", "retired", *RETIRED_RUN_STATES.values(),
})
_RUN = re.compile(r"^AIHUB-71748-SFT-PROCESSING-\d{8}-\d{4}$")
_APPROVAL = re.compile(r"^AIHUB-71748-SFT-PROCESSING-APPROVAL-\d{8}-\d{4}$")


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


@dataclass(frozen=True)
class RuntimeExecutionRequest:
    run_id: str
    approval_id: str
    execution_allowed: bool
    maximum_processing_calls: int
    maximum_payload_open_sessions: int
    requested_at: str
    request_fingerprint: str = ""


def runtime_request_fingerprint(request: RuntimeExecutionRequest) -> str:
    payload = {
        **request.__dict__,
        "request_fingerprint": "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_runtime_request(
    request: RuntimeExecutionRequest,
    contract: ProcessingRunContract,
) -> None:
    if request.run_id != contract.run_id or request.approval_id != contract.approval_id:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
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
    if request.maximum_processing_calls != 1 or request.maximum_payload_open_sessions != 1:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    try:
        requested = datetime.fromisoformat(request.requested_at)
    except (TypeError, ValueError):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT") from None
    if requested.tzinfo is None or requested.utcoffset() is None:
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")
    if request.request_fingerprint != runtime_request_fingerprint(request):
        raise RunContractError("RUNTIME_PERMISSION_CONFLICT")


def validate_run_contract(contract: ProcessingRunContract) -> None:
    if contract.run_id in RETIRED_RUN_IDS:
        raise RunContractError("RUN_ID_RETIRED")
    if contract.approval_id in RETIRED_APPROVAL_IDS:
        raise RunContractError("APPROVAL_RETIRED")
    if not _RUN.fullmatch(contract.run_id) or not _APPROVAL.fullmatch(contract.approval_id):
        raise RunContractError("RUN_ID_ALREADY_USED")
    suffix = contract.run_id.rsplit("-", 2)[-2:]
    if contract.approval_id.rsplit("-", 2)[-2:] != suffix:
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
    processing_calls: int = 0
    payload_open_sessions: int = 0
    active_payload_sessions: int = 0

    def begin_processing(self) -> None:
        if self.processing_calls >= self.maximum_processing_calls:
            raise RunContractError("PROCESSING_CALL_LIMIT_EXCEEDED")
        self.processing_calls += 1

    def open_payload_session(self) -> None:
        if self.active_payload_sessions:
            raise RunContractError("PAYLOAD_SESSION_ALREADY_ACTIVE")
        if self.payload_open_sessions >= self.maximum_payload_open_sessions:
            raise RunContractError("PAYLOAD_SESSION_LIMIT_EXCEEDED")
        self.payload_open_sessions += 1
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
