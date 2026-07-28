from dataclasses import FrozenInstanceError
import math

import pytest

from src.data.near_duplicate_policy import (
    ANSWER_NEAR_DUPLICATE,
    CROSS_SPLIT_NEAR_DUPLICATE,
    QA_PAIR_NEAR_DUPLICATE,
    QUESTION_NEAR_DUPLICATE,
    NearDuplicatePolicyError,
    evaluate_near_duplicate_policy,
)


@pytest.mark.parametrize(
    "duplicate_type",
    [
        QUESTION_NEAR_DUPLICATE,
        ANSWER_NEAR_DUPLICATE,
        QA_PAIR_NEAR_DUPLICATE,
        CROSS_SPLIT_NEAR_DUPLICATE,
    ],
)
def test_all_supported_types_require_review(duplicate_type: str) -> None:
    decision = evaluate_near_duplicate_policy(duplicate_type, 0.95)
    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.processing_candidate == "review_candidate"
    assert decision.threshold_status == "not_approved"
    assert decision.automatic_processing is False
    assert decision.review_required is True


def test_blocked_band_is_still_review_only() -> None:
    decision = evaluate_near_duplicate_policy(CROSS_SPLIT_NEAR_DUPLICATE, 0.97)
    assert decision.processing_candidate == "blocked_candidate"
    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.automatic_processing is False


def test_unknown_type_fails_closed() -> None:
    with pytest.raises(NearDuplicatePolicyError, match="^UNKNOWN_NEAR_DUPLICATE_TYPE$"):
        evaluate_near_duplicate_policy("UNKNOWN", 0.99)


@pytest.mark.parametrize("score", [None, True, -0.1, 1.1, math.nan, math.inf])
def test_invalid_similarity_fails_closed(score: object) -> None:
    with pytest.raises(NearDuplicatePolicyError, match="^INVALID_SIMILARITY$"):
        evaluate_near_duplicate_policy(QUESTION_NEAR_DUPLICATE, score)  # type: ignore[arg-type]


def test_below_proposal_threshold_fails_closed() -> None:
    with pytest.raises(NearDuplicatePolicyError, match="^BELOW_PROPOSAL_THRESHOLD$"):
        evaluate_near_duplicate_policy(QUESTION_NEAR_DUPLICATE, 0.8999)


def test_decision_is_immutable() -> None:
    decision = evaluate_near_duplicate_policy(QUESTION_NEAR_DUPLICATE, 0.90)
    with pytest.raises(FrozenInstanceError):
        decision.policy_label = "KEEP"  # type: ignore[misc]
