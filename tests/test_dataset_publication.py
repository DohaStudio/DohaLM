from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import src.data.dataset_publication as publication
from src.data.checksums import canonical_json_bytes, checksum_value
from src.data.dataset_governance import (
    approve_dataset_version,
    begin_dataset_review,
    propose_dataset_version,
)
from src.data.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationMetadata,
    publish_dataset_version,
)
from src.data.errors import DataIssue, DataPipelineError

CHECKSUM = "sha256:" + "a" * 64
NAMES = ("candidate_train", "candidate_validation", "candidate_test")


def envelope(kind: str, object_id: str) -> dict:
    return {
        "schema_name": kind,
        "schema_version": "1.0.0",
        "object_id": object_id,
        "created_at": "2026-08-11T00:00:00Z",
        "created_by": "actor_test",
        "producer": {"name": "synthetic-test", "version": "1.0.0"},
    }


def approved_version():
    draft = {
        **envelope("dataset_version", "dataset_version_1"),
        "dataset_id": "dataset_lyrics",
        "dataset_version": "1.0.0",
        "status": "draft",
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
            "group_keys": {name: f"group_{name}" for name in NAMES},
        },
        "schema_manifest_id": "record_schema_1",
        "rights_summary": {"status": "pass", "exception_count": 0},
        "dataset_eligibility_evidence_id": "dataset_gate_1",
        "approval_evidence_ids": ["dataset_approval_1"],
        "approved": False,
        "frozen": False,
        "training_allowed": False,
        "dataset_manifest_id": "dataset_manifest_1",
        "content_fingerprint": CHECKSUM,
    }
    return approve_dataset_version(
        begin_dataset_review(propose_dataset_version(draft)),
        approval_evidence_ids=("dataset_approval_1",),
    )


