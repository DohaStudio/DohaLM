from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import src.data as data_api
import src.data.dataset_publication as publication
from src.data.checksums import canonical_json_bytes, checksum_value
from src.data.dataset_governance import (
    DatasetVersionIdentity,
    approve_dataset_version,
    begin_dataset_review,
    propose_dataset_version,
)
from src.data.dataset_publication import (
    DatasetPublicationAuthority,
    DatasetPublicationError,
    DatasetPublicationMetadata,
    DatasetPublicationRecord,
    FilesystemDatasetPublicationAuthority,
    publish_dataset_version,
)
from src.data.errors import DataIssue, DataPipelineError

CHECKSUM = "sha256:" + "a" * 64
NAMES = ("candidate_train", "candidate_validation", "candidate_test")
VERSION_FILE = "dataset-version.json"
MANIFEST_FILE = "dataset-manifest.json"


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


def test_malformed_approved_snapshot_is_sanitized_before_filesystem_entry(
    monkeypatch, tmp_path: Path
):
    approved = approved_version()
    malformed = b'{"secret":"token-credential",'
    object.__setattr__(approved, "_canonical_payload", malformed)
    publication_root = tmp_path / "publication-root"

    def forbidden_entry(_self):
        raise AssertionError("AtomicArtifactDirectory must not be entered")

    monkeypatch.setattr(
        publication.AtomicArtifactDirectory, "__enter__", forbidden_entry
    )
    with pytest.raises(DatasetPublicationError) as raised:
        publish(publication_root, approved=approved)

    assert raised.value.code == "APPROVED_VERSION_INVALID"
    assert raised.value.stage == "input"
    assert str(raised.value) == "APPROVED_VERSION_INVALID:input:dataset_publication"
    assert "JSONDecodeError" not in str(raised.value)
    assert "token-credential" not in str(raised.value)
    assert not publication_root.exists()


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


def _authority(root: Path) -> FilesystemDatasetPublicationAuthority:
    authority: DatasetPublicationAuthority = FilesystemDatasetPublicationAuthority(root)
    return authority


def _target(root: Path, storage_key: str) -> Path:
    return root / storage_key


def _rewrite(
    target: Path,
    filename: str,
    update,
    *,
    repair_manifest_checksum: bool = False,
) -> None:
    path = target / filename
    payload = json.loads(path.read_bytes())
    update(payload)
    if filename == MANIFEST_FILE and repair_manifest_checksum:
        payload.pop("manifest_checksum", None)
        payload["manifest_checksum"] = checksum_value(payload)
    path.write_bytes(canonical_json_bytes(payload))


def _file_snapshot(target: Path) -> dict[str, bytes]:
    return {
        entry.name: entry.read_bytes() for entry in target.iterdir() if entry.is_file()
    }


def test_public_authority_reads_exact_pair_and_optional_fingerprint(tmp_path: Path):
    publication_result = publish(tmp_path)
    authority = _authority(tmp_path)
    record = authority.read_authoritative_publication(
        publication_result.identity,
        expected_pair_fingerprint=publication_result.pair_fingerprint,
    )

    assert isinstance(record, DatasetPublicationRecord)
    assert record.identity == publication_result.identity
    assert record.dataset_version == publication_result.dataset_version
    assert record.dataset_manifest == publication_result.dataset_manifest
    assert record.pair_fingerprint == publication_result.pair_fingerprint
    assert not hasattr(record, "published")
    assert not hasattr(record, "storage_key")
    assert str(tmp_path) not in repr(authority)
    assert data_api.DatasetPublicationAuthority is DatasetPublicationAuthority
    assert data_api.DatasetPublicationRecord is DatasetPublicationRecord
    assert (
        data_api.FilesystemDatasetPublicationAuthority
        is FilesystemDatasetPublicationAuthority
    )


@pytest.mark.parametrize(
    ("identity", "expected_fingerprint"),
    (
        (None, None),
        (DatasetVersionIdentity("../bad", "dataset", "1.0.0"), None),
        (DatasetVersionIdentity("version", "dataset", "1.0.0"), "sha256:BAD"),
    ),
)
def test_read_request_fails_before_storage_access(
    monkeypatch, tmp_path: Path, identity, expected_fingerprint
):
    authority = _authority(tmp_path / "absent")

    def forbidden_lstat(_path):
        raise AssertionError("storage must not be accessed")

    monkeypatch.setattr(Path, "lstat", forbidden_lstat)
    with pytest.raises(DatasetPublicationError) as raised:
        authority.read_authoritative_publication(
            identity,
            expected_pair_fingerprint=expected_fingerprint,
        )
    assert (raised.value.code, raised.value.stage) == (
        "PUBLICATION_READ_REQUEST_INVALID",
        "request",
    )


