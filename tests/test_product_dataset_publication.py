from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from pathlib import Path

import pytest
from test_dataset_publication import candidate, eligibility, metadata, rights
from test_product_dataset_approval import (
    APPROVED_AT,
    _approval_request,
    _OrderedEvidenceAuthority,
    _prepared,
    _ReadableReviewAuthority,
)
from test_product_dataset_governance import _CurrentEvidenceAuthority

import src.data.product_dataset_approval as approval_module
import src.data.product_dataset_publication as integration_module
from src.data.dataset_governance import DatasetGovernanceError, DatasetVersionIdentity
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalEvidenceStatus,
)
from src.data.dataset_publication import DatasetPublicationError
from src.data.dataset_review_authority import DatasetReviewAuthorityError
from src.data.product_dataset_publication import (
    ProductDatasetPublicationRequest,
    publish_product_dataset_version,
)

SUFFIXES = ("train", "validation", "test")


def _request(proposal, **changes):
    approval = _approval_request(proposal)
    values = {
        "identity": approval.identity,
        "proposal_fingerprint": approval.proposal_fingerprint,
        "approval_evidence_ids": approval.approval_evidence_ids,
        "evaluated_at": APPROVED_AT,
    }
    values.update(changes)
    return ProductDatasetPublicationRequest(**values)


def _upstream() -> tuple[dict, ...]:
    names = tuple(f"candidate_{suffix}" for suffix in SUFFIXES)
    return (
        *(candidate(name, fingerprint) for name, fingerprint in zip(names, "abc")),
        *(rights(name) for name in names),
        *(eligibility(name) for name in names),
    )


def _metadata(**changes):
    return metadata(
        created_at="2026-08-25T00:00:00Z",
        workspace_id="workspace_test",
        **changes,
    )


def _publish(
    request,
    root: Path,
    *,
    proposal_authority,
    review_authority,
    evidence=None,
    publication_metadata=None,
):
    return publish_product_dataset_version(
        request,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        current_evidence_authority=evidence or _CurrentEvidenceAuthority(),
        metadata=publication_metadata or _metadata(),
        upstream_objects=_upstream(),
        publication_root=root,
    )


def _corrupt(value, field: str, replacement):
    corrupt = object.__new__(type(value))
    for name in value.__dataclass_fields__:
        object.__setattr__(
            corrupt,
            name,
            replacement if name == field else getattr(value, name),
        )
    return corrupt


def test_happy_path_uses_authoritative_order_and_returns_committed_pair(
    monkeypatch, tmp_path: Path
):
    events: list[str] = []
    proposal_authority, proposal, review_authority, started = _prepared(events)
    evidence = _OrderedEvidenceAuthority(events)
    original_approve = approval_module.approve_dataset_version
    original_publish = integration_module.publish_dataset_version

    def approve(*args, **kwargs):
        events.append("approve_dataset_version")
        return original_approve(*args, **kwargs)

    def publish(*args, **kwargs):
        events.append("publish_dataset_version")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(approval_module, "approve_dataset_version", approve)
    monkeypatch.setattr(integration_module, "publish_dataset_version", publish)
    proposal_record = proposal_authority.records[proposal.identity][0]
    review_record = started.review_record

    result = _publish(
        _request(proposal),
        tmp_path,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        evidence=evidence,
    )

    assert events == [
        "proposal_read",
        "review_read",
        "current_evidence",
        "approve_dataset_version",
        "publish_dataset_version",
    ]
    assert result.published is True
    assert result.identity == proposal.identity
    assert result.dataset_version["status"] == "frozen"
    assert result.dataset_version["approved"] is True
    assert result.dataset_version["frozen"] is True
    assert result.dataset_version["training_allowed"] is True
    assert result.dataset_manifest["manifest_status"] == "issued"
    assert (
        result.dataset_version["dataset_manifest_id"]
        == result.dataset_manifest["dataset_manifest_id"]
    )
    assert proposal_authority.records[proposal.identity][0] is proposal_record
    assert proposal_record.status == "draft"
    assert review_authority._record is review_record
    assert review_record.lifecycle_state == "reviewing"


def test_request_and_signature_exclude_caller_lifecycle_payloads():
    assert tuple(ProductDatasetPublicationRequest.__dataclass_fields__) == (
        "identity",
        "proposal_fingerprint",
        "approval_evidence_ids",
        "evaluated_at",
    )
    signature = inspect.signature(publish_product_dataset_version)
    assert tuple(signature.parameters) == (
        "request",
        "proposal_authority",
        "review_authority",
        "current_evidence_authority",
        "metadata",
        "upstream_objects",
        "publication_root",
    )
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    assert not {
        "proposal",
        "reviewing",
        "approved",
        "frozen",
        "manifest",
    } & set(ProductDatasetPublicationRequest.__dataclass_fields__)


