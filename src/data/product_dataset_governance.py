"""Product Dataset composition to DatasetVersion proposal integration."""

from __future__ import annotations

from datetime import datetime

from .dataset_proposal_authority import (
    DatasetProposalAuthority,
    DatasetProposalAuthorityResult,
    DatasetProposalCurrentEvidenceAuthority,
    adjudicate_dataset_version_proposal,
)
from .product_dataset_composition import (
    ProductDatasetComposition,
    build_dataset_version_proposal_mapping,
)
from .product_dataset_proposal_manifest import ProductDatasetManifestAuthority


def propose_product_dataset_version(
    composition: ProductDatasetComposition,
    *,
    authority: DatasetProposalAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
    proposed_at: datetime,
    manifest_authority: ProductDatasetManifestAuthority | None = None,
) -> DatasetProposalAuthorityResult:
    """Validate one exact composition and atomically create or replay its draft."""

    submission = (
        manifest_authority.create_submission(composition)
        if manifest_authority is not None
        else None
    )
    payload = (
        submission.proposal.payload
        if submission is not None
        else build_dataset_version_proposal_mapping(composition)
    )
    return adjudicate_dataset_version_proposal(
        payload,
        authority=authority,
        current_evidence_authority=current_evidence_authority,
        proposed_at=proposed_at,
        manifest_submission=submission,
    )


__all__ = ["propose_product_dataset_version"]
