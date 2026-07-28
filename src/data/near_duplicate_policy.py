"""Near duplicate 후보를 자동 처리 없이 검토 상태로 제한하는 순수 정책."""

from __future__ import annotations

from dataclasses import dataclass
import math


QUESTION_NEAR_DUPLICATE = "QUESTION_NEAR_DUPLICATE"
ANSWER_NEAR_DUPLICATE = "ANSWER_NEAR_DUPLICATE"
QA_PAIR_NEAR_DUPLICATE = "QA_PAIR_NEAR_DUPLICATE"
CROSS_SPLIT_NEAR_DUPLICATE = "CROSS_SPLIT_NEAR_DUPLICATE"

REVIEW_CANDIDATE_THRESHOLD = 0.90
BLOCKED_CANDIDATE_THRESHOLD = 0.97
THRESHOLD_STATUS = "not_approved"

_KNOWN_TYPES = frozenset(
    {
        QUESTION_NEAR_DUPLICATE,
        ANSWER_NEAR_DUPLICATE,
        QA_PAIR_NEAR_DUPLICATE,
        CROSS_SPLIT_NEAR_DUPLICATE,
    }
)


class NearDuplicatePolicyError(ValueError):
    """정책 입력이 고정 계약을 벗어났음을 나타낸다."""


@dataclass(frozen=True)
class NearDuplicatePolicyDecision:
    policy_label: str
    processing_candidate: str
    reason_code: str
    threshold_status: str = THRESHOLD_STATUS
    automatic_processing: bool = False
    review_required: bool = True


def evaluate_near_duplicate_policy(
    duplicate_type: str,
    similarity: float,
) -> NearDuplicatePolicyDecision:
    """Proposal threshold 이상 후보만 REVIEW_REQUIRED로 분류한다."""

    if not isinstance(duplicate_type, str) or duplicate_type not in _KNOWN_TYPES:
        raise NearDuplicatePolicyError("UNKNOWN_NEAR_DUPLICATE_TYPE")
    if isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
        raise NearDuplicatePolicyError("INVALID_SIMILARITY")
    score = float(similarity)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise NearDuplicatePolicyError("INVALID_SIMILARITY")
    if score < REVIEW_CANDIDATE_THRESHOLD:
        raise NearDuplicatePolicyError("BELOW_PROPOSAL_THRESHOLD")

    candidate = (
        "blocked_candidate"
        if score >= BLOCKED_CANDIDATE_THRESHOLD
        else "review_candidate"
    )
    reason_codes = {
        QUESTION_NEAR_DUPLICATE: "QUESTION_SIMILARITY_REQUIRES_REVIEW",
        ANSWER_NEAR_DUPLICATE: "ANSWER_SIMILARITY_REQUIRES_REVIEW",
        QA_PAIR_NEAR_DUPLICATE: "QA_PAIR_SIMILARITY_REQUIRES_REVIEW",
        CROSS_SPLIT_NEAR_DUPLICATE: "CROSS_SPLIT_SIMILARITY_REQUIRES_REVIEW",
    }
    return NearDuplicatePolicyDecision(
        policy_label="REVIEW_REQUIRED",
        processing_candidate=candidate,
        reason_code=reason_codes[duplicate_type],
    )
