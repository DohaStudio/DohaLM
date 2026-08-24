from __future__ import annotations

import ast
import inspect
from datetime import timedelta

import pytest
from test_product_dataset_governance import _CurrentEvidenceAuthority
from test_product_dataset_review import (
    FIRST_STARTED_AT,
    _prepared_authority,
    _ReviewAuthority,
    _start,
)
from test_product_dataset_review import (
    _request as review_request,
)

import src.data.product_dataset_approval as integration_module
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalEvidenceStatus,
)
from src.data.dataset_review_authority import DatasetReviewAuthorityError
from src.data.product_dataset_approval import (
    ProductDatasetApprovalRequest,
    approve_product_dataset_version,
)

APPROVED_AT = FIRST_STARTED_AT + timedelta(hours=1)


class _ReadableReviewAuthority(_ReviewAuthority):
    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__(events)
        self.read_calls = []
        self.read_override = None

    def read_authoritative_review(self, identity, *, proposal_fingerprint):
        self.read_calls.append((identity, proposal_fingerprint))
        if self.events is not None:
            self.events.append("review_read")
        if self.read_override is not None:
            return self.read_override
        return super().read_authoritative_review(
            identity,
            proposal_fingerprint=proposal_fingerprint,
        )


class _OrderedEvidenceAuthority(_CurrentEvidenceAuthority):
    def __init__(self, events: list[str], status=None) -> None:
        super().__init__(status) if status is not None else super().__init__()
        self.events = events

    def evaluate_current_proposal_evidence(self, *args, **kwargs):
        self.events.append("current_evidence")
        return super().evaluate_current_proposal_evidence(*args, **kwargs)


def _prepared(events: list[str] | None = None):
    proposal_authority, proposal = _prepared_authority(events)
    review_authority = _ReadableReviewAuthority(events)
    started = _start(
        review_request(proposal),
        proposal_authority=proposal_authority,
        review_authority=review_authority,
    )
    proposal_authority.read_calls.clear()
    review_authority.read_calls.clear()
    if events is not None:
        events.clear()
    return proposal_authority, proposal, review_authority, started


def _approval_request(proposal, **changes):
    values = {
        "identity": proposal.identity,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "approval_evidence_ids": ("dataset_review_product_1",),
        "approved_at": APPROVED_AT,
    }
    values.update(changes)
    return ProductDatasetApprovalRequest(**values)


def _approve(request, *, proposal_authority, review_authority, evidence=None):
    return approve_product_dataset_version(
        request,
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        current_evidence_authority=evidence or _CurrentEvidenceAuthority(),
    )


def test_valid_approval_uses_authoritative_order_and_existing_pure_transition(
    monkeypatch,
):
    events: list[str] = []
    proposal_authority, proposal, review_authority, started = _prepared(events)
    evidence = _OrderedEvidenceAuthority(events)
    original_begin = integration_module.begin_dataset_review
    original_approve = integration_module.approve_dataset_version

    def begin(value):
        events.append("begin_dataset_review")
        return original_begin(value)

    def approve(value, *, approval_evidence_ids):
        events.append("approve_dataset_version")
        return original_approve(value, approval_evidence_ids=approval_evidence_ids)

    monkeypatch.setattr(integration_module, "begin_dataset_review", begin)
    monkeypatch.setattr(integration_module, "approve_dataset_version", approve)
    caller_reviewing_payload = {"status": "approved", "approved": True}

    result = _approve(
        _approval_request(proposal),
        proposal_authority=proposal_authority,
        review_authority=review_authority,
        evidence=evidence,
    )

    assert caller_reviewing_payload != result.payload
    assert events == [
        "proposal_read",
        "review_read",
        "current_evidence",
        "begin_dataset_review",
        "approve_dataset_version",
    ]
    assert result.identity == proposal.identity
    assert result.payload["status"] == "approved"
    assert result.payload["approved"] is True
    assert result.payload["frozen"] is False
    assert result.payload["training_allowed"] is False
    assert review_authority._record is started.review_record


