"""Side-effect-free handoff from an accepted review to Dataset inclusion review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .checksums import checksum_value
from .common_dataset_contracts import (
    COMMON_CONTRACT_AUTHORITY_COMMIT,
    COMMON_CONTRACT_PACKAGE_VERSION,
    COMMON_CONTRACT_POLICY_VERSION,
)
from .learning_candidate_consumer import CommonObjectReference, ProducerIdentity
from .learning_candidate_review import (
    LearningCandidateReviewAuthority,
    LearningCandidateReviewError,
    LearningCandidateReviewResult,
    ReviewDecision,
    ReviewReason,
    evaluate_current_review_evidence,
)

_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


class DatasetInclusionHandoffStatus(str, Enum):
    """Local lifecycle status that grants no Dataset publication authority."""

    PENDING_DATASET_INCLUSION_REVIEW = "PENDING_DATASET_INCLUSION_REVIEW"


class DatasetInclusionHandoffError(ValueError):
    """A handoff contract or current-authority invariant failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:dataset_inclusion_handoff")


class DatasetInclusionHandoffRejected(DatasetInclusionHandoffError):
    """A valid review is not currently eligible for Dataset inclusion review."""


@dataclass(frozen=True)
class DatasetInclusionHandoff:
    """Immutable local request for a separate Dataset inclusion review."""

    handoff_id: str
    status: DatasetInclusionHandoffStatus
    handoff_created_at: str
    candidate_id: str
    review_evidence_reference: str
    reviewer_id: str
    reviewed_at: str
    candidate_schema_version: str
    candidate_content_fingerprint: str
    candidate_producer: ProducerIdentity
    rights_producer: ProducerIdentity
    eligibility_producer: ProducerIdentity
    source_type: str
    task: str
    input_references: tuple[CommonObjectReference, ...]
    output_references: tuple[CommonObjectReference, ...]
    parent_candidate_ids: tuple[str, ...]
    candidate_review_evidence_ids: tuple[str, ...]
    rights_metadata_id: str
    consent_evidence_refs: tuple[str, ...]
    training_eligibility_id: str
    usage_purpose: str
    workspace_id: str | None
    rights_checked_at: str
    eligibility_checked_at: str
    dataset_inclusion_review_allowed: bool = True
    dataset_version_creation_allowed: bool = False
    dataset_publication_allowed: bool = False
    training_allowed: bool = False
    evaluation_allowed: bool = False
    promotion_allowed: bool = False
    contract_package_version: str = COMMON_CONTRACT_PACKAGE_VERSION
    contract_policy_version: str = COMMON_CONTRACT_POLICY_VERSION
    contract_authority_commit: str = COMMON_CONTRACT_AUTHORITY_COMMIT