def test_root_contract_not_found_and_staging_are_distinct(tmp_path: Path):
    identity = approved_version().identity
    with pytest.raises(DatasetPublicationError) as relative:
        FilesystemDatasetPublicationAuthority(Path("relative-publication-root"))
    assert relative.value.code == "PUBLICATION_STORAGE_UNAVAILABLE"

    absent_root = tmp_path / "absent-root"
    with pytest.raises(DatasetPublicationError) as unavailable:
        _authority(absent_root).read_authoritative_publication(identity)
    assert unavailable.value.code == "PUBLICATION_STORAGE_UNAVAILABLE"

    root = tmp_path / "available-root"
    root.mkdir()
    with pytest.raises(DatasetPublicationError) as missing:
        _authority(root).read_authoritative_publication(identity)
    assert missing.value.code == "PUBLICATION_NOT_FOUND"

    staging = root / ".unrelated.staging-synthetic"
    staging.mkdir()
    (staging / VERSION_FILE).write_text("{}", encoding="utf-8")
    (staging / MANIFEST_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetPublicationError) as ignored:
        _authority(root).read_authoritative_publication(identity)
    assert ignored.value.code == "PUBLICATION_NOT_FOUND"
    assert {entry.name for entry in staging.iterdir()} == {
        VERSION_FILE,
        MANIFEST_FILE,
    }


@pytest.mark.parametrize(
    "mutation",
    ("missing-version", "missing-manifest", "extra", "non-file", "final-is-file"),
)
def test_exact_file_set_corruption_is_never_repaired(tmp_path: Path, mutation: str):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    if mutation == "missing-version":
        (target / VERSION_FILE).unlink()
    elif mutation == "missing-manifest":
        (target / MANIFEST_FILE).unlink()
    elif mutation == "extra":
        (target / "extra.json").write_text("{}", encoding="utf-8")
    elif mutation == "non-file":
        (target / MANIFEST_FILE).unlink()
        (target / MANIFEST_FILE).mkdir()
    else:
        for entry in target.iterdir():
            entry.unlink()
        target.rmdir()
        target.write_text("not-a-directory", encoding="utf-8")
    before_entries = (
        {entry.name for entry in target.iterdir()} if target.is_dir() else None
    )

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_CORRUPT"
    after_entries = (
        {entry.name for entry in target.iterdir()} if target.is_dir() else None
    )
    assert after_entries == before_entries


def test_malformed_json_is_corrupt_and_sanitized(tmp_path: Path):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    malformed = b'{"secret":"token-credential",'
    (target / MANIFEST_FILE).write_bytes(malformed)

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_CORRUPT"
    assert str(raised.value) == "PUBLICATION_CORRUPT:verification:dataset_publication"
    assert "secret" not in str(raised.value)
    assert str(tmp_path) not in str(raised.value)
    assert (target / MANIFEST_FILE).read_bytes() == malformed


@pytest.mark.parametrize("filename", (VERSION_FILE, MANIFEST_FILE))
def test_schema_invalid_resources_are_distinct_from_corrupt_bytes(
    tmp_path: Path, filename: str
):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    _rewrite(target, filename, lambda payload: payload.pop("schema_name"))

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_SCHEMA_INVALID"
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.parametrize("filename", (VERSION_FILE, MANIFEST_FILE))
def test_noncanonical_resources_are_corrupt_without_rewrite(
    tmp_path: Path, filename: str
):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    path = target / filename
    payload = json.loads(path.read_bytes())
    noncanonical = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(noncanonical)

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_CORRUPT"
    assert path.read_bytes() == noncanonical


def test_wrong_version_identity_has_typed_failure(tmp_path: Path):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    _rewrite(
        target,
        VERSION_FILE,
        lambda payload: payload.update(object_id="dataset_version_other"),
    )

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "update",
    (
        lambda payload: payload.update(
            source_dataset_version_id="dataset_version_other"
        ),
        lambda payload: payload.update(
            source_dataset_version_checksum="sha256:" + "b" * 64
        ),
        lambda payload: payload.update(item_count=payload["item_count"] + 1),
    ),
)
def test_manifest_pair_binding_and_item_count_corruption(tmp_path: Path, update):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    _rewrite(
        target,
        MANIFEST_FILE,
        update,
        repair_manifest_checksum=True,
    )

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_CORRUPT"


