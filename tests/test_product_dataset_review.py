from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from test_product_dataset_governance import (
    _AtomicProposalAuthority,
    _CurrentEvidenceAuthority,
    _propose,
)

import src.data.product_dataset_review as integration_module
from src.data.dataset_governance import DatasetVersionIdentity, DatasetVersionProposal
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalEvidenceStatus,
)
from src.data.dataset_review_authority import (
    DatasetReviewAuthorityError,
    DatasetReviewOutcome,
    DatasetReviewStartRequest,
    DatasetReviewStartResult,
    build_dataset_review_authority_record,
    dataset_review_start_requests_equivalent,
    validate_dataset_review_authority_record,
)
from src.data.product_dataset_review import start_product_dataset_review

FIRST_STARTED_AT = datetime(
    2026,
    8,
    24,
    12,
    0,
    tzinfo=timezone(timedelta(hours=9)),
)


class _ReadableProposalAuthority(_AtomicProposalAuthority):
    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__()
        self.events = events
        self.read_calls: list[DatasetVersionIdentity] = []
        self.read_override = None

    def read_authoritative_proposal(self, identity):
        self.read_calls.append(identity)
        if self.events is not None:
            self.events.append("proposal_read")
        record = super().read_authoritative_proposal(identity)
        return self.read_override or record


class _ReviewAuthority:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events
        self.calls: list[DatasetReviewStartRequest] = []
        self.writes = 0
        self._request: DatasetReviewStartRequest | None = None
        self._record = None

    def start_review(self, request: DatasetReviewStartRequest):
        self.calls.append(request)
        if self.events is not None:
            self.events.append("review_start")
        if self._record is None:
            self._request = request
            self._record = build_dataset_review_authority_record(
                request,
                authority_reference="dataset-review:product-test",
                authority_version=1,
            )
            self.writes += 1
            outcome = DatasetReviewOutcome.STARTED
            record = self._record
        elif dataset_review_start_requests_equivalent(self._request, request):
            outcome = DatasetReviewOutcome.REPLAYED
            record = self._record
        else:
            outcome = DatasetReviewOutcome.CONFLICT
            record = None
        return DatasetReviewStartResult(
            outcome=outcome,
            identity=request.identity,
            proposal_fingerprint=request.proposal_fingerprint,
            authority_reference="dataset-review:product-test",
            authority_version=1,
            record=record,
        )

    def read_authoritative_review(self, identity, *, proposal_fingerprint):
        if self._record is None:
            raise DatasetReviewAuthorityError(
                "DATASET_REVIEW_AUTHORITY_NOT_FOUND",
                "read",
                identity=identity,
            )
        return validate_dataset_review_authority_record(
            self._record,
            expected_identity=identity,
            expected_proposal_fingerprint=proposal_fingerprint,
        )


class _OrderedEvidenceAuthority(_CurrentEvidenceAuthority):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def evaluate_current_proposal_evidence(self, *args, **kwargs):
        self.events.append("current_evidence")
        return super().evaluate_current_proposal_evidence(*args, **kwargs)


def _prepared_authority(events: list[str] | None = None):
    authority = _ReadableProposalAuthority(events)
    proposal_result = _propose(authority=authority)
    authority.read_calls.clear()
    if events is not None:
        events.clear()
    return authority, proposal_result


def _request(proposal_result, **changes):
    values = {
        "identity": proposal_result.identity,
        "proposal_fingerprint": proposal_result.proposal_fingerprint,
        "reviewer_reference": "reviewer:product-owner-1",
        "review_started_at": FIRST_STARTED_AT,
        "request_reference": "request:review-start-1",
    }
    values.update(changes)
    return DatasetReviewStartRequest(**values)


def _start(request, *, proposal_authority, evidence=None, review_authority=None):
    return start_product_dataset_review(
        request,
        proposal_authority=proposal_authority,
        current_evidence_authority=evidence or _CurrentEvidenceAuthority(),
        review_authority=review_authority or _ReviewAuthority(),
    )


def test_started_uses_required_order_and_existing_pure_transition(monkeypatch):
    events: list[str] = []
    proposal_authority, proposal = _prepared_authority(events)
    evidence = _OrderedEvidenceAuthority(events)
    review_authority = _ReviewAuthority(events)
    original_transition = integration_module.begin_dataset_review

    def transition(value):
        events.append("begin_dataset_review")
        return original_transition(value)

    monkeypatch.setattr(integration_module, "begin_dataset_review", transition)
    result = _start(
        _request(proposal),
        proposal_authority=proposal_authority,
        evidence=evidence,
        review_authority=review_authority,
    )

    assert events == [
        "proposal_read",
        "current_evidence",
        "review_start",
        "begin_dataset_review",
    ]
    assert result.outcome is DatasetReviewOutcome.STARTED
    assert result.identity == proposal.identity
    assert result.proposal_fingerprint == proposal.proposal_fingerprint
    assert result.reviewing_proposal.status == "reviewing"
    assert result.reviewing_proposal.payload["approved"] is False
    assert result.reviewing_proposal.payload["frozen"] is False
    assert result.reviewing_proposal.payload["training_allowed"] is False
    assert proposal_authority.records[proposal.identity][0].status == "draft"


