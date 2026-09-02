from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

import pytest
from test_product_dataset_composition import _compose
from test_product_dataset_governance import (
    _AtomicProposalAuthority,
    _CurrentEvidenceAuthority,
)

from src.data.checksums import canonical_json_bytes, file_checksum, sha256_bytes
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityRecord,
    dataset_version_proposal_fingerprint,
    validate_dataset_proposal_authority_record,
)
from src.data.product_dataset_governance import propose_product_dataset_version
from src.data.product_dataset_proposal_manifest import (
    ProductDatasetManifestAuthority,
    ProductDatasetManifestAuthorityError,
)


def _write_json(path, value) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _artifacts(tmp_path):
    composition = _compose()
    members = sorted(composition.members, key=lambda item: item.candidate_id)
    _write_json(tmp_path / "composition.json", asdict(composition))
    with (tmp_path / "members.jsonl").open("wb") as handle:
        for member in members:
            handle.write(
                canonical_json_bytes(
                    {
                        "candidate_id": member.candidate_id,
                        "content_fingerprint": member.candidate_content_fingerprint,
                        "group_key": member.group_key,
                        "handoff_id": member.handoff_id,
                        "source_id": "sha256:" + member.candidate_id.rsplit(":", 1)[-1],
                        "split": member.split,
                    }
                )
            )
    counts = {
        split: sum(member.split == split for member in members)
        for split in ("train", "validation", "test")
    }
    dataset_identity = {
        "composition_id": composition.composition_id,
        "composition_source_fingerprint": composition.source_fingerprint,
        "composition_content_fingerprint": composition.content_fingerprint,
        "split_counts": counts,
    }
    from src.data.checksums import checksum_value

    dataset_manifest = {
        "schema_version": "1.0.0",
        "dataset_id": composition.dataset_id,
        "dataset_manifest_id": composition.dataset_manifest_id,
        "dataset_fingerprint": checksum_value(dataset_identity),
        "rights_metadata_id": members[0].rights_metadata_id,
        "rights_source_token_fingerprint": "sha256:" + "e" * 64,
        "identity": dataset_identity,
    }
    allocations = [
        {
            "source_id": "sha256:" + member.candidate_id.rsplit(":", 1)[-1],
            "group_key": member.group_key,
            "split": member.split,
        }
        for member in members
    ]
    allocation_contract = "product-dataset-allocation-reference-v1"
    allocation_bytes = canonical_json_bytes(
        {
            "contract_version": allocation_contract,
            "allocations": sorted(allocations, key=lambda item: item["source_id"]),
        }
    )
    split_manifest = {
        "schema_version": "1.0.0",
        "allocation_fingerprint": sha256_bytes(allocation_bytes),
        "allocation_fingerprint_contract_version": allocation_contract,
        "allocation_fingerprint_canonical_bytes_size": len(allocation_bytes),
        "cross_split_group_overlap": 0,
        "statistics": {split: {"records": count} for split, count in counts.items()},
    }
    _write_json(tmp_path / "dataset-manifest.json", dataset_manifest)
    _write_json(tmp_path / "split-manifest.json", split_manifest)
    files = {
        name: file_checksum(tmp_path / name)
        for name in (
            "composition.json",
            "members.jsonl",
            "dataset-manifest.json",
            "split-manifest.json",
        )
    }
    _write_json(tmp_path / "artifact-checksums.json", {"files": files})
    return composition


def test_manifest_reference_root_is_bounded_reproducible_and_resolvable(tmp_path):
    composition = _artifacts(tmp_path)
    authority = ProductDatasetManifestAuthority(tmp_path.resolve())

    first = authority.create_submission(composition)
    second = authority.create_submission(composition)
    resolved = authority.resolve_root(first.canonical_root)

    assert len(first.canonical_root) < 1_048_576
    assert first == second
    assert resolved.payload == first.proposal.payload
    assert resolved.authority_root == first.proposal.authority_root
    assert dataset_version_proposal_fingerprint(resolved) == first.proposal_fingerprint
    assert first.proposal.authority_root["member_count"] == 3
    assert first.proposal.authority_root["split_counts"] == {
        "train": 1,
        "validation": 1,
        "test": 1,
    }
    assert all(
        "path" not in first.proposal.authority_root[name]
        for name in (
            "composition",
            "member_manifest",
            "dataset_manifest",
            "allocation_manifest",
        )
    )


