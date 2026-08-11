from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import src.data.dataset_governance as governance
from src.data.common_dataset_contracts import CommonDatasetValidationError
from src.data.dataset_governance import (
    DatasetGovernanceError,
    approve_dataset_version,
    begin_dataset_review,
    propose_dataset_version,
)


def draft_payload(**updates) -> dict:
    value = {
        "schema_name": "dataset_version",
        "schema_version": "1.0.0",
        "object_id": "dataset_version_1",
        "created_at": "2026-08-11T00:00:00Z",
        "created_by": "actor_test",
        "producer": {"name": "synthetic-test", "version": "1.0.0"},
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
        "created_from": "sha256:" + "a" * 64,
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
        "approved": False,
        "frozen": False,
        "training_allowed": False,
        "dataset_manifest_id": "dataset_manifest_future_1",
        "content_fingerprint": "sha256:" + "b" * 64,
    }
    value.update(updates)
    return value


def reviewed(payload: dict | None = None):
    return begin_dataset_review(propose_dataset_version(payload or draft_payload()))


def approved(payload: dict | None = None, **kwargs):
    return approve_dataset_version(
        reviewed(payload),
        approval_evidence_ids=("dataset_approval_1",),
        **kwargs,
    )


def test_valid_proposal_review_and_approval_state_machine():
    proposal = propose_dataset_version(draft_payload())
    review = begin_dataset_review(proposal)
    result = approve_dataset_version(
        review, approval_evidence_ids=("dataset_approval_1",)
    )
    assert proposal.status == "draft"
    assert review.status == "reviewing"
    assert result.payload["status"] == "approved"
    assert result.payload["approved"] is True
    assert result.payload["frozen"] is False
    assert result.payload["training_allowed"] is False
    assert result.fingerprint.startswith("sha256:")
    assert len(result.fingerprint) == 71


def test_common_validation_runs_before_domain_validation(monkeypatch):
    calls = []
    original_common = governance.validate_dataset_version
    original_domain = governance._require_domain_valid

    def common(payload):
        calls.append("common")
        return original_common(payload)

    def domain(payload, *, allowed_statuses):
        calls.append("domain")
        return original_domain(payload, allowed_statuses=allowed_statuses)

    monkeypatch.setattr(governance, "validate_dataset_version", common)
    monkeypatch.setattr(governance, "_require_domain_valid", domain)
    propose_dataset_version(draft_payload())
    assert calls == ["common", "domain"]

    calls.clear()
    invalid = draft_payload()
    invalid.pop("dataset_id")
    with pytest.raises(CommonDatasetValidationError):
        propose_dataset_version(invalid)
    assert calls == ["common"]


def test_domain_failure_prevents_proposal_and_approval():
    invalid = draft_payload()
    invalid["split_manifest"]["validation"] = ["candidate_train"]
    with pytest.raises(DatasetGovernanceError) as raised:
        propose_dataset_version(invalid)
    assert raised.value.code == "DATASET_DOMAIN_INVALID"
    assert "SPLIT_CANDIDATE_LEAKAGE" in {issue.code for issue in raised.value.issues}


def test_direct_or_unsupported_state_transitions_are_rejected():
    proposal = propose_dataset_version(draft_payload())
    with pytest.raises(DatasetGovernanceError, match="INVALID_STATE_TRANSITION"):
        approve_dataset_version(proposal, approval_evidence_ids=("dataset_approval_1",))
    with pytest.raises(DatasetGovernanceError, match="INVALID_STATE_TRANSITION"):
        begin_dataset_review(reviewed())
    assert not hasattr(governance, "freeze_dataset_version")


@pytest.mark.parametrize("state", ["Manifest Issued", "frozen", "unknown"])
def test_manifest_issued_and_unknown_or_frozen_proposals_are_rejected(state: str):
    invalid = draft_payload(status=state)
    if state == "frozen":
        invalid.update(approved=True, frozen=True, training_allowed=True)
    with pytest.raises((CommonDatasetValidationError, DatasetGovernanceError)):
        propose_dataset_version(invalid)


def test_approval_requires_explicit_matching_evidence():
    proposal = reviewed()
    with pytest.raises(DatasetGovernanceError) as missing:
        approve_dataset_version(proposal, approval_evidence_ids=())
    assert missing.value.code == "APPROVAL_EVIDENCE_MISSING"
    with pytest.raises(DatasetGovernanceError) as mismatch:
        approve_dataset_version(proposal, approval_evidence_ids=("other_approval",))
    assert mismatch.value.code == "APPROVAL_EVIDENCE_MISMATCH"