def test_invalid_request_and_naive_evaluation_time_fail_before_publication(
    monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "publish_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetPublicationError) as wrong_type:
        _publish(
            object(),
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )
    with pytest.raises(DatasetGovernanceError) as naive_time:
        _publish(
            _request(proposal, evaluated_at=APPROVED_AT.replace(tzinfo=None)),
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert wrong_type.value.code == "PRODUCT_PUBLICATION_REQUEST_INVALID"
    assert naive_time.value.code == "APPROVAL_REQUEST_INVALID"
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "case",
    (
        "not_found",
        "identity_mismatch",
        "fingerprint_mismatch",
        "corrupt_payload",
        "authority_metadata",
    ),
)
def test_proposal_failures_stop_before_review_or_publication(
    case, monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    request = _request(proposal)
    record = proposal_authority.read_authoritative_proposal(proposal.identity)
    proposal_authority.read_calls.clear()
    if case == "not_found":
        proposal_authority.records.clear()
    elif case == "identity_mismatch":
        proposal_authority.read_override = _corrupt(
            record,
            "identity",
            DatasetVersionIdentity("dataset_version_other", "dataset_other", "2.0.0"),
        )
    elif case == "fingerprint_mismatch":
        request = replace(request, proposal_fingerprint="sha256:" + "f" * 64)
    elif case == "corrupt_payload":
        object.__setattr__(record.proposal, "_canonical_payload", b'{"secret":"value"')
        proposal_authority.read_override = record
    else:
        proposal_authority.read_override = _corrupt(
            record,
            "authority_reference",
            "private authority value",
        )
    calls = []
    monkeypatch.setattr(
        integration_module,
        "publish_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetProposalAuthorityError):
        _publish(
            request,
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert review_authority.read_calls == []
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("not_found", None),
        ("proposal_fingerprint", "sha256:" + "f" * 64),
        ("record_fingerprint", "sha256:" + "0" * 64),
        ("lifecycle_state", "approved"),
        ("authority_reference", "private authority value"),
    ),
)
def test_review_failures_stop_before_evidence_or_publication(
    field, value, monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    if field == "not_found":
        review_authority = _ReadableReviewAuthority()
    else:
        review_authority.read_override = _corrupt(
            review_authority._record, field, value
        )
    evidence = _CurrentEvidenceAuthority()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "publish_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetReviewAuthorityError):
        _publish(
            _request(proposal),
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            evidence=evidence,
        )

    assert evidence.calls == []
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "status",
    (
        DatasetProposalEvidenceStatus.MISSING,
        DatasetProposalEvidenceStatus.EXPIRED,
        DatasetProposalEvidenceStatus.REVOKED,
        DatasetProposalEvidenceStatus.IDENTITY_MISMATCH,
        DatasetProposalEvidenceStatus.INVALID,
    ),
)
def test_non_current_publication_evidence_stops_before_publication(
    status, monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "publish_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetProposalAuthorityError):
        _publish(
            _request(proposal),
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            evidence=_CurrentEvidenceAuthority(status),
        )

    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_approval_evidence_mismatch_stops_before_publication(
    monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "publish_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetGovernanceError) as raised:
        _publish(
            _request(proposal, approval_evidence_ids=("other_evidence",)),
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert getattr(raised.value, "code", None) == "APPROVAL_EVIDENCE_MISMATCH"
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_each_invocation_freshly_approves_before_committed_pair_replay(
    monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    evidence = _CurrentEvidenceAuthority()
    original = approval_module.approve_dataset_version
    transitions = []

    def approve(*args, **kwargs):
        transitions.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(approval_module, "approve_dataset_version", approve)
    request = _request(proposal)
    first = _publish(
        request,
        tmp_path,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        evidence=evidence,
    )
    original_bytes = {
        path.name: path.read_bytes()
        for path in (tmp_path / first.storage_key).iterdir()
    }
    replay = _publish(
        request,
        tmp_path,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        evidence=evidence,
    )

    assert first.published is True
    assert replay.published is False
    assert replay.pair_fingerprint == first.pair_fingerprint
    assert len(proposal_authority.read_calls) == 2
    assert len(review_authority.read_calls) == 2
    assert len(evidence.calls) == 2
    assert len(transitions) == 2
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / first.storage_key).iterdir()
    } == original_bytes


def test_uncommitted_failure_has_no_approval_recovery_and_retry_is_fresh(
    monkeypatch, tmp_path: Path
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    evidence = _CurrentEvidenceAuthority()
    real_publish = integration_module.publish_dataset_version
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DatasetPublicationError("PUBLICATION_WRITE_FAILED", "staging")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(integration_module, "publish_dataset_version", fail_once)
    request = _request(proposal)
    with pytest.raises(DatasetPublicationError):
        _publish(
            request,
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            evidence=evidence,
        )
    result = _publish(
        request,
        tmp_path,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        evidence=evidence,
    )

    assert result.published is True
    assert calls == 2
    assert len(proposal_authority.read_calls) == 2
    assert len(review_authority.read_calls) == 2
    assert len(evidence.calls) == 2


def test_conflicting_pair_fails_without_overwriting_committed_pair(tmp_path: Path):
    proposal_authority, proposal, review_authority, _ = _prepared()
    request = _request(proposal)
    first = _publish(
        request,
        tmp_path,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
    )
    target = tmp_path / first.storage_key
    original = {path.name: path.read_bytes() for path in target.iterdir()}

    with pytest.raises(DatasetPublicationError) as raised:
        _publish(
            request,
            tmp_path,
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            publication_metadata=_metadata(source={"alias": "different"}),
        )

    assert raised.value.code == "PUBLICATION_CONFLICT"
    assert {path.name: path.read_bytes() for path in target.iterdir()} == original


def test_service_has_no_database_runtime_training_or_filesystem_implementation():
    tree = ast.parse(inspect.getsource(integration_module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    source = inspect.getsource(integration_module).lower()
    assert not any(name.startswith(("psycopg", "sqlalchemy")) for name in imports)
    assert (
        not {
            "mkdir",
            "rename",
            "replace",
            "open",
            "write_text",
            "write_bytes",
            "atomicartifactdirectory",
        }
        & calls
    )
    assert not {
        "approval_authority",
        "postgres",
        "sqlite",
        "fastapi",
        "run_training",
        "evaluate_model",
        "promote_model",
    } & set(source.split())