def create_dataset_inclusion_handoff(
    review_result: LearningCandidateReviewResult,
    *,
    handoff_created_at: datetime,
    authority: LearningCandidateReviewAuthority,
    expected_workspace_id: str | None = None,
) -> DatasetInclusionHandoff:
    """Create a review-only Dataset handoff after current evidence revalidation."""

    created_at = _require_handoff_time(handoff_created_at)
    _require_accepted_review(review_result, created_at, expected_workspace_id)
    try:
        current = evaluate_current_review_evidence(
            review_result,
            authority=authority,
            checked_at=created_at,
        )
    except LearningCandidateReviewError as exc:
        raise DatasetInclusionHandoffError(exc.code, exc.stage) from None
    if current.reason_code is not None:
        raise DatasetInclusionHandoffRejected(
            _rejection_code(current.reason_code),
            "current_evidence",
        )
    if current.resolved is not True:
        raise DatasetInclusionHandoffRejected(
            "CURRENT_EVIDENCE_UNRESOLVED",
            "current_evidence",
        )

    checked_at = _utc_text(created_at)
    identity_projection = {
        "candidate_id": review_result.candidate_id,
        "handoff_created_at": checked_at,
        "review_evidence_reference": review_result.review_evidence_reference,
        "reviewed_at": review_result.reviewed_at,
        "rights_metadata_id": review_result.rights_metadata_id,
        "training_eligibility_id": review_result.training_eligibility_id,
        "workspace_id": review_result.workspace_id,
    }
    return DatasetInclusionHandoff(
        handoff_id=f"handoff:{checksum_value(identity_projection)}",
        status=DatasetInclusionHandoffStatus.PENDING_DATASET_INCLUSION_REVIEW,
        handoff_created_at=checked_at,
        candidate_id=review_result.candidate_id,
        review_evidence_reference=review_result.review_evidence_reference,
        reviewer_id=review_result.reviewer_id,
        reviewed_at=review_result.reviewed_at,
        candidate_schema_version=review_result.candidate_schema_version,
        candidate_content_fingerprint=review_result.candidate_content_fingerprint,
        candidate_producer=review_result.candidate_producer,
        rights_producer=review_result.rights_producer,
        eligibility_producer=review_result.eligibility_producer,
        source_type=review_result.source_type,
        task=review_result.task,
        input_references=review_result.input_references,
        output_references=review_result.output_references,
        parent_candidate_ids=review_result.parent_candidate_ids,
        candidate_review_evidence_ids=review_result.candidate_review_evidence_ids,
        rights_metadata_id=review_result.rights_metadata_id,
        consent_evidence_refs=review_result.consent_evidence_refs,
        training_eligibility_id=review_result.training_eligibility_id,
        usage_purpose=review_result.usage_purpose,
        workspace_id=review_result.workspace_id,
        rights_checked_at=checked_at,
        eligibility_checked_at=checked_at,
    )


def _require_accepted_review(
    review: object,
    created_at: datetime,
    expected_workspace_id: str | None,
) -> None:
    if type(review) is not LearningCandidateReviewResult:
        raise DatasetInclusionHandoffError("REVIEW_RESULT_INVALID", "review")
    if review.decision is not ReviewDecision.ACCEPTED:
        raise DatasetInclusionHandoffRejected("REVIEW_NOT_ACCEPTED", "review")
    if (
        review.requested_decision is not ReviewDecision.ACCEPTED
        or review.reason_code is not ReviewReason.ACCEPTED_VALID_CURRENT_ELIGIBILITY
        or review.current_evidence_resolved is not True
        or review.dataset_inclusion_review_allowed is not True
        or review.dataset_publication_allowed is not False
        or review.training_allowed is not False
        or review.evaluation_allowed is not False
        or review.promotion_allowed is not False
    ):
        raise DatasetInclusionHandoffError("REVIEW_RESULT_INVALID", "review")
    if (
        review.contract_package_version != COMMON_CONTRACT_PACKAGE_VERSION
        or review.contract_policy_version != COMMON_CONTRACT_POLICY_VERSION
        or review.contract_authority_commit != COMMON_CONTRACT_AUTHORITY_COMMIT
        or review.canonical_status != "approved"
        or not _is_reference(review.candidate_id)
        or not _is_reference(review.reviewer_id)
        or not _is_reference(review.review_evidence_reference)
        or not _is_reference(review.candidate_schema_version)
        or not _is_reference(review.source_type)
        or not _is_reference(review.task)
        or not _is_reference(review.rights_metadata_id)
        or not _is_reference(review.training_eligibility_id)
        or not _is_reference(review.usage_purpose)
        or (review.workspace_id is not None and not _is_reference(review.workspace_id))
        or not _FINGERPRINT.fullmatch(review.candidate_content_fingerprint)
        or type(review.candidate_producer) is not ProducerIdentity
        or type(review.rights_producer) is not ProducerIdentity
        or type(review.eligibility_producer) is not ProducerIdentity
        or not _valid_producer(review.candidate_producer)
        or not _valid_producer(review.rights_producer)
        or not _valid_producer(review.eligibility_producer)
        or not _valid_references(review.candidate_review_evidence_ids)
        or not _valid_references(review.consent_evidence_refs)
    ):
        raise DatasetInclusionHandoffError("REVIEW_IDENTITY_INVALID", "identity")
    if (
        not isinstance(review.input_references, tuple)
        or not isinstance(review.output_references, tuple)
        or not isinstance(review.parent_candidate_ids, tuple)
        or any(
            type(item) is not CommonObjectReference for item in review.input_references
        )
        or any(
            type(item) is not CommonObjectReference for item in review.output_references
        )
        or any(
            not _valid_object_reference(item)
            for item in (*review.input_references, *review.output_references)
        )
        or any(not _is_reference(item) for item in review.parent_candidate_ids)
        or review.candidate_id in review.parent_candidate_ids
    ):
        raise DatasetInclusionHandoffError("LINEAGE_MISMATCH", "lineage")
    reviewed_at = _parse_time(review.reviewed_at, "reviewed_at")
    rights_checked_at = _parse_time(review.rights_checked_at, "rights_checked_at")
    eligibility_checked_at = _parse_time(
        review.eligibility_checked_at,
        "eligibility_checked_at",
    )
    if (
        reviewed_at > created_at
        or rights_checked_at != reviewed_at
        or eligibility_checked_at != reviewed_at
    ):
        raise DatasetInclusionHandoffError("REVIEW_TIMESTAMP_INVALID", "timestamp")
    if (
        expected_workspace_id is not None
        and review.workspace_id != expected_workspace_id
    ):
        raise DatasetInclusionHandoffError("WORKSPACE_SCOPE_MISMATCH", "workspace")


