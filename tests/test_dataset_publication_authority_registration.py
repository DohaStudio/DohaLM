from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationResult,
)
from src.data.product_dataset_authority_registration import (
    InternalProductionDatasetEligibility,
    build_compatible_product_dataset_pair_replacement,
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
            "split_id": "split:test",
            "object_file_artifact_refs": [
                {
                    "object_id": "artifact:test",
                    "schema_name": "dataset_artifact_manifest",
                    "schema_version": "1.0.0",
                }
            ],
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
    values = {
        "eligibility": _eligibility(),
        "source_commit": "a" * 40,
        "valid_from": NOW,
        "valid_until": NOW + timedelta(days=1),
        "correlation_reference": "correlation:Dataset-registration",
    }
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


def test_compatible_pair_replacement_is_v2_stable_and_preserves_content_pair() -> None:
    publication = _publication()
    values = {
        "previous_pair_authority_id": "00000000-0000-0000-0000-000000000001",
        "eligibility": _eligibility(),
        "upstream_objects": [{"object_type": "rights", "status": "approved"}],
        "evaluated_at": "2026-09-01T01:00:00+00:00",
        "expected_split_id": "split:test",
        "artifact_references": publication.dataset_manifest[
            "object_file_artifact_refs"
        ],
        "source_commit": "a" * 40,
        "valid_until": None,
        "correlation_reference": "correlation:Dataset-pair-v2",
    }
    first = build_compatible_product_dataset_pair_replacement(publication, **values)
    replay = build_compatible_product_dataset_pair_replacement(publication, **values)
    assert replay == first
    assert first.pair_fingerprint == publication.pair_fingerprint
    assert first.pair_payload_fingerprint != publication.pair_fingerprint
    assert b'"payload_schema":"dataset_pair_payload_v2"' in first.pair_payload
    assert b'"upstream_objects"' in first.pair_payload
    assert b'"artifact_references"' in first.pair_payload
    assert b'"evaluated_at"' in first.pair_payload
    assert b'"expected_split_id":"split:test"' in first.pair_payload


def test_compatible_pair_replacement_rejects_wrong_split_or_artifacts() -> None:
    publication = _publication()
    common = {
        "previous_pair_authority_id": "00000000-0000-0000-0000-000000000001",
        "eligibility": _eligibility(),
        "upstream_objects": [{"object_type": "rights", "status": "approved"}],
        "evaluated_at": "2026-09-01T01:00:00+00:00",
        "source_commit": "a" * 40,
        "valid_until": None,
        "correlation_reference": "correlation:Dataset-pair-v2",
    }
    with pytest.raises(
        DatasetPublicationError, match="PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID"
    ):
        build_compatible_product_dataset_pair_replacement(
            publication,
            expected_split_id="split:wrong",
            artifact_references=publication.dataset_manifest[
                "object_file_artifact_refs"
            ],
            **common,
        )
    with pytest.raises(
        DatasetPublicationError, match="PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID"
    ):
        build_compatible_product_dataset_pair_replacement(
            publication,
            expected_split_id="split:test",
            artifact_references=[],
            **common,
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
