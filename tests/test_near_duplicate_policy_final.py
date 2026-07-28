from dataclasses import FrozenInstanceError
import math

import pytest

from src.data.near_duplicate_policy import (
    ANSWER_NEAR_DUPLICATE,
    CROSS_SPLIT_NEAR_DUPLICATE,
    QA_PAIR_NEAR_DUPLICATE,
    QUESTION_NEAR_DUPLICATE,
)
from src.data.near_duplicate_policy_final import (
    BLOCKED_PROPOSAL_BAND_0_97_TO_1_00,
    REVIEW_BAND_0_90_TO_0_93,
    REVIEW_BAND_0_93_TO_0_97,
    NearDuplicateFinalPolicyError,
    evaluate_near_duplicate_final_policy,
    similarity_band_for_score,
)


@pytest.mark.parametrize(
    ("duplicate_type", "cross_split", "processing_candidate"),
    [
        (QUESTION_NEAR_DUPLICATE, False, "question_review_candidate"),
        (ANSWER_NEAR_DUPLICATE, False, "answer_review_candidate"),
        (QA_PAIR_NEAR_DUPLICATE, False, "canonical_or_merge_review_candidate"),
        (
            CROSS_SPLIT_NEAR_DUPLICATE,
            True,
            "training_keep_and_validation_exclusion_candidate",
        ),
    ],
)
def test_all_types_are_review_only(
    duplicate_type: str,
    cross_split: bool,
    processing_candidate: str,
) -> None:
    decision = evaluate_near_duplicate_final_policy(
        duplicate_type,
        REVIEW_BAND_0_93_TO_0_97,
        cross_split,
    )
    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.processing_candidate == processing_candidate
    assert decision.threshold_status == "not_approved"
    assert decision.automatic_processing is False
    assert decision.review_required is True
    assert decision.dataset_processing_approved is False


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.90, REVIEW_BAND_0_90_TO_0_93),
        (0.95, REVIEW_BAND_0_93_TO_0_97),
        (0.98, BLOCKED_PROPOSAL_BAND_0_97_TO_1_00),
    ],
)
def test_proposal_score_bands(score: float, expected: str) -> None:
    assert similarity_band_for_score(score) == expected


def test_blocked_proposal_band_remains_review_required() -> None:
    decision = evaluate_near_duplicate_final_policy(
        CROSS_SPLIT_NEAR_DUPLICATE,
        BLOCKED_PROPOSAL_BAND_0_97_TO_1_00,
        True,
    )
    assert decision.policy_label == "REVIEW_REQUIRED"
    assert decision.processing_candidate == (
        "training_keep_and_validation_exclusion_candidate"
    )
    assert decision.reason_code.endswith("BLOCKED_PROPOSAL_BAND")


@pytest.mark.parametrize(
    ("duplicate_type", "band", "cross_split", "error_code"),
    [
        ("UNKNOWN", REVIEW_BAND_0_90_TO_0_93, False, "UNKNOWN_NEAR_DUPLICATE_TYPE"),
        (QUESTION_NEAR_DUPLICATE, "UNKNOWN", False, "UNKNOWN_SIMILARITY_BAND"),
        (QUESTION_NEAR_DUPLICATE, REVIEW_BAND_0_90_TO_0_93, True, "CROSS_SPLIT_TYPE_REQUIRED"),
        (CROSS_SPLIT_NEAR_DUPLICATE, REVIEW_BAND_0_90_TO_0_93, False, "CROSS_SPLIT_FLAG_REQUIRED"),
        (QUESTION_NEAR_DUPLICATE, REVIEW_BAND_0_90_TO_0_93, None, "INVALID_CROSS_SPLIT_FLAG"),
    ],
)
def test_invalid_contract_fails_closed(
    duplicate_type: str,
    band: str,
    cross_split: object,
    error_code: str,
) -> None:
    with pytest.raises(NearDuplicateFinalPolicyError, match=f"^{error_code}$"):
        evaluate_near_duplicate_final_policy(
            duplicate_type,
            band,
            cross_split,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("score", [None, True, -0.1, 0.8999, 1.0, 1.1, math.nan, math.inf])
def test_invalid_or_non_near_score_fails_closed(score: object) -> None:
    with pytest.raises(NearDuplicateFinalPolicyError):
        similarity_band_for_score(score)  # type: ignore[arg-type]


def test_decision_is_immutable() -> None:
    decision = evaluate_near_duplicate_final_policy(
        QUESTION_NEAR_DUPLICATE,
        REVIEW_BAND_0_90_TO_0_93,
        False,
    )
    with pytest.raises(FrozenInstanceError):
        decision.policy_label = "KEEP"  # type: ignore[misc]
