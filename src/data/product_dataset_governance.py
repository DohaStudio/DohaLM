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


def propose_product_dataset_version(
    composition: ProductDatasetComposition,
    *,
    authority: DatasetProposalAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
    proposed_at: datetime,
) -> DatasetProposalAuthorityResult:
    """Validate one exact composition and atomically create or replay its draft."""

    payload = build_dataset_version_proposal_mapping(composition)
    return adjudicate_dataset_version_proposal(
        payload,
        authority=authority,
        current_evidence_authority=current_evidence_authority,
        proposed_at=proposed_at,
    )


__all__ = ["propose_product_dataset_version"]
