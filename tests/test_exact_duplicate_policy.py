from dataclasses import FrozenInstanceError

import pytest

from src.data.exact_duplicate_policy import (
    ANSWER_REUSE,
    CROSS_SPLIT,
    CROSS_SPLIT_DUPLICATE,
    EXACT_QA_DUPLICATE,
    QUESTION_CONFLICT,
    ExactDuplicatePolicyError,
    evaluate_exact_duplicate_policy,
)


def test_exact_qa_duplicate_is_only_a_canonical_candidate() -> None:
    decision = evaluate_exact_duplicate_policy(EXACT_QA_DUPLICATE)

    assert decision.policy_label == "CANONICAL_CANDIDATE"
    assert decision.processing_candidate == (
        "canonical_candidate",
        "remove_duplicate_candidate",
    )
    assert decision.reason_code == "EXACT_QA_REQUIRES_CANONICAL_SELECTION"
    assert decision.automatic_processing is False
    assert decision.review_required is True


def test_answer_reuse_requires_context_review_without_automatic_deletion() -> None:
    decision = evaluate_exact_duplicate_policy(ANSWER_REUSE)

    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.processing_candidate == ("retain_candidate", "review_candidate")
    assert decision.reason_code == "ANSWER_REUSE_CONTEXT_UNKNOWN"
    assert decision.automatic_processing is False


def test_question_conflict_requires_manual_review() -> None:
    decision = evaluate_exact_duplicate_policy(QUESTION_CONFLICT)

    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.processing_candidate == ("manual_review_candidate",)
    assert decision.reason_code == "QUESTION_CONFLICT_REQUIRES_REVIEW"


def test_explicit_cross_split_duplicate_is_blocked() -> None:
    decision = evaluate_exact_duplicate_policy(CROSS_SPLIT_DUPLICATE)

    assert decision.policy_label == "BLOCKED"
    assert decision.processing_candidate == (
        "training_keep_candidate",
        "validation_exclusion_candidate",
    )
    assert decision.reason_code == "CROSS_SPLIT_REQUIRES_SEPARATE_APPROVAL"


@pytest.mark.parametrize(
    "duplicate_type",
    [EXACT_QA_DUPLICATE, QUESTION_CONFLICT, ANSWER_REUSE],
)
def test_cross_split_overlap_overrides_within_split_policy(duplicate_type: str) -> None:
    decision = evaluate_exact_duplicate_policy(duplicate_type, CROSS_SPLIT)

    assert decision.policy_label == "BLOCKED"
    assert decision.automatic_processing is False
    assert decision.review_required is True


def test_unknown_duplicate_type_fails_closed() -> None:
    with pytest.raises(ExactDuplicatePolicyError, match="^UNKNOWN_DUPLICATE_TYPE$"):
        evaluate_exact_duplicate_policy("UNKNOWN")


def test_unknown_overlap_type_fails_closed() -> None:
    with pytest.raises(ExactDuplicatePolicyError, match="^UNKNOWN_OVERLAP_TYPE$"):
        evaluate_exact_duplicate_policy(EXACT_QA_DUPLICATE, "UNKNOWN")


def test_non_string_input_fails_closed_without_echoing_input() -> None:
    with pytest.raises(ExactDuplicatePolicyError, match="^UNKNOWN_DUPLICATE_TYPE$"):
        evaluate_exact_duplicate_policy(None)  # type: ignore[arg-type]

    with pytest.raises(ExactDuplicatePolicyError, match="^UNKNOWN_DUPLICATE_TYPE$"):
        evaluate_exact_duplicate_policy([])  # type: ignore[arg-type]


def test_decision_is_immutable() -> None:
    decision = evaluate_exact_duplicate_policy(EXACT_QA_DUPLICATE)

    with pytest.raises(FrozenInstanceError):
        decision.policy_label = "KEEP"  # type: ignore[misc]


def test_every_supported_decision_disables_automatic_processing() -> None:
    for duplicate_type in (
        EXACT_QA_DUPLICATE,
        QUESTION_CONFLICT,
        ANSWER_REUSE,
        CROSS_SPLIT_DUPLICATE,
    ):
        decision = evaluate_exact_duplicate_policy(duplicate_type)
        assert decision.automatic_processing is False
        assert decision.review_required is True