def test_replay_rechecks_evidence_and_preserves_first_record_time():
    proposal_authority, proposal = _prepared_authority()
    evidence = _CurrentEvidenceAuthority()
    review_authority = _ReviewAuthority()
    first_request = _request(proposal)
    retry_request = _request(
        proposal,
        review_started_at=FIRST_STARTED_AT + timedelta(days=1),
    )

    first = _start(
        first_request,
        proposal_authority=proposal_authority,
        evidence=evidence,
        review_authority=review_authority,
    )
    replay = _start(
        retry_request,
        proposal_authority=proposal_authority,
        evidence=evidence,
        review_authority=review_authority,
    )

    assert first.outcome is DatasetReviewOutcome.STARTED
    assert replay.outcome is DatasetReviewOutcome.REPLAYED
    assert replay.review_record is first.review_record
    assert replay.review_record.review_started_at == FIRST_STARTED_AT
    assert replay.reviewing_proposal.payload == first.reviewing_proposal.payload
    assert [call[2] for call in evidence.calls] == [
        first_request.review_started_at,
        retry_request.review_started_at,
    ]
    assert review_authority.writes == 1
    assert proposal_authority.records[proposal.identity][0].status == "draft"


def test_revoked_evidence_after_start_blocks_replay_and_preserves_history():
    proposal_authority, proposal = _prepared_authority()
    evidence = _CurrentEvidenceAuthority()
    review_authority = _ReviewAuthority()
    request = _request(proposal)
    started = _start(
        request,
        proposal_authority=proposal_authority,
        evidence=evidence,
        review_authority=review_authority,
    )
    evidence.status = DatasetProposalEvidenceStatus.REVOKED

    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_REVOKED",
    ):
        _start(
            request,
            proposal_authority=proposal_authority,
            evidence=evidence,
            review_authority=review_authority,
        )

    assert len(review_authority.calls) == review_authority.writes == 1
    assert (
        review_authority.read_authoritative_review(
            proposal.identity,
            proposal_fingerprint=proposal.proposal_fingerprint,
        )
        is started.review_record
    )


def test_expected_fingerprint_mismatch_stops_before_evidence_and_review():
    proposal_authority, proposal = _prepared_authority()
    evidence = _CurrentEvidenceAuthority()
    review_authority = _ReviewAuthority()

    with pytest.raises(
        DatasetProposalAuthorityError,
        match="DATASET_PROPOSAL_FINGERPRINT_MISMATCH",
    ):
        _start(
            _request(proposal, proposal_fingerprint="sha256:" + "f" * 64),
            proposal_authority=proposal_authority,
            evidence=evidence,
            review_authority=review_authority,
        )

    assert evidence.calls == []
    assert review_authority.calls == []
    assert review_authority.writes == 0


@pytest.mark.parametrize("failure", ("not_found", "unavailable"))
def test_proposal_read_failure_is_sanitized_and_never_calls_review(failure):
    proposal_authority, proposal = _prepared_authority()
    if failure == "not_found":
        proposal_authority.records.clear()
    else:
        proposal_authority.read_authoritative_proposal = lambda identity: (
            _ for _ in ()
        ).throw(  # type: ignore[method-assign]
            RuntimeError("private database detail")
        )
    evidence = _CurrentEvidenceAuthority()
    review_authority = _ReviewAuthority()

    with pytest.raises(DatasetProposalAuthorityError) as raised:
        _start(
            _request(proposal),
            proposal_authority=proposal_authority,
            evidence=evidence,
            review_authority=review_authority,
        )

    assert raised.value.code in {
        "DATASET_PROPOSAL_AUTHORITY_NOT_FOUND",
        "PROPOSAL_AUTHORITY_UNAVAILABLE",
    }
    assert "private" not in str(raised.value)
    assert evidence.calls == []
    assert review_authority.calls == []


