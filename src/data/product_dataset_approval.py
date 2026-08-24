"""Product Dataset approval orchestration over authoritative review state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .dataset_governance import (
    ApprovedDatasetVersion,
    DatasetGovernanceError,
    DatasetVersionIdentity,
    approve_dataset_version,
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
    validate_dataset_review_authority_record,
)

_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ProductDatasetApprovalRequest:
    """Identity-only approval input; no caller-created lifecycle payload."""

    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    approval_evidence_ids: tuple[str, ...]
    approved_at: datetime


def approve_product_dataset_version(
    request: ProductDatasetApprovalRequest,
    *,
    proposal_authority: DatasetProposalAuthority,
    review_authority: DatasetReviewAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
) -> ApprovedDatasetVersion:
    """Read both authorities, revalidate evidence, then apply the pure transition."""

    submitted = _validate_request(request)
    authoritative = _read_proposal(submitted, proposal_authority)
    review = _read_review(submitted, review_authority)

    require_current_dataset_evidence(
        authoritative.proposal,
        proposal_fingerprint=authoritative.proposal_fingerprint,
        authority=current_evidence_authority,
        evaluated_at=submitted.approved_at,
    )

    reviewing = begin_dataset_review(authoritative.proposal)
    if (
        reviewing.identity != review.identity
        or reviewing.status != review.lifecycle_state
        or reviewing.payload["approved"] is not review.approved
        or reviewing.payload["frozen"] is not review.frozen
        or reviewing.payload["training_allowed"] is not review.training_allowed
    ):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_REPRESENTATION_INVALID",
            "approval",
            identity=submitted.identity,
        )
    approved = approve_dataset_version(
        reviewing,
        approval_evidence_ids=submitted.approval_evidence_ids,
    )
    if approved.identity != submitted.identity:
        raise DatasetGovernanceError("APPROVAL_RESULT_INVALID", "approval")
    return approved


def _validate_request(request: object) -> ProductDatasetApprovalRequest:
    if type(request) is not ProductDatasetApprovalRequest:
        raise DatasetGovernanceError("APPROVAL_REQUEST_INVALID", "approval")
    if (
        type(request.identity) is not DatasetVersionIdentity
        or any(
            not isinstance(value, str) or not value
            for value in (
                request.identity.object_id,
                request.identity.dataset_id,
                request.identity.dataset_version,
            )
        )
        or not isinstance(request.proposal_fingerprint, str)
        or _FINGERPRINT.fullmatch(request.proposal_fingerprint) is None
        or type(request.approval_evidence_ids) is not tuple
        or not request.approval_evidence_ids
        or any(
            not isinstance(reference, str) or not reference
            for reference in request.approval_evidence_ids
        )
        or len(set(request.approval_evidence_ids)) != len(request.approval_evidence_ids)
        or not isinstance(request.approved_at, datetime)
        or request.approved_at.tzinfo is None
        or request.approved_at.utcoffset() is None
    ):
        raise DatasetGovernanceError("APPROVAL_REQUEST_INVALID", "approval")
    return request


def _read_proposal(
    request: ProductDatasetApprovalRequest,
    authority: DatasetProposalAuthority,
):
    read = getattr(authority, "read_authoritative_proposal", None)
    if not callable(read):
        raise DatasetProposalAuthorityError("PROPOSAL_AUTHORITY_MISSING", "read")
    try:
        loaded = read(request.identity)
    except DatasetProposalAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetProposalAuthorityError(
            "PROPOSAL_AUTHORITY_UNAVAILABLE",
            "read",
            identity=request.identity,
        ) from None
    return validate_dataset_proposal_authority_record(
        loaded,
        expected_identity=request.identity,
        expected_proposal_fingerprint=request.proposal_fingerprint,
    )


def _read_review(
    request: ProductDatasetApprovalRequest,
    authority: DatasetReviewAuthority,
):
    read = getattr(authority, "read_authoritative_review", None)
    if not callable(read):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_MISSING",
            "read",
            identity=request.identity,
        )
    try:
        loaded = read(
            request.identity,
            proposal_fingerprint=request.proposal_fingerprint,
        )
    except DatasetReviewAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_UNAVAILABLE",
            "read",
            identity=request.identity,
        ) from None
    return validate_dataset_review_authority_record(
        loaded,
        expected_identity=request.identity,
        expected_proposal_fingerprint=request.proposal_fingerprint,
    )


__all__ = ["ProductDatasetApprovalRequest", "approve_product_dataset_version"]
