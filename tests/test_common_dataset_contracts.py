from __future__ import annotations

from copy import deepcopy

import pytest

from src.data.common_dataset_contracts import (
    COMMON_CONTRACT_PACKAGE_VERSION,
    DATASET_MANIFEST_SCHEMA_ID,
    DATASET_VERSION_SCHEMA_ID,
    LEARNING_CANDIDATE_SCHEMA_ID,
    RIGHTS_METADATA_SCHEMA_ID,
    TRAINING_ELIGIBILITY_SCHEMA_ID,
    CommonContractRuntimeError,
    CommonDatasetValidationError,
    validate_dataset_manifest,
    validate_dataset_publication_scenario,
    validate_dataset_version,
    validate_learning_candidate,
    validate_rights_metadata,
    validate_training_eligibility,
    verify_common_contract_runtime,
)

CHECKSUM = "sha256:" + "a" * 64


def envelope(kind: str, object_id: str) -> dict:
    return {
        "schema_name": kind,
        "schema_version": "1.0.0",
        "object_id": object_id,
        "created_at": "2026-08-11T00:00:00Z",
        "created_by": "actor_test",
        "producer": {"name": "synthetic-test", "version": "1.0.0"},
    }


def dataset_version() -> dict:
    return {
        **envelope("dataset_version", "dataset_version_1"),
        "dataset_id": "dataset_lyrics",
        "dataset_version": "1.0.0",
        "status": "frozen",
        "usage_purpose": "lyrics_training",
        "task": "lyrics_generation",
        "lineage": [
            {
                "object_id": "candidate_train",
                "schema_name": "learning_candidate",
                "schema_version": "1.0.0",
            }
        ],
        "created_from": CHECKSUM,
        "candidate_count": 3,
        "split_manifest": {
            "train": ["candidate_train"],
            "validation": ["candidate_validation"],
            "test": ["candidate_test"],
            "group_keys": {
                "candidate_train": "group_train",
                "candidate_validation": "group_validation",
                "candidate_test": "group_test",
            },
        },
        "schema_manifest_id": "record_schema_1",
        "rights_summary": {"status": "pass", "exception_count": 0},
        "dataset_eligibility_evidence_id": "dataset_gate_1",
        "approval_evidence_ids": ["dataset_approval_1"],
        "approved": True,
        "frozen": True,
        "training_allowed": True,
        "dataset_manifest_id": "dataset_manifest_1",
        "content_fingerprint": CHECKSUM,
    }


def dataset_manifest() -> dict:
    return {
        **envelope("dataset_manifest", "dataset_manifest_1"),
        "dataset_manifest_id": "dataset_manifest_1",
        "manifest_status": "issued",
        "manifest_format_version": "1.0.0",
        "source_dataset_version_id": "dataset_version_1",
        "source_dataset_version_checksum": CHECKSUM,
        "dataset_id": "dataset_lyrics",
        "dataset_version": "1.0.0",
        "dataset_domain": "lm",
        "source": {"alias": "synthetic"},
        "license_status": "APPROVED",
        "training_allowed": True,
        "commercial_usage_status": "REVIEW_REQUIRED",
        "redistribution_allowed": False,
        "item_count": 3,
        "manifest_checksum": "sha256:" + "b" * 64,
        "object_file_artifact_refs": [
            {
                "object_id": "artifact_dataset",
                "schema_name": "artifact",
                "schema_version": "1.0.0",
            }
        ],
        "content_checksum_set_id": "checksum_set_1",
        "split_id": "split_1",
        "deletion_status": "active",
    }


def candidate(name: str) -> dict:
    fingerprint_char = {
        "candidate_train": "1",
        "candidate_validation": "2",
        "candidate_test": "3",
    }[name]
    return {
        **envelope("learning_candidate", name),
        "candidate_id": name,
        "source_type": "human_authored",
        "task": "lyrics_generation",
        "status": "approved",
        "input_refs": [],
        "output_refs": [
            {
                "object_id": f"artifact_{name}",
                "schema_name": "artifact",
                "schema_version": "1.0.0",
            }
        ],
        "rights_metadata_id": f"rights_{name}",
        "review_evidence_ids": [f"review_{name}"],
        "content_fingerprint": "sha256:" + fingerprint_char * 64,
        "parent_candidate_ids": [],
    }


def rights(name: str) -> dict:
    return {
        **envelope("rights_metadata", f"rights_{name}"),
        "rights_metadata_id": f"rights_{name}",
        "source_type": "user_created",
        "rights_status": "approved",
        "user_created": True,
        "generated": False,
        "reference": False,
        "uploaded": False,
        "external": False,
        "analysis_allowed": True,
        "training_allowed": True,
        "redistribution_allowed": False,
        "retention_allowed": {
            "allowed": True,
            "expires_at": "2027-08-11T00:00:00Z",
            "scope": "training",
        },
        "derivative_generation_allowed": True,
        "consent_evidence_refs": [f"consent_{name}"],
        "jurisdiction": "KR",
        "reviewed_at": "2026-08-11T00:00:00Z",
        "reviewed_by": "reviewer_1",
    }