@pytest.mark.parametrize("resource", ("version", "manifest"))
def test_non_terminal_lifecycle_is_corrupt(tmp_path: Path, resource: str):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    if resource == "version":
        _rewrite(
            target,
            VERSION_FILE,
            lambda payload: payload.update(
                status="approved", frozen=False, training_allowed=False
            ),
        )
    else:
        _rewrite(
            target,
            MANIFEST_FILE,
            lambda payload: payload.update(
                manifest_status="draft", training_allowed=False
            ),
            repair_manifest_checksum=True,
        )

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_CORRUPT"


def test_expected_fingerprint_mismatch_is_read_only(tmp_path: Path):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    before = _file_snapshot(target)

    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(
            publication_result.identity,
            expected_pair_fingerprint="sha256:" + "0" * 64,
        )
    assert raised.value.code == "PUBLICATION_FINGERPRINT_MISMATCH"
    assert _file_snapshot(target) == before


def test_storage_io_failure_is_unavailable_and_sanitized(monkeypatch, tmp_path: Path):
    publication_result = publish(tmp_path)
    target = _target(tmp_path, publication_result.storage_key)
    manifest_path = target / MANIFEST_FILE
    original_read_bytes = Path.read_bytes

    def fail_read(path: Path):
        if path == manifest_path:
            raise PermissionError(f"secret mount {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(DatasetPublicationError) as raised:
        _authority(tmp_path).read_authoritative_publication(publication_result.identity)
    assert raised.value.code == "PUBLICATION_STORAGE_UNAVAILABLE"
    assert "secret" not in str(raised.value)
    assert str(tmp_path) not in str(raised.value)


def test_record_is_immutable_snapshot_across_new_adapter(tmp_path: Path):
    publication_result = publish(tmp_path)
    first = _authority(tmp_path).read_authoritative_publication(
        publication_result.identity
    )
    exposed_version = first.dataset_version
    exposed_manifest = first.dataset_manifest
    exposed_version["status"] = "mutated"
    exposed_manifest["source"]["alias"] = "mutated"

    assert first.dataset_version["status"] == "frozen"
    assert first.dataset_manifest["source"]["alias"] != "mutated"
    with pytest.raises(FrozenInstanceError):
        first.pair_fingerprint = "sha256:" + "0" * 64
    restarted = _authority(tmp_path).read_authoritative_publication(
        publication_result.identity
    )
    assert restarted == first


def test_read_path_never_enters_write_or_repair_primitives(monkeypatch, tmp_path: Path):
    publication_result = publish(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read path attempted a mutation")

    monkeypatch.setattr(publication.AtomicArtifactDirectory, "__init__", forbidden)
    monkeypatch.setattr(publication, "_write_canonical_file", forbidden)
    for name in ("mkdir", "write_bytes", "write_text", "unlink", "rename", "rmdir"):
        monkeypatch.setattr(Path, name, forbidden)

    record = _authority(tmp_path).read_authoritative_publication(
        publication_result.identity
    )
    assert record.pair_fingerprint == publication_result.pair_fingerprint


def test_publish_replay_and_public_read_are_equivalent(tmp_path: Path):
    first = publish(tmp_path)
    read = _authority(tmp_path).read_authoritative_publication(first.identity)
    replay = publish(tmp_path)

    assert replay.published is False
    assert read.dataset_version == replay.dataset_version
    assert read.dataset_manifest == replay.dataset_manifest
    assert read.pair_fingerprint == replay.pair_fingerprint

    target = _target(tmp_path, first.storage_key)
    (target / "extra.json").write_text("{}", encoding="utf-8")
    for operation in (
        lambda: _authority(tmp_path).read_authoritative_publication(first.identity),
        lambda: publish(tmp_path),
    ):
        with pytest.raises(DatasetPublicationError) as raised:
            operation()
        assert raised.value.code == "PUBLICATION_CORRUPT"


def test_read_contract_has_no_governance_runtime_or_training_dependencies():
    namespace = vars(publication)
    for forbidden in (
        "DatasetProposalAuthority",
        "DatasetReviewAuthority",
        "DatasetProposalCurrentEvidenceAuthority",
        "approve_product_dataset_version",
        "TrainingEligibility",
        "TrainingRun",
    ):
        assert forbidden not in namespace
