"""Exact duplicate 검토 결과를 처리 후보로 분류하는 순수 정책 계층."""

from __future__ import annotations

from dataclasses import dataclass


EXACT_QA_DUPLICATE = "EXACT_QA_DUPLICATE"
QUESTION_CONFLICT = "QUESTION_CONFLICT"
ANSWER_REUSE = "ANSWER_REUSE"
CROSS_SPLIT_DUPLICATE = "CROSS_SPLIT_DUPLICATE"

WITHIN_SPLIT = "WITHIN_SPLIT"
CROSS_SPLIT = "CROSS_SPLIT"

_KNOWN_DUPLICATE_TYPES = frozenset(
    {
        EXACT_QA_DUPLICATE,
        QUESTION_CONFLICT,
        ANSWER_REUSE,
        CROSS_SPLIT_DUPLICATE,
    }
)
_KNOWN_OVERLAP_TYPES = frozenset({WITHIN_SPLIT, CROSS_SPLIT})


class ExactDuplicatePolicyError(ValueError):
    """정책 입력이 승인된 고정 vocabulary를 벗어났음을 나타낸다."""


@dataclass(frozen=True)
class ExactDuplicatePolicyDecision:
    """자동 처리 권한을 포함하지 않는 검토용 정책 결정."""

    policy_label: str
    processing_candidate: tuple[str, ...]
    reason_code: str
    automatic_processing: bool = False
    review_required: bool = True


def evaluate_exact_duplicate_policy(
    duplicate_type: str,
    overlap_type: str = WITHIN_SPLIT,
) -> ExactDuplicatePolicyDecision:
    """중복 분류를 검토 후보로 매핑하며 알 수 없는 입력은 Fail Closed한다."""

    if not isinstance(duplicate_type, str) or duplicate_type not in _KNOWN_DUPLICATE_TYPES:
        raise ExactDuplicatePolicyError("UNKNOWN_DUPLICATE_TYPE")
    if not isinstance(overlap_type, str) or overlap_type not in _KNOWN_OVERLAP_TYPES:
        raise ExactDuplicatePolicyError("UNKNOWN_OVERLAP_TYPE")

    if duplicate_type == CROSS_SPLIT_DUPLICATE or overlap_type == CROSS_SPLIT:
        return ExactDuplicatePolicyDecision(
            policy_label="BLOCKED",
            processing_candidate=(
                "training_keep_candidate",
                "validation_exclusion_candidate",
            ),
            reason_code="CROSS_SPLIT_REQUIRES_SEPARATE_APPROVAL",
        )

    if duplicate_type == EXACT_QA_DUPLICATE:
        return ExactDuplicatePolicyDecision(
            policy_label="CANONICAL_CANDIDATE",
            processing_candidate=(
                "canonical_candidate",
                "remove_duplicate_candidate",
            ),
            reason_code="EXACT_QA_REQUIRES_CANONICAL_SELECTION",
        )

    if duplicate_type == QUESTION_CONFLICT:
        return ExactDuplicatePolicyDecision(
            policy_label="REVIEW_REQUIRED",
            processing_candidate=("manual_review_candidate",),
            reason_code="QUESTION_CONFLICT_REQUIRES_REVIEW",
        )

    return ExactDuplicatePolicyDecision(
        policy_label="REVIEW_REQUIRED",
        processing_candidate=("retain_candidate", "review_candidate"),
        reason_code="ANSWER_REUSE_CONTEXT_UNKNOWN",
    )
