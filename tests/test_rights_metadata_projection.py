from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.data.current_evidence_snapshot import RightsReadModel, SourceToken
from src.data.rights_metadata_projection import (
    AuthorityRightsMetadata,
    RightsMetadataProjectionError,
    TypedRightsEvidence,
    project_common_rights_metadata,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
SOURCE = "11111111-1111-4111-8111-111111111111"
SUBJECT = "22222222-2222-4222-8222-222222222222"
RECORD = "33333333-3333-4333-8333-333333333333"
PRODUCER = "44444444-4444-4444-8444-444444444444"
REVIEWER = "55555555-5555-4555-8555-555555555555"
FP = "sha256:" + "a" * 64
TOKEN_FP = "sha256:" + "b" * 64


def _facts() -> AuthorityRightsMetadata:
    return AuthorityRightsMetadata(
        dataset_source_identity="AIHUB-71748",
        subject_kind="source_dataset",
        bound_identity="AIHUB-71748",
        rights_status="approved_limited",
        source_type="external",
        user_created=False,
        generated=False,
        reference=False,
        uploaded=False,
        external=True,
        analysis_allowed=True,
        derivative_generation_allowed=True,
        retention_mode="indefinite_while_current",
        retention_scope="training",
        retention_expires_at=None,
        consent_evidence_references=(),
        jurisdiction="KR",
        reviewer_authority_id=REVIEWER,
        reviewed_at=NOW,
        producer_authority_id=PRODUCER,
        effective_at=NOW,
        current_use_authorized=True,
        current_use_scope="internal_noncommercial_model_training_and_evaluation",
        fresh_acquisition_required=False,
        existing_material_reuse=True,
        historical_acquisition_receipt="not_recovered",
        provider_reacquisition_requirement_found=False,
        typed_evidence_references=(
            TypedRightsEvidence(
                "evidence:aihub-current-policy", "provider_usage_policy"
            ),
            TypedRightsEvidence("evidence:aihub-source-integrity", "source_integrity"),
        ),
    )


def _rights(metadata: AuthorityRightsMetadata | None = None) -> RightsReadModel:
    token = SourceToken(
        SOURCE,
        "rights-source-token-v1",
        SUBJECT,
        RECORD,
        FP,
        1,
        TOKEN_FP,
    )
    return RightsReadModel(
        SUBJECT,
        RECORD,
        SOURCE,
        "rights-source-token-v1",
        True,
        False,
        False,
        False,
        FP,
        token,
        _facts() if metadata is None else metadata,
    )


def test_current_use_projection_is_common_valid_and_authority_backed() -> None:
    payload = project_common_rights_metadata(_rights())
    assert payload["rights_metadata_id"] == f"rights:{RECORD}"
    assert payload["source_type"] == "external"
    assert payload["training_allowed"] is True
    assert payload["redistribution_allowed"] is False
    assert payload["retention_allowed"] is True
    assert payload["consent_evidence_refs"] == []
    assert payload["reviewed_by"] == f"authority:{REVIEWER}"
    current_use = payload["extensions"]["doharights.current_use"]
    assert current_use["fresh_acquisition_required"] is False
    assert current_use["existing_material_reuse"] is True
    assert current_use["historical_acquisition_receipt"] == "not_recovered"
    assert current_use["commercial_use_allowed"] is False
    assert current_use["external_model_publication_allowed"] is False


def test_missing_enrichment_and_tampered_evidence_fail_closed() -> None:
    with pytest.raises(
        RightsMetadataProjectionError, match="RIGHTS_AUTHORITY_FACTS_MISSING"
    ):
        project_common_rights_metadata(replace(_rights(), metadata=None))
    with pytest.raises(RightsMetadataProjectionError, match="RIGHTS_EVIDENCE_INVALID"):
        TypedRightsEvidence("https://example.invalid/evidence", "provider_usage_policy")


def test_reviewer_producer_collision_and_artificial_expiry_are_rejected() -> None:
    with pytest.raises(
        RightsMetadataProjectionError, match="RIGHTS_METADATA_FACTS_INVALID"
    ):
        replace(_facts(), reviewer_authority_id=PRODUCER)
    with pytest.raises(RightsMetadataProjectionError, match="RIGHTS_RETENTION_INVALID"):
        replace(_facts(), retention_expires_at=NOW)