def test_identity_and_fingerprint_are_canonical_for_mapping_order():
    one = draft_payload()
    one["producer"]["name"] = "synthetic\\producer\nline"
    one["extensions"] = {
        "dohastudio.test": {"newline": "first\r\nsecond", "path": "segment\\value"}
    }
    two = dict(reversed(list(one.items())))
    first = approved(one)
    second = approved(two)
    assert first.identity == second.identity
    assert first.fingerprint == second.fingerprint


def test_nested_input_and_result_aliases_cannot_mutate_snapshots():
    source = draft_payload()
    proposal = propose_dataset_version(source)
    source["split_manifest"]["train"].append("candidate_injected")
    assert proposal.payload["split_manifest"]["train"] == ["candidate_train"]

    exposed = proposal.payload
    exposed["rights_summary"]["status"] = "fail"
    assert proposal.payload["rights_summary"]["status"] == "pass"

    result = approve_dataset_version(
        begin_dataset_review(proposal),
        approval_evidence_ids=("dataset_approval_1",),
    )
    approved_payload = result.payload
    approved_payload["task"] = "mutated"
    assert result.payload["task"] == "lyrics_generation"
    with pytest.raises(FrozenInstanceError):
        result.fingerprint = "sha256:" + "0" * 64


def test_same_approval_is_idempotent_and_conflicting_fingerprint_fails_closed():
    first = approved()
    replay = approved(existing=first)
    assert replay is first

    conflicting_payload = draft_payload(task="different_task")
    with pytest.raises(DatasetGovernanceError) as raised:
        approved(conflicting_payload, existing=first)
    assert raised.value.code == "APPROVAL_FINGERPRINT_CONFLICT"

    different_identity = draft_payload(object_id="dataset_version_2")
    with pytest.raises(DatasetGovernanceError) as identity_error:
        approved(different_identity, existing=first)
    assert identity_error.value.code == "APPROVAL_IDENTITY_MISMATCH"


def test_domain_aggregate_rights_count_group_and_permission_rules():
    cases = []
    rights = draft_payload()
    rights["rights_summary"] = {"status": "fail", "exception_count": 1}
    cases.append((rights, "RIGHTS_SUMMARY_NOT_PASS"))
    count = draft_payload(candidate_count=4)
    cases.append((count, "CANDIDATE_COUNT_MISMATCH"))
    groups = draft_payload()
    groups["split_manifest"]["group_keys"]["candidate_validation"] = "group_train"
    cases.append((groups, "SPLIT_GROUP_LEAKAGE"))
    permission = draft_payload(training_allowed=True)
    cases.append((permission, "TRAINING_PERMISSION_NOT_ALLOWED"))

    for payload, code in cases:
        with pytest.raises(DatasetGovernanceError) as raised:
            propose_dataset_version(payload)
        assert code in {issue.code for issue in raised.value.issues}


def test_legacy_inputs_are_not_promoted_or_defaulted():
    for legacy in (
        "v1",
        {"dataset_version": "v1"},
        {"source-manifest.json": {"dataset_version": "v1"}},
    ):
        with pytest.raises(CommonDatasetValidationError):
            propose_dataset_version(legacy)


def test_errors_do_not_expose_payload_paths_or_secrets():
    invalid = draft_payload()
    invalid["producer"]["name"] = "C:\\private\\storage\\token-secret"
    invalid["split_manifest"]["validation"] = ["candidate_train"]
    with pytest.raises(DatasetGovernanceError) as raised:
        propose_dataset_version(invalid)
    rendered = str(raised.value)
    assert "private" not in rendered
    assert "storage" not in rendered
    assert "secret" not in rendered
    assert set(raised.value.issues[0].to_dict()) == {"code", "path"}


def test_non_json_extension_fails_with_sanitized_canonicalization_error():
    invalid = draft_payload()
    invalid["extensions"] = {"dohastudio.test": {"value": float("nan")}}
    with pytest.raises(DatasetGovernanceError) as raised:
        propose_dataset_version(invalid)
    assert raised.value.code == "CANONICALIZATION_FAILED"
    assert str(raised.value) == (
        "CANONICALIZATION_FAILED:snapshot:dataset_version:NONE"
    )


def test_governance_has_no_publication_or_consumer_dependencies(monkeypatch):
    assert "AtomicArtifactDirectory" not in vars(governance)
    assert "DataConfig" not in vars(governance)
    assert "TokenizedJsonlDataset" not in vars(governance)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr("pathlib.Path.write_bytes", forbidden)
    monkeypatch.setattr("pathlib.Path.write_text", forbidden)
    monkeypatch.setattr("pathlib.Path.mkdir", forbidden)
    monkeypatch.setattr("os.rename", forbidden)
    result = approved()
    assert result.payload["status"] == "approved"
