"""Run identity and fail-closed execution contract for SFT processing."""

from __future__ import annotations

from dataclasses import dataclass
import re


RETIRED_RUN_IDS = frozenset({"AIHUB-71748-SFT-PROCESSING-20260729-0001"})
RETIRED_APPROVAL_IDS = frozenset({"AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001"})
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
    processing_allowed: bool = False
    execution_allowed: bool = False


def validate_run_contract(contract: ProcessingRunContract) -> None:
    if contract.run_id in RETIRED_RUN_IDS:
        raise RunContractError("RUN_ID_RETIRED")
    if contract.approval_id in RETIRED_APPROVAL_IDS:
        raise RunContractError("APPROVAL_ID_ALREADY_USED")
    if not _RUN.fullmatch(contract.run_id) or not _APPROVAL.fullmatch(contract.approval_id):
        raise RunContractError("RUN_ID_ALREADY_USED")
    if any((contract.retry_allowed, contract.resume_allowed, contract.overwrite_allowed)):
        raise RunContractError("RUN_ID_ALREADY_USED")
    if contract.processing_allowed is not contract.execution_allowed:
        raise RunContractError("RUN_ID_ALREADY_USED")
