"""Pure, fail-closed AIHUB-71748 leakage and Dataset readiness policy."""

from __future__ import annotations

from dataclasses import dataclass


TRAIN_VALIDATION_QUESTION_LEAK = "TRAIN_VALIDATION_QUESTION_LEAK"
TRAIN_VALIDATION_ANSWER_LEAK = "TRAIN_VALIDATION_ANSWER_LEAK"
TRAIN_VALIDATION_QA_LEAK = "TRAIN_VALIDATION_QA_LEAK"
EVALUATION_PROMPT_LEAK = "EVALUATION_PROMPT_LEAK"
MODEL_EVALUATION_LEAK = "MODEL_EVALUATION_LEAK"
BENCHMARK_CONTAMINATION_CANDIDATE = "BENCHMARK_CONTAMINATION_CANDIDATE"

SCHEMA = "schema"
JOIN = "join"
PII = "pii"
EXACT_DUPLICATE = "exact_duplicate"
NEAR_DUPLICATE = "near_duplicate"
LEAKAGE = "leakage"
BENCHMARK = "benchmark"
LICENSE = "license"
PROCESSING = "processing"
TRAINING = "training"

COMPLETED = "completed"
CANDIDATES_DETECTED = "candidates_detected"
NO_CANDIDATES = "no_candidates"
NOT_AVAILABLE_LOCAL = "not_available_local"
VERIFICATION_REQUIRED = "verification_required"
NOT_APPROVED = "not_approved"

_LEAKAGE_TYPES = frozenset(
    {
        TRAIN_VALIDATION_QUESTION_LEAK,
        TRAIN_VALIDATION_ANSWER_LEAK,
        TRAIN_VALIDATION_QA_LEAK,
        EVALUATION_PROMPT_LEAK,
        MODEL_EVALUATION_LEAK,
        BENCHMARK_CONTAMINATION_CANDIDATE,
    }
)
_READINESS_TYPES = frozenset(
    {
        SCHEMA,
        JOIN,
        PII,
        EXACT_DUPLICATE,
        NEAR_DUPLICATE,
        LEAKAGE,
        BENCHMARK,
        LICENSE,
        PROCESSING,
        TRAINING,
    }
)
_ALL_TYPES = _LEAKAGE_TYPES | _READINESS_TYPES
_ALL_RESULTS = frozenset(
    {
        COMPLETED,
        CANDIDATES_DETECTED,
        NO_CANDIDATES,
        NOT_AVAILABLE_LOCAL,
        VERIFICATION_REQUIRED,
        NOT_APPROVED,
    }
)


class DatasetReadinessPolicyError(ValueError):
    """Policy input is outside the approved aggregate-only vocabulary."""


@dataclass(frozen=True)
class DatasetReadinessDecision:
    """Review-only decision that never authorizes Dataset processing."""

    status: str
    reason: str
    processing_candidate: str
    policy_risk: str
    automatic_processing: bool = False
    review_required: bool = True
    dataset_selection_approved: bool = False
    dataset_processing_approved: bool = False
    execution_allowed: bool = False


def _decision(
    status: str,
    reason: str,
    processing_candidate: str,
    policy_risk: str,
    *,
    review_required: bool = True,
) -> DatasetReadinessDecision:
    return DatasetReadinessDecision(
        status=status,
        reason=reason,
        processing_candidate=processing_candidate,
        policy_risk=policy_risk,
        review_required=review_required,
    )


