"""Product Dataset publication over fresh authoritative approval validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .dataset_governance import DatasetVersionIdentity
from .dataset_proposal_authority import (
    DatasetProposalAuthority,
    DatasetProposalCurrentEvidenceAuthority,
)
from .dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationMetadata,
    DatasetPublicationResult,
    publish_dataset_version,
)
from .dataset_review_authority import DatasetReviewAuthority
from .product_dataset_approval import (
    ProductDatasetApprovalRequest,
    approve_product_dataset_version,
)
from .product_dataset_current_evidence import DatasetLifecycleStage


@dataclass(frozen=True, slots=True)
class ProductDatasetPublicationRequest:
    """Identity-only publication request without caller-created lifecycle state."""

    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    approval_evidence_ids: tuple[str, ...]
    evaluated_at: datetime


def publish_product_dataset_version(
    request: ProductDatasetPublicationRequest,
    *,
    proposal_authority: DatasetProposalAuthority,
    review_authority: DatasetReviewAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
    metadata: DatasetPublicationMetadata,
    upstream_objects: Sequence[Mapping[str, Any]],
    publication_root: Path,
) -> DatasetPublicationResult:
    """Freshly approve from both authorities, then publish one durable pair."""

    if type(request) is not ProductDatasetPublicationRequest:
        raise DatasetPublicationError("PRODUCT_PUBLICATION_REQUEST_INVALID", "input")

    approved = approve_product_dataset_version(
        ProductDatasetApprovalRequest(
            identity=request.identity,
            proposal_fingerprint=request.proposal_fingerprint,
            approval_evidence_ids=request.approval_evidence_ids,
            approved_at=request.evaluated_at,
        ),
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        current_evidence_authority=current_evidence_authority,
    )
    bind = getattr(current_evidence_authority, "freeze_stage", None)
    if not callable(bind):
        raise DatasetPublicationError(
            "CURRENT_EVIDENCE_BINDING_AUTHORITY_MISSING", "publication"
        )
    bind(
        identity=request.identity,
        proposal_fingerprint=request.proposal_fingerprint,
        stage=DatasetLifecycleStage.PUBLICATION,
    )
    return publish_dataset_version(
        approved,
        metadata=metadata,
        upstream_objects=upstream_objects,
        evaluated_at=request.evaluated_at.isoformat(),
        publication_root=publication_root,
    )


__all__ = ["ProductDatasetPublicationRequest", "publish_product_dataset_version"]
