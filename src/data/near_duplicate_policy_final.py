"""Pure, fail-closed policy for aggregate AIHUB-71748 near-duplicate candidates."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.data.near_duplicate_policy import (
    ANSWER_NEAR_DUPLICATE,
    BLOCKED_CANDIDATE_THRESHOLD,
    CROSS_SPLIT_NEAR_DUPLICATE,
    QA_PAIR_NEAR_DUPLICATE,
    QUESTION_NEAR_DUPLICATE,
    REVIEW_CANDIDATE_THRESHOLD,
    THRESHOLD_STATUS,
)


REVIEW_BAND_0_90_TO_0_93 = "0.90-0.93"
REVIEW_BAND_0_93_TO_0_97 = "0.93-0.97"
BLOCKED_PROPOSAL_BAND_0_97_TO_1_00 = "0.97-1.00"

_KNOWN_TYPES = frozenset(
    {
        QUESTION_NEAR_DUPLICATE,
        ANSWER_NEAR_DUPLICATE,
        QA_PAIR_NEAR_DUPLICATE,
        CROSS_SPLIT_NEAR_DUPLICATE,
    }
)
_KNOWN_BANDS = frozenset(
    {
        REVIEW_BAND_0_90_TO_0_93,
        REVIEW_BAND_0_93_TO_0_97,
        BLOCKED_PROPOSAL_BAND_0_97_TO_1_00,
    }
)


class NearDuplicateFinalPolicyError(ValueError):
    """Policy input is outside the approved design-only contract."""


@dataclass(frozen=True)
class NearDuplicateFinalPolicyDecision:
    policy_label: str
    processing_candidate: str
    reason_code: str
    duplicate_type: str
    similarity_band: str
    cross_split: bool
    threshold_status: str = THRESHOLD_STATUS
    automatic_processing: bool = False
    review_required: bool = True
    dataset_processing_approved: bool = False


def similarity_band_for_score(similarity: float) -> str:
    """Map a synthetic score to a proposal band without approving a threshold."""

    if isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
        raise NearDuplicateFinalPolicyError("INVALID_SIMILARITY")
    score = float(similarity)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise NearDuplicateFinalPolicyError("INVALID_SIMILARITY")
    if score < REVIEW_CANDIDATE_THRESHOLD:
        raise NearDuplicateFinalPolicyError("BELOW_PROPOSAL_THRESHOLD")
    if score == 1.0:
        raise NearDuplicateFinalPolicyError("EXACT_SIMILARITY_NOT_NEAR_DUPLICATE")
    if score < 0.93:
        return REVIEW_BAND_0_90_TO_0_93
    if score < BLOCKED_CANDIDATE_THRESHOLD:
        return REVIEW_BAND_0_93_TO_0_97
    return BLOCKED_PROPOSAL_BAND_0_97_TO_1_00


def evaluate_near_duplicate_final_policy(
    duplicate_type: str,
    similarity_band: str,
    cross_split: bool,
) -> NearDuplicateFinalPolicyDecision:
    """Return a review-only proposal and never mutate or select records."""

    if not isinstance(duplicate_type, str) or duplicate_type not in _KNOWN_TYPES:
        raise NearDuplicateFinalPolicyError("UNKNOWN_NEAR_DUPLICATE_TYPE")
    if not isinstance(similarity_band, str) or similarity_band not in _KNOWN_BANDS:
        raise NearDuplicateFinalPolicyError("UNKNOWN_SIMILARITY_BAND")
    if not isinstance(cross_split, bool):
        raise NearDuplicateFinalPolicyError("INVALID_CROSS_SPLIT_FLAG")
    if duplicate_type == CROSS_SPLIT_NEAR_DUPLICATE and not cross_split:
        raise NearDuplicateFinalPolicyError("CROSS_SPLIT_FLAG_REQUIRED")
    if duplicate_type != CROSS_SPLIT_NEAR_DUPLICATE and cross_split:
        raise NearDuplicateFinalPolicyError("CROSS_SPLIT_TYPE_REQUIRED")

    candidates = {
        QUESTION_NEAR_DUPLICATE: "question_review_candidate",
        ANSWER_NEAR_DUPLICATE: "answer_review_candidate",
        QA_PAIR_NEAR_DUPLICATE: "canonical_or_merge_review_candidate",
        CROSS_SPLIT_NEAR_DUPLICATE: (
            "training_keep_and_validation_exclusion_candidate"
        ),
    }
    reason_codes = {
        QUESTION_NEAR_DUPLICATE: "QUESTION_NEAR_DUPLICATE_REVIEW_REQUIRED",
        ANSWER_NEAR_DUPLICATE: "ANSWER_NEAR_DUPLICATE_REVIEW_REQUIRED",
        QA_PAIR_NEAR_DUPLICATE: "QA_PAIR_NEAR_DUPLICATE_REVIEW_REQUIRED",
        CROSS_SPLIT_NEAR_DUPLICATE: "CROSS_SPLIT_NEAR_DUPLICATE_REVIEW_REQUIRED",
    }
    if similarity_band == BLOCKED_PROPOSAL_BAND_0_97_TO_1_00:
        reason_code = f"{reason_codes[duplicate_type]}_BLOCKED_PROPOSAL_BAND"
    else:
        reason_code = reason_codes[duplicate_type]

    return NearDuplicateFinalPolicyDecision(
        policy_label="REVIEW_REQUIRED",
        processing_candidate=candidates[duplicate_type],
        reason_code=reason_code,
        duplicate_type=duplicate_type,
        similarity_band=similarity_band,
        cross_split=cross_split,
    )
