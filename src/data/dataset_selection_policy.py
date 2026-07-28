"""Pure, fail-closed policy for the AIHUB-71748 SFT selection review."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping


AIHUB_71748 = "AIHUB-71748"
SFT = "SFT"

CONDITIONALLY_SELECTED = "CONDITIONALLY_SELECTED"
DEFERRED = "DEFERRED"
REJECTED = "REJECTED"

COMPLETED = "completed"
REVIEW_REQUIRED = "review_required"
BLOCKED = "blocked"
NOT_STARTED = "not_started"

INVALID_APPROVAL_REQUEST = "INVALID_APPROVAL_REQUEST"
SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
JOIN_INTEGRITY_PASSED = "JOIN_INTEGRITY_PASSED"
SAFE_INSPECTOR_VALIDATED = "SAFE_INSPECTOR_VALIDATED"
PII_POLICY_PENDING = "PII_POLICY_PENDING"
DUPLICATE_POLICY_PENDING = "DUPLICATE_POLICY_PENDING"
LEAKAGE_POLICY_PENDING = "LEAKAGE_POLICY_PENDING"
TERMS_EVIDENCE_PENDING = "TERMS_EVIDENCE_PENDING"
BENCHMARK_SOURCE_PENDING = "BENCHMARK_SOURCE_PENDING"
BENCHMARK_CONTAMINATION_UNDETERMINED = "BENCHMARK_CONTAMINATION_UNDETERMINED"
PROCESSING_MANIFEST_PENDING = "PROCESSING_MANIFEST_PENDING"
PROCESSING_BACKEND_PENDING = "PROCESSING_BACKEND_PENDING"

REQUIRED_READINESS = (
    "schema",
    "join",
    "safe_inspector",
    "component_consistency",
    "pii",
    "exact_duplicate",
    "near_duplicate",
    "leakage",
    "license",
    "benchmark",
    "dataset_processing",
)

CURRENT_SELECTION_CONDITIONS = (
    "sft_usage_evidence_not_finalized",
    "pii_threshold_not_approved",
    "duplicate_processing_not_approved",
    "leakage_processing_not_approved",
    "benchmark_source_not_available",
    "benchmark_contamination_not_determined",
    "dataset_processing_not_approved",
)

_DECISIONS = frozenset({CONDITIONALLY_SELECTED, DEFERRED, REJECTED})
_READINESS_STATUSES = frozenset({COMPLETED, REVIEW_REQUIRED, BLOCKED, NOT_STARTED})
_CONDITIONS = frozenset(CURRENT_SELECTION_CONDITIONS)
_COMMIT_LENGTH = 40

_REASON_ORDER = (
    SCHEMA_VALIDATED,
    JOIN_INTEGRITY_PASSED,
    SAFE_INSPECTOR_VALIDATED,
    PII_POLICY_PENDING,
    DUPLICATE_POLICY_PENDING,
    LEAKAGE_POLICY_PENDING,
    TERMS_EVIDENCE_PENDING,
    BENCHMARK_SOURCE_PENDING,
    BENCHMARK_CONTAMINATION_UNDETERMINED,
    PROCESSING_MANIFEST_PENDING,
    PROCESSING_BACKEND_PENDING,
)


@dataclass(frozen=True)
class DatasetSelectionDecision:
    """Immutable recommendation that never grants downstream execution rights."""

    recommendation: str
    requested_decision: str
    decision_allowed: bool
    processing_allowed: bool
    training_allowed: bool
    execution_allowed: bool
    reason_codes: tuple[str, ...]


def _invalid(requested_decision: object) -> DatasetSelectionDecision:
    return DatasetSelectionDecision(
        recommendation=DEFERRED,
        requested_decision="INVALID",
        decision_allowed=False,
        processing_allowed=False,
        training_allowed=False,
        execution_allowed=False,
        reason_codes=(INVALID_APPROVAL_REQUEST,),
    )


def _is_commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _COMMIT_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _reason_codes(
    statuses: Mapping[str, str],
    conditions: frozenset[str],
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if statuses["schema"] == COMPLETED:
        reasons.add(SCHEMA_VALIDATED)
    if statuses["join"] == COMPLETED:
        reasons.add(JOIN_INTEGRITY_PASSED)
    if statuses["safe_inspector"] == COMPLETED:
        reasons.add(SAFE_INSPECTOR_VALIDATED)

    if statuses["pii"] != COMPLETED or "pii_threshold_not_approved" in conditions:
        reasons.add(PII_POLICY_PENDING)
    if (
        statuses["exact_duplicate"] != COMPLETED
        or statuses["near_duplicate"] != COMPLETED
        or "duplicate_processing_not_approved" in conditions
    ):
        reasons.add(DUPLICATE_POLICY_PENDING)
    if statuses["leakage"] != COMPLETED or "leakage_processing_not_approved" in conditions:
        reasons.add(LEAKAGE_POLICY_PENDING)
    if statuses["license"] != COMPLETED or "sft_usage_evidence_not_finalized" in conditions:
        reasons.add(TERMS_EVIDENCE_PENDING)
    if statuses["benchmark"] != COMPLETED or "benchmark_source_not_available" in conditions:
        reasons.add(BENCHMARK_SOURCE_PENDING)
    if "benchmark_contamination_not_determined" in conditions:
        reasons.add(BENCHMARK_CONTAMINATION_UNDETERMINED)
    if statuses["dataset_processing"] != COMPLETED or "dataset_processing_not_approved" in conditions:
        reasons.update({PROCESSING_MANIFEST_PENDING, PROCESSING_BACKEND_PENDING})
    return tuple(reason for reason in _REASON_ORDER if reason in reasons)


def evaluate_dataset_selection_policy(
    readiness_statuses: Mapping[str, str],
    selection_conditions: Iterable[str],
    requested_decision: str,
    *,
    dataset_id: str = AIHUB_71748,
    component: str = SFT,
    evidence_commit: str | None = None,
    final_approval_requested: bool = False,
    processing_allowed: bool = False,
    training_allowed: bool = False,
    execution_allowed: bool = False,
) -> DatasetSelectionDecision:
    """Evaluate fixed aggregate statuses without accessing data or granting approval."""

    try:
        statuses = MappingProxyType(dict(readiness_statuses))
        conditions = frozenset(selection_conditions)
    except (TypeError, ValueError):
        return _invalid(requested_decision)

    invalid = (
        dataset_id != AIHUB_71748
        or component != SFT
        or not isinstance(requested_decision, str)
        or requested_decision not in _DECISIONS
        or set(statuses) != set(REQUIRED_READINESS)
        or any(
            not isinstance(status, str) or status not in _READINESS_STATUSES
            for status in statuses.values()
        )
        or not conditions.issubset(_CONDITIONS)
        or processing_allowed is not False
        or training_allowed is not False
        or execution_allowed is not False
        or not isinstance(final_approval_requested, bool)
        or (evidence_commit is not None and not _is_commit(evidence_commit))
        or (final_approval_requested and not _is_commit(evidence_commit))
    )
    if invalid:
        return _invalid(requested_decision)

    structural_evidence_complete = all(
        statuses[key] == COMPLETED
        for key in ("schema", "join", "safe_inspector", "component_consistency")
    )
    if not structural_evidence_complete:
        return _invalid(requested_decision)

    return DatasetSelectionDecision(
        recommendation=CONDITIONALLY_SELECTED,
        requested_decision=requested_decision,
        decision_allowed=True,
        processing_allowed=False,
        training_allowed=False,
        execution_allowed=False,
        reason_codes=_reason_codes(statuses, conditions),
    )
