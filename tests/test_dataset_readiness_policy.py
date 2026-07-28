from dataclasses import FrozenInstanceError

import pytest

from src.data.dataset_readiness_policy import (
    BENCHMARK,
    BENCHMARK_CONTAMINATION_CANDIDATE,
    CANDIDATES_DETECTED,
    COMPLETED,
    EVALUATION_PROMPT_LEAK,
    EXACT_DUPLICATE,
    JOIN,
    LEAKAGE,
    LICENSE,
    MODEL_EVALUATION_LEAK,
    NEAR_DUPLICATE,
    NO_CANDIDATES,
    NOT_APPROVED,
    NOT_AVAILABLE_LOCAL,
    PII,
    PROCESSING,
    SCHEMA,
    TRAINING,
    TRAIN_VALIDATION_ANSWER_LEAK,
    TRAIN_VALIDATION_QA_LEAK,
    TRAIN_VALIDATION_QUESTION_LEAK,
    VERIFICATION_REQUIRED,
    DatasetReadinessPolicyError,
    evaluate_dataset_readiness_policy,
)


@pytest.mark.parametrize("policy_type", [SCHEMA, JOIN])
def test_completed_structural_contracts_are_completed(policy_type: str) -> None:
    decision = evaluate_dataset_readiness_policy(COMPLETED, policy_type)
    assert decision.status == "completed"
    assert decision.review_required is False
    assert decision.execution_allowed is False


@pytest.mark.parametrize("policy_type", [PII, EXACT_DUPLICATE, NEAR_DUPLICATE, LEAKAGE])
def test_completed_scans_still_require_processing_review(policy_type: str) -> None:
    decision = evaluate_dataset_readiness_policy(COMPLETED, policy_type)
    assert decision.status == "review_required"
    assert decision.processing_candidate == "REVIEW_REQUIRED"
    assert decision.dataset_processing_approved is False


def test_missing_local_benchmark_blocks_readiness_without_download() -> None:
    decision = evaluate_dataset_readiness_policy(NOT_AVAILABLE_LOCAL, BENCHMARK)
    assert decision.status == "blocked"
    assert decision.processing_candidate == "UNRESOLVED"
    assert decision.reason == "BENCHMARK_SOURCE_NOT_AVAILABLE_LOCAL"


def test_license_processing_and_training_remain_fail_closed() -> None:
    license_decision = evaluate_dataset_readiness_policy(
        VERIFICATION_REQUIRED,
        LICENSE,
    )
    assert license_decision.status == "review_required"
    for policy_type in (PROCESSING, TRAINING):
        decision = evaluate_dataset_readiness_policy(NOT_APPROVED, policy_type)
        assert decision.status == "not_started"
        assert decision.processing_candidate == "BLOCKED"
        assert decision.execution_allowed is False


@pytest.mark.parametrize(
    ("policy_type", "status", "candidate"),
    [
        (TRAIN_VALIDATION_QUESTION_LEAK, "review_required", "VALIDATION_EXCLUSION_CANDIDATE"),
        (TRAIN_VALIDATION_ANSWER_LEAK, "review_required", "REVIEW_REQUIRED"),
        (TRAIN_VALIDATION_QA_LEAK, "blocked", "VALIDATION_EXCLUSION_CANDIDATE"),
        (EVALUATION_PROMPT_LEAK, "blocked", "BLOCKED"),
        (MODEL_EVALUATION_LEAK, "blocked", "BLOCKED"),
        (BENCHMARK_CONTAMINATION_CANDIDATE, "blocked", "BLOCKED"),
    ],
)
def test_leakage_candidates_never_trigger_automatic_processing(
    policy_type: str,
    status: str,
    candidate: str,
) -> None:
    decision = evaluate_dataset_readiness_policy(CANDIDATES_DETECTED, policy_type)
    assert decision.status == status
    assert decision.processing_candidate == candidate
    assert decision.automatic_processing is False
    assert decision.dataset_selection_approved is False
    assert decision.dataset_processing_approved is False
    assert decision.execution_allowed is False


def test_answer_exact_candidate_requires_context_review() -> None:
    decision = evaluate_dataset_readiness_policy(
        CANDIDATES_DETECTED,
        TRAIN_VALIDATION_ANSWER_LEAK,
    )
    assert decision.policy_risk == "review_candidate"
    assert decision.reason == "ANSWER_CONTEXT_UNKNOWN_REVIEW_REQUIRED"
    assert decision.processing_candidate == "REVIEW_REQUIRED"


def test_no_prompt_candidate_is_not_a_dataset_approval() -> None:
    decision = evaluate_dataset_readiness_policy(
        NO_CANDIDATES,
        EVALUATION_PROMPT_LEAK,
    )
    assert decision.status == "completed"
    assert decision.review_required is False
    assert decision.dataset_selection_approved is False
    assert decision.execution_allowed is False


def test_benchmark_unavailable_is_distinct_from_no_candidate() -> None:
    decision = evaluate_dataset_readiness_policy(
        NOT_AVAILABLE_LOCAL,
        BENCHMARK_CONTAMINATION_CANDIDATE,
    )
    assert decision.status == "blocked"
    assert decision.processing_candidate == "UNRESOLVED"


@pytest.mark.parametrize(
    ("scan_result", "policy_type", "error_code"),
    [
        (COMPLETED, "unknown", "UNKNOWN_POLICY_TYPE"),
        ("unknown", SCHEMA, "UNKNOWN_SCAN_RESULT"),
        (NOT_APPROVED, SCHEMA, "INCOMPATIBLE_SCAN_RESULT"),
        (COMPLETED, TRAIN_VALIDATION_QA_LEAK, "INCOMPATIBLE_SCAN_RESULT"),
        (NOT_AVAILABLE_LOCAL, EVALUATION_PROMPT_LEAK, "INCOMPATIBLE_SCAN_RESULT"),
    ],
)
def test_unknown_or_incompatible_state_fails_closed(
    scan_result: str,
    policy_type: str,
    error_code: str,
) -> None:
    with pytest.raises(DatasetReadinessPolicyError, match=f"^{error_code}$"):
        evaluate_dataset_readiness_policy(scan_result, policy_type)


def test_non_string_input_fails_without_echoing_payload() -> None:
    with pytest.raises(DatasetReadinessPolicyError, match="^UNKNOWN_POLICY_TYPE$"):
        evaluate_dataset_readiness_policy(COMPLETED, object())  # type: ignore[arg-type]
    with pytest.raises(DatasetReadinessPolicyError, match="^UNKNOWN_SCAN_RESULT$"):
        evaluate_dataset_readiness_policy(object(), SCHEMA)  # type: ignore[arg-type]


def test_decision_is_immutable() -> None:
    decision = evaluate_dataset_readiness_policy(COMPLETED, SCHEMA)
    with pytest.raises(FrozenInstanceError):
        decision.status = "blocked"  # type: ignore[misc]