def _rejection_code(reason: ReviewReason) -> str:
    return {
        ReviewReason.REJECTED_RIGHTS_EXPIRED: "CURRENT_RIGHTS_EXPIRED",
        ReviewReason.REJECTED_RIGHTS_REVOKED: "CURRENT_RIGHTS_REVOKED",
        ReviewReason.REJECTED_RIGHTS_INVALID: "CURRENT_RIGHTS_INVALID",
        ReviewReason.REJECTED_ELIGIBILITY_EXPIRED: "CURRENT_ELIGIBILITY_EXPIRED",
        ReviewReason.REJECTED_ELIGIBILITY_REVOKED: "CURRENT_ELIGIBILITY_REVOKED",
        ReviewReason.REJECTED_ELIGIBILITY_INVALID: "CURRENT_ELIGIBILITY_INVALID",
        ReviewReason.NEEDS_REVIEW_EVIDENCE_UNRESOLVED: "CURRENT_EVIDENCE_UNRESOLVED",
    }.get(reason, "CURRENT_EVIDENCE_INVALID")


def _require_handoff_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DatasetInclusionHandoffError("HANDOFF_TIMESTAMP_INVALID", "timestamp")
    return value


def _parse_time(value: object, stage: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise DatasetInclusionHandoffError("REVIEW_TIMESTAMP_INVALID", stage) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DatasetInclusionHandoffError("REVIEW_TIMESTAMP_INVALID", stage)
    return parsed


def _is_reference(value: object) -> bool:
    return isinstance(value, str) and _SAFE_REFERENCE.fullmatch(value) is not None


def _valid_references(values: object) -> bool:
    return (
        isinstance(values, tuple)
        and bool(values)
        and all(_is_reference(value) for value in values)
    )


def _valid_producer(value: ProducerIdentity) -> bool:
    return _is_reference(value.name) and _is_reference(value.version)


def _valid_object_reference(value: CommonObjectReference) -> bool:
    return (
        _is_reference(value.object_id)
        and _is_reference(value.schema_name)
        and _is_reference(value.schema_version)
        and (
            value.content_fingerprint is None
            or _FINGERPRINT.fullmatch(value.content_fingerprint) is not None
        )
    )


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "DatasetInclusionHandoff",
    "DatasetInclusionHandoffError",
    "DatasetInclusionHandoffRejected",
    "DatasetInclusionHandoffStatus",
    "create_dataset_inclusion_handoff",
]
