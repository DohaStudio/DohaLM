"""Run identity, registry, and single-use execution counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
import re
from typing import Mapping


RETIRED_RUN_IDS = frozenset({
    "AIHUB-71748-SFT-PROCESSING-20260729-0001",
    "AIHUB-71748-SFT-PROCESSING-20260729-0002",
})
RETIRED_APPROVAL_IDS = frozenset({
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001",
    "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002",
})
RUN_STATES = frozenset({
    "reserved", "preflight_passed", "approval_issued", "approval_consumed",
    "processing", "completed", "failed_closed_before_consumption",
    "failed_closed", "retired",
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
    permissions = (
        contract.processing_allowed,
        contract.payload_read_allowed,
        contract.output_write_allowed,
        contract.execution_allowed,
    )
    if len(set(permissions)) != 1:
        raise RunContractError("APPROVAL_PERMISSION_ESCALATION")
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
    states: dict[str, str] = field(default_factory=lambda: {
        run_id: "retired" for run_id in RETIRED_RUN_IDS
    })

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