@pytest.mark.parametrize(
    "corruption", ("identity", "fingerprint", "payload", "metadata")
)
def test_corrupt_authoritative_proposal_stops_before_evidence_and_review(corruption):
    proposal_authority, proposal = _prepared_authority()
    record = proposal_authority.read_authoritative_proposal(proposal.identity)
    if corruption == "identity":
        value = replace(
            record,
            identity=DatasetVersionIdentity("other_object", "other_dataset", "2.0.0"),
        )
    elif corruption == "fingerprint":
        value = replace(record, proposal_fingerprint="sha256:" + "e" * 64)
    elif corruption == "metadata":
        value = replace(record, authority_reference="private path")
    else:
        invalid = object.__new__(DatasetVersionProposal)
        object.__setattr__(invalid, "_canonical_payload", b"{}")
        value = replace(record, proposal=invalid)
    proposal_authority.read_override = value
    evidence = _CurrentEvidenceAuthority()
    review_authority = _ReviewAuthority()

    with pytest.raises(DatasetProposalAuthorityError):
        _start(
            _request(proposal),
            proposal_authority=proposal_authority,
            evidence=evidence,
            review_authority=review_authority,
        )

    assert evidence.calls == []
    assert review_authority.calls == []


@pytest.mark.parametrize(
    ("source", "status"),
    (
        ("rights_missing", DatasetProposalEvidenceStatus.MISSING),
        ("rights_expired", DatasetProposalEvidenceStatus.EXPIRED),
        ("rights_revoked", DatasetProposalEvidenceStatus.REVOKED),
        ("rights_identity", DatasetProposalEvidenceStatus.IDENTITY_MISMATCH),
        ("eligibility_missing", DatasetProposalEvidenceStatus.MISSING),
        ("eligibility_invalid", DatasetProposalEvidenceStatus.INVALID),
        ("eligibility_expired", DatasetProposalEvidenceStatus.EXPIRED),
        ("eligibility_revoked", DatasetProposalEvidenceStatus.REVOKED),
        ("eligibility_identity", DatasetProposalEvidenceStatus.IDENTITY_MISMATCH),
    ),
)
def test_non_current_rights_or_eligibility_never_calls_review_authority(source, status):
    del source
    proposal_authority, proposal = _prepared_authority()
    review_authority = _ReviewAuthority()

    with pytest.raises(DatasetProposalAuthorityError):
        _start(
            _request(proposal),
            proposal_authority=proposal_authority,
            evidence=_CurrentEvidenceAuthority(status),
            review_authority=review_authority,
        )

    assert review_authority.calls == []
    assert review_authority.writes == 0


@pytest.mark.parametrize(
    "change",
    (
        {"reviewer_reference": "reviewer:other"},
        {"request_reference": "request:other"},
    ),
)
def test_conflict_is_sanitized_and_preserves_existing_record(change):
    proposal_authority, proposal = _prepared_authority()
    review_authority = _ReviewAuthority()
    first = _start(
        _request(proposal),
        proposal_authority=proposal_authority,
        review_authority=review_authority,
    )

    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _start(
            _request(proposal, **change),
            proposal_authority=proposal_authority,
            review_authority=review_authority,
        )

    assert raised.value.code == "DATASET_REVIEW_START_CONFLICT"
    assert "reviewer" not in str(raised.value)
    assert "request" not in str(raised.value)
    assert review_authority.writes == 1
    assert review_authority._record is first.review_record
    assert proposal_authority.records[proposal.identity][0].status == "draft"


@pytest.mark.parametrize("failure", ("missing", "unavailable", "invalid_result"))
def test_review_authority_failures_are_sanitized_after_evidence(failure):
    proposal_authority, proposal = _prepared_authority()
    evidence = _CurrentEvidenceAuthority()
    if failure == "missing":
        review_authority = object()
    elif failure == "unavailable":

        class Unavailable:
            def start_review(self, request):
                del request
                raise RuntimeError("private review backend detail")

        review_authority = Unavailable()
    else:

        class Invalid:
            def start_review(self, request):
                del request
                return object()

        review_authority = Invalid()

    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _start(
            _request(proposal),
            proposal_authority=proposal_authority,
            evidence=evidence,
            review_authority=review_authority,
        )

    assert raised.value.code in {
        "DATASET_REVIEW_AUTHORITY_MISSING",
        "DATASET_REVIEW_AUTHORITY_UNAVAILABLE",
        "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
    }
    assert "private" not in str(raised.value)
    assert len(evidence.calls) == 1


def test_dependencies_are_explicit_and_no_payload_or_hidden_clock_is_accepted():
    signature = inspect.signature(start_product_dataset_review)
    assert tuple(signature.parameters) == (
        "request",
        "proposal_authority",
        "current_evidence_authority",
        "review_authority",
    )
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )


def test_integration_has_no_direct_storage_api_approval_publication_or_training():
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
        "approve_dataset_version",
        "publish_dataset_version",
        "run_training",
        "evaluate_model",
        "promote_model",
        "postgres",
        "sqlite",
        "fastapi",
    } & set(source.split())