def eligibility(name: str) -> dict:
    return {
        **envelope("training_eligibility", f"eligibility_{name}"),
        "training_eligibility_id": f"eligibility_{name}",
        "candidate_id": name,
        "candidate_status": "approved",
        "rights_metadata_id": f"rights_{name}",
        "policy_version": "1.0.0",
        "usage_purpose": "lyrics_training",
        "checks": {
            key: "pass"
            for key in (
                "review",
                "rights",
                "provenance",
                "consent",
                "retention",
                "purpose_scope",
                "quality",
                "pii",
                "lineage",
                "reference_source_separation",
            )
        },
        "approved": True,
        "training_allowed": True,
        "decision": "eligible",
        "reason_codes": [],
        "reviewed_by": "reviewer_1",
        "reviewed_at": "2026-08-11T00:00:00Z",
        "expires_at": "2027-08-11T00:00:00Z",
    }


def publication_scenario() -> dict:
    names = ("candidate_train", "candidate_validation", "candidate_test")
    return {
        "scenario_id": "dataset_publication_valid",
        "evaluated_at": "2026-08-11T12:00:00Z",
        "objects": [
            *(candidate(name) for name in names),
            *(rights(name) for name in names),
            *(eligibility(name) for name in names),
            dataset_version(),
            dataset_manifest(),
        ],
    }


def test_installed_runtime_and_valid_objects_pass_unchanged():
    verify_common_contract_runtime()
    assert DATASET_VERSION_SCHEMA_ID == (
        "https://schemas.dohastudio.org/common-ai/v1/dataset-version.schema.json"
    )
    assert DATASET_MANIFEST_SCHEMA_ID == (
        "https://schemas.dohastudio.org/common-ai/v1/dataset-manifest.schema.json"
    )
    assert LEARNING_CANDIDATE_SCHEMA_ID.endswith("/learning-candidate.schema.json")
    assert RIGHTS_METADATA_SCHEMA_ID.endswith("/rights-metadata.schema.json")
    assert TRAINING_ELIGIBILITY_SCHEMA_ID.endswith("/training-eligibility.schema.json")
    version = dataset_version()
    manifest = dataset_manifest()
    assert validate_dataset_version(version) is version
    assert validate_dataset_manifest(manifest) is manifest
    name = "candidate_train"
    assert validate_learning_candidate(candidate(name)) is not None
    assert validate_rights_metadata(rights(name)) is not None
    assert validate_training_eligibility(eligibility(name)) is not None


def test_valid_frozen_and_issued_pair_passes_as_one_scenario():
    scenario = publication_scenario()
    assert validate_dataset_publication_scenario(scenario) is scenario


def test_invalid_object_fails_with_structured_non_payload_issue():
    invalid = dataset_version()
    invalid["dataset_id"] = "private value with spaces"
    before = deepcopy(invalid)
    with pytest.raises(CommonDatasetValidationError) as raised:
        validate_dataset_version(invalid)
    assert raised.value.kind == "dataset_version"
    assert raised.value.issues
    assert all(
        set(issue.to_dict()) == {"code", "path"} for issue in raised.value.issues
    )
    assert "private value" not in str(raised.value)
    assert invalid == before


def test_invalid_manifest_and_wrong_expected_kind_fail_closed():
    invalid = dataset_manifest()
    invalid["manifest_status"] = "published"
    with pytest.raises(CommonDatasetValidationError) as manifest_error:
        validate_dataset_manifest(invalid)
    with pytest.raises(CommonDatasetValidationError) as kind_error:
        validate_dataset_version(dataset_manifest())
    assert manifest_error.value.issues
    assert kind_error.value.issues


def test_pair_identity_mismatch_fails_closed():
    scenario = publication_scenario()
    changed = deepcopy(scenario)
    changed["objects"][-1]["source_dataset_version_checksum"] = "sha256:" + "c" * 64
    with pytest.raises(CommonDatasetValidationError) as raised:
        validate_dataset_publication_scenario(changed)
    assert "MANIFEST_IDENTITY_MISMATCH" in {issue.code for issue in raised.value.issues}


def test_package_version_mismatch_is_sanitized(monkeypatch):
    monkeypatch.setattr(
        "src.data.common_dataset_contracts.distribution_version",
        lambda _name: COMMON_CONTRACT_PACKAGE_VERSION + ".unexpected",
    )
    with pytest.raises(CommonContractRuntimeError) as raised:
        verify_common_contract_runtime()
    assert str(raised.value) == "COMMON_CONTRACT_RUNTIME_UNAVAILABLE"
