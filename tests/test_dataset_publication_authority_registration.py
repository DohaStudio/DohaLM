from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationResult,
)
from src.data.product_dataset_authority_registration import (
    InternalProductionDatasetEligibility,
    build_product_dataset_authority_registration,
)


NOW = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)


def _publication(*, frozen: bool = True) -> DatasetPublicationResult:
    return DatasetPublicationResult._create(
        {
            "object_id": "dataset-version-test",
            "dataset_id": "dataset-test",
            "dataset_version": "v1",
            "status": "frozen" if frozen else "draft",
            "training_allowed": True,
        },
        {
            "object_id": "dataset-manifest-test",
            "manifest_status": "issued",
            "training_allowed": True,
        },
        storage_key="a" * 64,
        pair_fingerprint="sha256:" + "3" * 64,
        published=True,
    )


def _eligibility() -> InternalProductionDatasetEligibility:
    return InternalProductionDatasetEligibility(
        reference="eligibility:candidate-a",
        source_lineage_reference="lineage:candidate-a",
        internal_training_allowed=True,
        commercial_usage_allowed=False,
        redistribution_allowed=False,
    )


def test_publication_authority_registration_is_exact_stable_and_noncommercial() -> None:
    values = dict(
        eligibility=_eligibility(),
        source_commit="a" * 40,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=1),
        correlation_reference="correlation:Dataset-registration",
    )
    first = build_product_dataset_authority_registration(_publication(), **values)
    replay = build_product_dataset_authority_registration(_publication(), **values)
    assert replay == first
    assert first.dataset_version_id == "dataset-version-test"
    assert first.dataset_manifest_id == "dataset-manifest-test"
    assert first.pair_fingerprint == "sha256:" + "3" * 64
    assert b'"commercial"' not in first.pair_payload


def test_publication_authority_registration_rejects_scope_escalation_and_draft() -> (
    None
):
    with pytest.raises(DatasetPublicationError):
        InternalProductionDatasetEligibility(
            reference="eligibility:candidate-a",
            source_lineage_reference="lineage:candidate-a",
            internal_training_allowed=True,
            commercial_usage_allowed=True,
            redistribution_allowed=False,
        )
    with pytest.raises(DatasetPublicationError):
        build_product_dataset_authority_registration(
            _publication(frozen=False),
            eligibility=_eligibility(),
            source_commit="a" * 40,
            valid_from=NOW,
            valid_until=NOW + timedelta(days=1),
            correlation_reference="correlation:Dataset-registration",
        )