@pytest.mark.parametrize(
    "name",
    [
        "composition.json",
        "members.jsonl",
        "dataset-manifest.json",
        "split-manifest.json",
    ],
)
def test_manifest_byte_tamper_fails_closed(tmp_path, name):
    composition = _artifacts(tmp_path)
    authority = ProductDatasetManifestAuthority(tmp_path.resolve())
    before = authority.create_submission(composition)
    with (tmp_path / name).open("ab") as handle:
        handle.write(b" ")

    with pytest.raises(
        ProductDatasetManifestAuthorityError,
        match="MANIFEST_FINGERPRINT_MISMATCH",
    ):
        authority.resolve_root(before.canonical_root)


def test_missing_manifest_and_stale_reference_fail_closed(tmp_path):
    composition = _artifacts(tmp_path)
    authority = ProductDatasetManifestAuthority(tmp_path.resolve())
    submission = authority.create_submission(composition)
    (tmp_path / "members.jsonl").unlink()
    with pytest.raises(ProductDatasetManifestAuthorityError):
        authority.resolve_root(submission.canonical_root)

    composition = _artifacts(tmp_path)
    submission = authority.create_submission(composition)
    root = json.loads(submission.canonical_root)
    root["member_manifest"]["byte_size"] += 1
    stale = canonical_json_bytes(root)
    with pytest.raises(
        ProductDatasetManifestAuthorityError, match="MANIFEST_REFERENCE_STALE"
    ):
        authority.resolve_root(stale)


def test_one_million_member_scale_is_constant_size_metadata(tmp_path):
    composition = _artifacts(tmp_path)
    submission = ProductDatasetManifestAuthority(tmp_path.resolve()).create_submission(
        composition
    )
    root = json.loads(submission.canonical_root)
    baseline = len(submission.canonical_root)
    root["member_count"] = 1_000_000
    root["split_counts"] = {
        "train": 900_000,
        "validation": 50_000,
        "test": 50_000,
    }

    scaled = canonical_json_bytes(root)

    assert len(scaled) < 1_048_576
    assert len(scaled) - baseline < 100


def test_product_governance_port_uses_root_fingerprint_and_exact_replay(tmp_path):
    composition = _artifacts(tmp_path)
    manifests = ProductDatasetManifestAuthority(tmp_path.resolve())
    proposals = _AtomicProposalAuthority()

    first = propose_product_dataset_version(
        composition,
        authority=proposals,
        current_evidence_authority=_CurrentEvidenceAuthority(),
        proposed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        manifest_authority=manifests,
    )
    replay = propose_product_dataset_version(
        composition,
        authority=proposals,
        current_evidence_authority=_CurrentEvidenceAuthority(),
        proposed_at=datetime(2026, 9, 2, 1, tzinfo=timezone.utc),
        manifest_authority=manifests,
    )

    assert first.proposal.authority_root["schema_version"] == "2.0.0"
    assert first.proposal_fingerprint == dataset_version_proposal_fingerprint(
        first.proposal
    )
    assert replay.proposal_fingerprint == first.proposal_fingerprint
    record = DatasetProposalAuthorityRecord(
        proposal=first.proposal,
        identity=first.identity,
        proposal_fingerprint=first.proposal_fingerprint,
        authority_reference="authority:large-proposal:test",
        authority_version=2,
    )
    assert (
        validate_dataset_proposal_authority_record(
            record,
            expected_identity=first.identity,
            expected_proposal_fingerprint=first.proposal_fingerprint,
        )
        is record
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("member_count",), 4),
        (("split_counts", "train"), 2),
        (("allocation_fingerprint",), "sha256:" + "0" * 64),
        (("composition_content_fingerprint",), "sha256:" + "1" * 64),
        (("production_dataset_fingerprint",), "sha256:" + "2" * 64),
        (
            ("current_rights_snapshot_reference", "source_token_fingerprint"),
            "sha256:" + "3" * 64,
        ),
        (("eligibility_evidence_reference",), "eligibility:other"),
        (("member_manifest", "byte_size"), 1),
        (("dataset_manifest", "content_fingerprint"), "sha256:" + "4" * 64),
        (("composition", "logical_identity"), "composition:other"),
    ],
)
def test_root_binding_tamper_matrix_fails_closed(tmp_path, path, replacement):
    composition = _artifacts(tmp_path)
    authority = ProductDatasetManifestAuthority(tmp_path.resolve())
    root = json.loads(authority.create_submission(composition).canonical_root)
    target = root
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ProductDatasetManifestAuthorityError):
        authority.resolve_root(canonical_json_bytes(root))