def _evaluate_leakage(
    scan_result: str,
    policy_type: str,
) -> DatasetReadinessDecision:
    if scan_result == NO_CANDIDATES:
        return _decision(
            COMPLETED,
            "NO_AGGREGATE_CANDIDATE_DETECTED",
            "KEEP",
            "none",
            review_required=False,
        )
    if policy_type == BENCHMARK_CONTAMINATION_CANDIDATE:
        if scan_result == NOT_AVAILABLE_LOCAL:
            return _decision(
                "blocked",
                "BENCHMARK_SOURCE_NOT_AVAILABLE_LOCAL",
                "UNRESOLVED",
                "block_candidate",
            )
        if scan_result == CANDIDATES_DETECTED:
            return _decision(
                "blocked",
                "BENCHMARK_CANDIDATE_REQUIRES_SEPARATE_REVIEW",
                "BLOCKED",
                "block_candidate",
            )
        raise DatasetReadinessPolicyError("INCOMPATIBLE_SCAN_RESULT")
    if scan_result != CANDIDATES_DETECTED:
        raise DatasetReadinessPolicyError("INCOMPATIBLE_SCAN_RESULT")

    mapping = {
        TRAIN_VALIDATION_QUESTION_LEAK: (
            "review_required",
            "QUESTION_CROSS_SPLIT_REVIEW_REQUIRED",
            "VALIDATION_EXCLUSION_CANDIDATE",
            "review_candidate",
        ),
        TRAIN_VALIDATION_ANSWER_LEAK: (
            "review_required",
            "ANSWER_CONTEXT_UNKNOWN_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
            "review_candidate",
        ),
        TRAIN_VALIDATION_QA_LEAK: (
            "blocked",
            "QA_CROSS_SPLIT_BLOCKS_DATASET_APPROVAL",
            "VALIDATION_EXCLUSION_CANDIDATE",
            "block_candidate",
        ),
        EVALUATION_PROMPT_LEAK: (
            "blocked",
            "EVALUATION_PROMPT_CANDIDATE_BLOCKS_APPROVAL",
            "BLOCKED",
            "block_candidate",
        ),
        MODEL_EVALUATION_LEAK: (
            "blocked",
            "MODEL_EVALUATION_CANDIDATE_BLOCKS_APPROVAL",
            "BLOCKED",
            "block_candidate",
        ),
    }
    status, reason, candidate, risk = mapping[policy_type]
    return _decision(status, reason, candidate, risk)


def _evaluate_readiness(
    scan_result: str,
    policy_type: str,
) -> DatasetReadinessDecision:
    expected = {
        SCHEMA: COMPLETED,
        JOIN: COMPLETED,
        PII: COMPLETED,
        EXACT_DUPLICATE: COMPLETED,
        NEAR_DUPLICATE: COMPLETED,
        LEAKAGE: COMPLETED,
        BENCHMARK: NOT_AVAILABLE_LOCAL,
        LICENSE: VERIFICATION_REQUIRED,
        PROCESSING: NOT_APPROVED,
        TRAINING: NOT_APPROVED,
    }
    if scan_result != expected[policy_type]:
        raise DatasetReadinessPolicyError("INCOMPATIBLE_SCAN_RESULT")

    if policy_type in {SCHEMA, JOIN}:
        return _decision(
            COMPLETED,
            f"{policy_type.upper()}_CONTRACT_COMPLETED",
            "KEEP",
            "none",
            review_required=False,
        )
    if policy_type in {PII, EXACT_DUPLICATE, NEAR_DUPLICATE, LEAKAGE}:
        return _decision(
            "review_required",
            f"{policy_type.upper()}_PROCESSING_POLICY_NOT_APPROVED",
            "REVIEW_REQUIRED",
            "review_candidate",
        )
    if policy_type == BENCHMARK:
        return _decision(
            "blocked",
            "BENCHMARK_SOURCE_NOT_AVAILABLE_LOCAL",
            "UNRESOLVED",
            "block_candidate",
        )
    if policy_type == LICENSE:
        return _decision(
            "review_required",
            "SFT_TERMS_VERIFICATION_REQUIRED",
            "REVIEW_REQUIRED",
            "review_candidate",
        )
    return _decision(
        "not_started",
        f"{policy_type.upper()}_NOT_APPROVED",
        "BLOCKED",
        "block_candidate",
    )


def evaluate_dataset_readiness_policy(
    scan_result: str,
    policy_type: str,
) -> DatasetReadinessDecision:
    """Map an aggregate status to a non-executing policy decision."""

    if not isinstance(policy_type, str) or policy_type not in _ALL_TYPES:
        raise DatasetReadinessPolicyError("UNKNOWN_POLICY_TYPE")
    if not isinstance(scan_result, str) or scan_result not in _ALL_RESULTS:
        raise DatasetReadinessPolicyError("UNKNOWN_SCAN_RESULT")
    if policy_type in _LEAKAGE_TYPES:
        return _evaluate_leakage(scan_result, policy_type)
    return _evaluate_readiness(scan_result, policy_type)
