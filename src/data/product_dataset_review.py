"""Product Dataset authoritative review-start orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .dataset_governance import (
    DatasetVersionIdentity,
    DatasetVersionProposal,
    begin_dataset_review,
)
from .dataset_proposal_authority import (
    DatasetProposalAuthority,
    DatasetProposalAuthorityError,
    DatasetProposalCurrentEvidenceAuthority,
    require_current_dataset_evidence,
    validate_dataset_proposal_authority_record,
)
from .dataset_review_authority import (
    DatasetReviewAuthority,
    DatasetReviewAuthorityError,
    DatasetReviewAuthorityRecord,
    DatasetReviewOutcome,
    DatasetReviewStartRequest,
    validate_dataset_review_start_request,
    validate_dataset_review_start_result,
)
from .product_dataset_current_evidence import DatasetLifecycleStage


@dataclass(frozen=True, slots=True)
class ProductDatasetReviewStartResult:
    """Immutable successful Product Dataset review-start representation."""

    outcome: DatasetReviewOutcome
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    reviewing_proposal: DatasetVersionProposal
    review_record: DatasetReviewAuthorityRecord


def start_product_dataset_review(
    request: DatasetReviewStartRequest,
    *,
    proposal_authority: DatasetProposalAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
    review_authority: DatasetReviewAuthority,
) -> ProductDatasetReviewStartResult:
    """Read, revalidate, atomically start, then represent one review lifecycle."""

    submitted = validate_dataset_review_start_request(request)
    read = getattr(proposal_authority, "read_authoritative_proposal", None)
    if not callable(read):
        raise DatasetProposalAuthorityError("PROPOSAL_AUTHORITY_MISSING", "read")
    try:
        loaded = read(submitted.identity)
    except DatasetProposalAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetProposalAuthorityError(
            "PROPOSAL_AUTHORITY_UNAVAILABLE",
            "read",
            identity=submitted.identity,
        ) from None
    authoritative = validate_dataset_proposal_authority_record(
        loaded,
        expected_identity=submitted.identity,
        expected_proposal_fingerprint=submitted.proposal_fingerprint,
    )
    require_current_dataset_evidence(
        authoritative.proposal,
        proposal_fingerprint=authoritative.proposal_fingerprint,
        authority=current_evidence_authority,
        evaluated_at=submitted.review_started_at,
    )

    start = getattr(review_authority, "start_review", None)
    if not callable(start):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_MISSING",
            "authority",
            identity=submitted.identity,
        )
    try:
        raw_result = start(submitted)
    except DatasetReviewAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_UNAVAILABLE",
            "authority",
            identity=submitted.identity,
        ) from None
    result = validate_dataset_review_start_result(raw_result, submitted)
    if result.outcome is DatasetReviewOutcome.CONFLICT:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_START_CONFLICT",
            "integration",
            identity=submitted.identity,
        )
    record = result.record
    if (
        record is None
        or record.reviewer_reference != submitted.reviewer_reference
        or record.request_reference != submitted.request_reference
        or (
            result.outcome is DatasetReviewOutcome.STARTED
            and record.review_started_at != submitted.review_started_at
        )
    ):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
            "integration",
            identity=submitted.identity,
        )
    bind = getattr(current_evidence_authority, "freeze_stage", None)
    if not callable(bind):
        raise DatasetProposalAuthorityError(
            "CURRENT_EVIDENCE_BINDING_AUTHORITY_MISSING", "review"
        )
    bind(
        identity=submitted.identity,
        proposal_fingerprint=submitted.proposal_fingerprint,
        stage=DatasetLifecycleStage.REVIEW,
    )

    reviewing = begin_dataset_review(authoritative.proposal)
    if (
        reviewing.identity != submitted.identity
        or reviewing.status != "reviewing"
        or reviewing.payload["approved"] is not False
        or reviewing.payload["frozen"] is not False
        or reviewing.payload["training_allowed"] is not False
    ):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_REPRESENTATION_INVALID",
            "integration",
            identity=submitted.identity,
        )
    return ProductDatasetReviewStartResult(
        outcome=result.outcome,
        identity=submitted.identity,
        proposal_fingerprint=submitted.proposal_fingerprint,
        reviewing_proposal=reviewing,
        review_record=record,
    )


__all__ = ["ProductDatasetReviewStartResult", "start_product_dataset_review"]