def test_review_not_found_rejects_even_when_caller_has_reviewing_payload(monkeypatch):
    proposal_authority, proposal = _prepared_authority()
    review_authority = _ReadableReviewAuthority()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "approve_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    caller_reviewing_payload = {"status": "reviewing"}

    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _approve(
            _approval_request(proposal),
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert caller_reviewing_payload["status"] == "reviewing"
    assert raised.value.code == "DATASET_REVIEW_AUTHORITY_NOT_FOUND"
    assert calls == []


def test_review_binding_mismatch_fails_before_evidence_and_approval(monkeypatch):
    proposal_authority, proposal, review_authority, _ = _prepared()
    other_authority, other = _prepared_authority()
    del other_authority
    other_request = review_request(
        other,
        proposal_fingerprint="sha256:" + "f" * 64,
    )
    from src.data.dataset_review_authority import build_dataset_review_authority_record

    review_authority.read_override = build_dataset_review_authority_record(
        other_request,
        authority_reference="dataset-review:other",
        authority_version=1,
    )
    evidence = _CurrentEvidenceAuthority()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "approve_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetReviewAuthorityError):
        _approve(
            _approval_request(proposal),
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            evidence=evidence,
        )

    assert evidence.calls == []
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("record_fingerprint", "sha256:" + "0" * 64),
        ("lifecycle_state", "approved"),
        ("reviewer_reference", "private reviewer value"),
        ("authority_reference", "private authority value"),
    ),
)
def test_corrupted_review_fails_closed(field, value, monkeypatch):
    proposal_authority, proposal, review_authority, _ = _prepared()
    corrupt = object.__new__(type(review_authority._record))
    for name in review_authority._record.__dataclass_fields__:
        object.__setattr__(
            corrupt,
            name,
            value if name == field else getattr(review_authority._record, name),
        )
    review_authority.read_override = corrupt
    calls = []
    monkeypatch.setattr(
        integration_module,
        "approve_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _approve(
            _approval_request(proposal),
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert "private" not in str(raised.value)
    assert calls == []


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
def test_non_current_approval_evidence_fails_before_transition(
    status,
    monkeypatch,
):
    proposal_authority, proposal, review_authority, _ = _prepared()
    calls = []
    monkeypatch.setattr(
        integration_module,
        "approve_dataset_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(DatasetProposalAuthorityError):
        _approve(
            _approval_request(proposal),
            proposal_authority=proposal_authority,
            review_authority=review_authority,
            evidence=_CurrentEvidenceAuthority(status),
        )

    assert calls == []


def test_proposal_and_review_records_remain_immutable_after_approval():
    proposal_authority, proposal, review_authority, started = _prepared()
    proposal_record = proposal_authority.records[proposal.identity][0]
    review_record = review_authority._record

    _approve(
        _approval_request(proposal),
        proposal_authority=proposal_authority,
        review_authority=review_authority,
    )

    assert proposal_authority.records[proposal.identity][0] is proposal_record
    assert proposal_record.status == "draft"
    assert review_authority._record is review_record is started.review_record
    assert review_record.lifecycle_state == "reviewing"


def test_request_has_no_caller_payload_and_dependencies_are_explicit():
    request_fields = tuple(ProductDatasetApprovalRequest.__dataclass_fields__)
    assert request_fields == (
        "identity",
        "proposal_fingerprint",
        "approval_evidence_ids",
        "approved_at",
    )
    signature = inspect.signature(approve_product_dataset_version)
    assert tuple(signature.parameters) == (
        "request",
        "proposal_authority",
        "review_authority",
        "current_evidence_authority",
    )
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )


def test_integration_has_no_storage_publication_training_api_or_runtime_surface():
    tree = ast.parse(inspect.getsource(integration_module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    source = inspect.getsource(integration_module).lower()
    assert not any(name.startswith(("psycopg", "sqlalchemy")) for name in imports)
    assert not {
        "publish_dataset_version",
        "run_training",
        "evaluate_model",
        "promote_model",
        "postgres",
        "sqlite",
        "fastapi",
        "approval_authority",
    } & set(source.split())