def candidate(name: str, fingerprint_char: str) -> dict:
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
    checks = (
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
    return {
        **envelope("training_eligibility", f"eligibility_{name}"),
        "training_eligibility_id": f"eligibility_{name}",
        "candidate_id": name,
        "candidate_status": "approved",
        "rights_metadata_id": f"rights_{name}",
        "policy_version": "1.0.0",
        "usage_purpose": "lyrics_training",
        "checks": {key: "pass" for key in checks},
        "approved": True,
        "training_allowed": True,
        "decision": "eligible",
        "reason_codes": [],
        "reviewed_by": "reviewer_1",
        "reviewed_at": "2026-08-11T00:00:00Z",
        "expires_at": "2027-08-11T00:00:00Z",
    }


def upstream() -> list[dict]:
    return [
        *(candidate(name, str(index)) for index, name in enumerate(NAMES, 1)),
        *(rights(name) for name in NAMES),
        *(eligibility(name) for name in NAMES),
    ]


def metadata(**updates) -> DatasetPublicationMetadata:
    value = {
        "created_at": "2026-08-11T12:00:00Z",
        "created_by": "publisher_1",
        "producer": {"name": "dataset-publication", "version": "1.0.0"},
        "manifest_format_version": "1.0.0",
        "dataset_domain": "lm",
        "source": {"alias": "합성\\source\nline"},
        "license_status": "APPROVED",
        "commercial_usage_status": "REVIEW_REQUIRED",
        "redistribution_allowed": False,
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
    value.update(updates)
    return DatasetPublicationMetadata.from_mapping(value)


def publish(root: Path, **updates):
    values = {
        "approved": approved_version(),
        "metadata": metadata(),
        "upstream_objects": upstream(),
        "evaluated_at": "2026-08-11T12:00:00Z",
        "publication_root": root,
    }
    values.update(updates)
    return publish_dataset_version(**values)


def test_constructs_exact_frozen_issued_pair_and_two_file_layout(tmp_path: Path):
    result = publish(tmp_path)
    version = result.dataset_version
    manifest = result.dataset_manifest
    assert result.published is True
    assert version["status"] == "frozen"
    assert (
        version["approved"] is version["frozen"] is version["training_allowed"] is True
    )
    assert (
        version["dataset_manifest_id"]
        == manifest["object_id"]
        == manifest["dataset_manifest_id"]
    )
    assert manifest["source_dataset_version_id"] == version["object_id"]
    assert manifest["source_dataset_version_checksum"] == version["content_fingerprint"]
    assert manifest["item_count"] == version["candidate_count"]
    target = tmp_path / result.storage_key
    assert {item.name for item in target.iterdir()} == {
        "dataset-version.json",
        "dataset-manifest.json",
    }
    assert (target / "dataset-version.json").read_bytes() == canonical_json_bytes(
        version
    )
    assert (target / "dataset-manifest.json").read_bytes() == canonical_json_bytes(
        manifest
    )


def test_checksum_storage_and_pair_fingerprint_exact_vectors(tmp_path: Path):
    result = publish(tmp_path)
    manifest = result.dataset_manifest
    projection = dict(manifest)
    checksum = projection.pop("manifest_checksum")
    assert checksum == checksum_value(projection)
    assert (
        result.storage_key
        == checksum_value(
            {
                "dataset_id": "dataset_lyrics",
                "dataset_version": "1.0.0",
                "object_id": "dataset_version_1",
            }
        )[7:]
    )
    assert result.pair_fingerprint == checksum_value(
        {
            "dataset_manifest": result.dataset_manifest,
            "dataset_version": result.dataset_version,
        }
    )


def test_mapping_order_and_evaluated_at_do_not_change_publication_identity(
    tmp_path: Path,
):
    ordered = metadata().payload
    reversed_metadata = DatasetPublicationMetadata.from_mapping(
        dict(reversed(list(ordered.items())))
    )
    first = publish(
        tmp_path / "first", metadata=DatasetPublicationMetadata.from_mapping(ordered)
    )
    second = publish(
        tmp_path / "second",
        metadata=reversed_metadata,
        evaluated_at="2026-08-12T01:00:00+09:00",
    )
    assert second.dataset_manifest == first.dataset_manifest
    assert second.storage_key == first.storage_key
    assert second.pair_fingerprint == first.pair_fingerprint


def test_optional_fields_are_only_copied_when_explicit(tmp_path: Path):
    absent = publish(tmp_path / "absent").dataset_manifest
    assert not {
        "supersedes",
        "correlation_id",
        "workspace_id",
        "job_id",
        "extensions",
    } & set(absent)
    explicit = publish(
        tmp_path / "explicit",
        metadata=metadata(
            correlation_id="correlation_1",
            extensions={"dohastudio.test": {"value": "명시값"}},
        ),
    ).dataset_manifest
    assert explicit["correlation_id"] == "correlation_1"
    assert explicit["extensions"] == {"dohastudio.test": {"value": "명시값"}}


def test_same_pair_replay_is_read_only_and_conflicting_pair_fails(tmp_path: Path):
    first = publish(tmp_path)
    before = (tmp_path / first.storage_key / "dataset-manifest.json").read_bytes()
    replay = publish(tmp_path)
    assert replay.published is False
    assert replay.pair_fingerprint == first.pair_fingerprint
    assert (
        tmp_path / first.storage_key / "dataset-manifest.json"
    ).read_bytes() == before

    conflicting = json.loads(before)
    conflicting["source"]["alias"] = "different"
    (tmp_path / first.storage_key / "dataset-manifest.json").write_bytes(
        canonical_json_bytes(conflicting)
    )
    with pytest.raises(DatasetPublicationError) as raised:
        publish(tmp_path)
    assert raised.value.code == "PUBLICATION_CONFLICT"


def test_corrupt_or_noncanonical_existing_pair_fails_closed(tmp_path: Path):
    result = publish(tmp_path)
    target = tmp_path / result.storage_key
    (target / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetPublicationError) as raised:
        publish(tmp_path)
    assert raised.value.code == "PUBLICATION_CORRUPT"


def test_explicit_metadata_and_complete_upstream_are_required_before_write(
    tmp_path: Path,
):
    value = metadata().payload
    value.pop("split_id")
    with pytest.raises(DatasetPublicationError) as missing:
        DatasetPublicationMetadata.from_mapping(value)
    assert missing.value.code == "PUBLICATION_METADATA_INVALID"

    with pytest.raises(DatasetPublicationError) as incomplete:
        publish(tmp_path, upstream_objects=[])
    assert incomplete.value.code == "PUBLICATION_CONTRACT_INVALID"
    assert list(tmp_path.iterdir()) == []


def test_inputs_and_results_are_immutable_snapshots(tmp_path: Path):
    source_metadata = metadata().payload
    metadata_snapshot = DatasetPublicationMetadata.from_mapping(source_metadata)
    source_upstream = upstream()
    result = publish(
        tmp_path,
        metadata=metadata_snapshot,
        upstream_objects=source_upstream,
    )
    source_metadata["source"]["alias"] = "mutated"
    source_upstream[0]["candidate_id"] = "mutated"
    exposed = result.dataset_manifest
    exposed["source"]["alias"] = "mutated"
    assert result.dataset_manifest["source"]["alias"] != "mutated"
    with pytest.raises(FrozenInstanceError):
        result.storage_key = "0" * 64


def test_invalid_time_and_tampered_approval_are_sanitized(tmp_path: Path):
    with pytest.raises(DatasetPublicationError) as invalid_time:
        publish(tmp_path, evaluated_at="2026-08-11T12:00:00")
    assert invalid_time.value.code == "PUBLICATION_CONTRACT_INVALID"
    assert str(tmp_path) not in str(invalid_time.value)

    approved = approved_version()
    object.__setattr__(approved, "fingerprint", "sha256:" + "0" * 64)
    with pytest.raises(DatasetPublicationError) as tampered:
        publish(tmp_path, approved=approved)
    assert tampered.value.code == "APPROVED_VERSION_INVALID"

    for legacy in ("v1", {"dataset_version": "v1"}):
        with pytest.raises(DatasetPublicationError) as rejected:
            publish(tmp_path, approved=legacy)
        assert rejected.value.code == "APPROVED_VERSION_INVALID"


def test_precommit_failure_leaves_no_partial_final(monkeypatch, tmp_path: Path):
    def fail(_path: Path, _payload: bytes) -> None:
        raise DatasetPublicationError("PUBLICATION_WRITE_FAILED", "staging")

    monkeypatch.setattr("src.data.dataset_publication._write_canonical_file", fail)
    with pytest.raises(DatasetPublicationError) as raised:
        publish(tmp_path)
    assert raised.value.code == "PUBLICATION_WRITE_FAILED"
    assert list(tmp_path.iterdir()) == []


def test_commit_failure_is_sanitized_and_cleans_same_process_staging(
    monkeypatch, tmp_path: Path
):
    def fail_commit(_self) -> None:
        raise DataPipelineError(
            DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "secret-path")
        )

    monkeypatch.setattr(publication.AtomicArtifactDirectory, "publish", fail_commit)
    with pytest.raises(DatasetPublicationError) as raised:
        publish(tmp_path)
    assert raised.value.code == "PUBLICATION_COMMIT_FAILED"
    assert "secret" not in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_validation_order_precedes_staging(monkeypatch, tmp_path: Path):
    calls: list[str] = []
    names = (
        "verify_common_contract_runtime",
        "validate_dataset_version",
        "validate_dataset_manifest",
        "_require_domain_identity",
        "validate_dataset_publication_scenario",
    )
    for name in names:
        original = getattr(publication, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(publication, name, wrapper)

    def stop_before_write(_path: Path, _payload: bytes) -> None:
        raise DatasetPublicationError("STOP", "test")

    monkeypatch.setattr(publication, "_write_canonical_file", stop_before_write)
    with pytest.raises(DatasetPublicationError, match="STOP"):
        publish(tmp_path)
    assert calls[:6] == [
        "verify_common_contract_runtime",
        "validate_dataset_version",
        "validate_dataset_version",
        "validate_dataset_manifest",
        "_require_domain_identity",
        "validate_dataset_publication_scenario",
    ]
    assert list(tmp_path.iterdir()) == []


def test_publication_has_no_clock_uuid_legacy_or_artifact_content_dependency():
    namespace = vars(publication)
    for forbidden in (
        "datetime",
        "time",
        "uuid",
        "DataConfig",
        "build_pipeline",
        "file_checksum",
        "artifact_checksum",
    ):
        assert forbidden not in namespace
