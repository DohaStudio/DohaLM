from __future__ import annotations

import ast
import inspect
from copy import copy
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

import src.data.dataset_review_authority as review_authority_module
from src.data.dataset_governance import (
    DatasetVersionIdentity,
    begin_dataset_review,
    propose_dataset_version,
)
from src.data.dataset_review_authority import (
    DatasetReviewAuthority,
    DatasetReviewAuthorityError,
    DatasetReviewAuthorityRecord,
    DatasetReviewOutcome,
    DatasetReviewStartRequest,
    DatasetReviewStartResult,
    build_dataset_review_authority_record,
    dataset_review_authority_record_fingerprint,
    dataset_review_start_requests_equivalent,
    validate_dataset_review_authority_record,
    validate_dataset_review_start_request,
    validate_dataset_review_start_result,
)

IDENTITY = DatasetVersionIdentity(
    "dataset_version_product_1",
    "dataset_product",
    "1.0.0",
)
PROPOSAL_FINGERPRINT = "sha256:" + "a" * 64
STARTED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=9)))
AUTHORITY_REFERENCE = "dataset-review:authority-1"


def _request(**updates) -> DatasetReviewStartRequest:
    values = {
        "identity": IDENTITY,
        "proposal_fingerprint": PROPOSAL_FINGERPRINT,
        "reviewer_reference": "reviewer:user-123",
        "review_started_at": STARTED_AT,
        "request_reference": "request:req-abc",
    }
    values.update(updates)
    return DatasetReviewStartRequest(**values)


def _record(
    request: DatasetReviewStartRequest | None = None,
    **metadata,
) -> DatasetReviewAuthorityRecord:
    values = {
        "authority_reference": AUTHORITY_REFERENCE,
        "authority_version": 1,
    }
    values.update(metadata)
    return build_dataset_review_authority_record(request or _request(), **values)


def _result(
    outcome: DatasetReviewOutcome,
    *,
    request: DatasetReviewStartRequest | None = None,
    record: DatasetReviewAuthorityRecord | None = None,
) -> DatasetReviewStartResult:
    submitted = request or _request()
    authoritative = record
    if authoritative is None and outcome is not DatasetReviewOutcome.CONFLICT:
        authoritative = _record(submitted)
    return DatasetReviewStartResult(
        outcome=outcome,
        identity=submitted.identity,
        proposal_fingerprint=submitted.proposal_fingerprint,
        authority_reference=AUTHORITY_REFERENCE,
        authority_version=1,
        record=authoritative,
    )


class _FakeReviewAuthority:
    """Test-only semantic fake; it is not a production persistence fallback."""

    def __init__(self) -> None:
        self._request: DatasetReviewStartRequest | None = None
        self._record: DatasetReviewAuthorityRecord | None = None

    def start_review(
        self,
        request: DatasetReviewStartRequest,
    ) -> DatasetReviewStartResult:
        if self._record is None:
            self._request = request
            self._record = _record(request)
            return _result(
                DatasetReviewOutcome.STARTED, request=request, record=self._record
            )
        if dataset_review_start_requests_equivalent(self._request, request):
            return _result(
                DatasetReviewOutcome.REPLAYED,
                request=request,
                record=self._record,
            )
        return _result(DatasetReviewOutcome.CONFLICT, request=request)

    def read_authoritative_review(
        self,
        identity: DatasetVersionIdentity,
        *,
        proposal_fingerprint: str,
    ) -> DatasetReviewAuthorityRecord:
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


def _draft_payload() -> dict:
    return {
        "schema_name": "dataset_version",
        "schema_version": "1.0.0",
        "object_id": IDENTITY.object_id,
        "created_at": "2026-08-24T00:00:00Z",
        "created_by": "actor_test",
        "producer": {"name": "synthetic-test", "version": "1.0.0"},
        "dataset_id": IDENTITY.dataset_id,
        "dataset_version": IDENTITY.dataset_version,
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
        "created_from": "sha256:" + "b" * 64,
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
        "content_fingerprint": "sha256:" + "c" * 64,
    }


def test_valid_request_is_immutable_and_preserves_explicit_values():
    request = _request()
    assert request.identity == IDENTITY
    assert request.proposal_fingerprint == PROPOSAL_FINGERPRINT
    assert request.reviewer_reference == "reviewer:user-123"
    assert request.review_started_at == STARTED_AT
    assert request.request_reference == "request:req-abc"
    with pytest.raises(FrozenInstanceError):
        request.reviewer_reference = "reviewer:other"


@pytest.mark.parametrize("reviewer", ["", " ", "reviewer/raw", "한글"])
def test_blank_or_malformed_reviewer_is_rejected(reviewer):
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _request(reviewer_reference=reviewer)
    assert raised.value.code == "REVIEWER_REFERENCE_INVALID"


def test_timezone_aware_timestamp_is_required_without_hidden_clock():
    assert _request().review_started_at.utcoffset() == timedelta(hours=9)
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _request(review_started_at=STARTED_AT.replace(tzinfo=None))
    assert raised.value.code == "REVIEW_STARTED_AT_INVALID"
    assert (
        inspect.signature(DatasetReviewStartRequest)
        .parameters["review_started_at"]
        .default
        is inspect.Parameter.empty
    )


@pytest.mark.parametrize(
    "reference",
    ["", "free form note", "C:\\private\\source", "https://source/path", "line\nbody"],
)
def test_raw_or_unsafe_request_reference_is_rejected(reference):
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _request(request_reference=reference)
    assert raised.value.code == "REVIEW_REQUEST_REFERENCE_INVALID"


def test_request_shape_cannot_store_raw_dataset_prompt_token_or_evidence_body():
    assert {field.name for field in fields(DatasetReviewStartRequest)} == {
        "identity",
        "proposal_fingerprint",
        "reviewer_reference",
        "review_started_at",
        "request_reference",
    }


def test_forged_or_corrupted_request_fails_closed_without_normalization():
    request = _request()
    corrupted = copy(request)
    object.__setattr__(corrupted, "reviewer_reference", "raw reviewer note")
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        validate_dataset_review_start_request(corrupted)
    assert raised.value.code == "REVIEWER_REFERENCE_INVALID"
    assert corrupted.reviewer_reference == "raw reviewer note"


def test_logical_retry_equivalence_ignores_only_review_started_at():
    retry = _request(review_started_at=STARTED_AT + timedelta(minutes=2))
    assert dataset_review_start_requests_equivalent(_request(), retry)
    assert not dataset_review_start_requests_equivalent(
        _request(),
        _request(reviewer_reference="reviewer:user-456"),
    )
    assert not dataset_review_start_requests_equivalent(
        _request(),
        _request(request_reference="request:req-other"),
    )
    assert not dataset_review_start_requests_equivalent(
        _request(),
        _request(proposal_fingerprint="sha256:" + "b" * 64),
    )


def test_record_preserves_binding_state_authority_and_safe_reference():
    record = _record()
    assert record.identity == IDENTITY
    assert record.proposal_fingerprint == PROPOSAL_FINGERPRINT
    assert record.reviewer_reference == "reviewer:user-123"
    assert record.review_started_at == STARTED_AT
    assert record.request_reference == "request:req-abc"
    assert record.lifecycle_state == "reviewing"
    assert record.authority_reference == AUTHORITY_REFERENCE
    assert record.authority_version == 1
    assert record.approved is record.frozen is record.training_allowed is False
    with pytest.raises(FrozenInstanceError):
        record.lifecycle_state = "approved"


def test_record_fingerprint_is_deterministic_and_normalizes_same_instant():
    first = _record()
    same_instant = _record(
        _request(review_started_at=STARTED_AT.astimezone(timezone.utc))
    )
    assert first.record_fingerprint == same_instant.record_fingerprint
    assert dataset_review_authority_record_fingerprint(first) == (
        first.record_fingerprint
    )


@pytest.mark.parametrize(
    "changed",
    [
        _request(
            identity=DatasetVersionIdentity(
                "dataset_version_2", "dataset_product", "1.0.0"
            )
        ),
        _request(proposal_fingerprint="sha256:" + "b" * 64),
        _request(reviewer_reference="reviewer:user-456"),
        _request(review_started_at=STARTED_AT + timedelta(seconds=1)),
        _request(request_reference="request:req-other"),
    ],
)
def test_record_fingerprint_detects_meaning_field_changes(changed):
    assert _record(changed).record_fingerprint != _record().record_fingerprint


def test_record_fingerprint_detects_authority_metadata_changes():
    assert _record(
        authority_reference="dataset-review:authority-2"
    ).record_fingerprint != (_record().record_fingerprint)
    assert (
        _record(authority_version=2).record_fingerprint != _record().record_fingerprint
    )


@pytest.mark.parametrize(
    ("reference", "version"),
    [
        ("", 1),
        ("authority/path", 1),
        (AUTHORITY_REFERENCE, 0),
        (AUTHORITY_REFERENCE, True),
    ],
)
def test_authority_reference_and_revision_are_validated(reference, version):
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _record(authority_reference=reference, authority_version=version)
    assert raised.value.code == "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"


@pytest.mark.parametrize(
    "outcome", [DatasetReviewOutcome.STARTED, DatasetReviewOutcome.REPLAYED]
)
def test_started_and_replayed_results_return_exact_reviewing_record(outcome):
    result = _result(outcome)
    validated = validate_dataset_review_start_result(result, _request())
    assert validated.outcome is outcome
    assert validated.record.lifecycle_state == "reviewing"
    assert validated.record.approved is False
    assert validated.record.frozen is False
    assert validated.record.training_allowed is False


def test_conflict_result_has_no_record_and_no_mutation_payload():
    result = _result(DatasetReviewOutcome.CONFLICT)
    assert result.outcome is DatasetReviewOutcome.CONFLICT
    assert result.record is None
    assert validate_dataset_review_start_result(result, _request()) is result


def test_retry_returns_first_record_and_preserves_first_timestamp():
    authority = _FakeReviewAuthority()
    first = authority.start_review(_request())
    retry_request = _request(review_started_at=STARTED_AT + timedelta(minutes=2))
    replay = authority.start_review(retry_request)
    assert first.outcome is DatasetReviewOutcome.STARTED
    assert replay.outcome is DatasetReviewOutcome.REPLAYED
    assert replay.record is first.record
    assert replay.record.review_started_at == STARTED_AT


def test_different_reviewer_reference_or_proposal_binding_conflicts():
    authority = _FakeReviewAuthority()
    authority.start_review(_request())
    for request in (
        _request(reviewer_reference="reviewer:user-456"),
        _request(request_reference="request:req-other"),
        _request(proposal_fingerprint="sha256:" + "b" * 64),
    ):
        result = authority.start_review(request)
        assert result.outcome is DatasetReviewOutcome.CONFLICT
        assert result.record is None


def test_authoritative_read_port_signature_and_exact_record_behavior():
    start = inspect.signature(DatasetReviewAuthority.start_review)
    read = inspect.signature(DatasetReviewAuthority.read_authoritative_review)
    assert tuple(start.parameters) == ("self", "request")
    assert tuple(read.parameters) == ("self", "identity", "proposal_fingerprint")
    assert (
        read.parameters["proposal_fingerprint"].kind is inspect.Parameter.KEYWORD_ONLY
    )

    authority = _FakeReviewAuthority()
    started = authority.start_review(_request())
    loaded = authority.read_authoritative_review(
        IDENTITY,
        proposal_fingerprint=PROPOSAL_FINGERPRINT,
    )
    assert loaded is started.record


def test_authoritative_read_not_found_is_a_typed_sanitized_failure():
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        _FakeReviewAuthority().read_authoritative_review(
            IDENTITY,
            proposal_fingerprint=PROPOSAL_FINGERPRINT,
        )
    assert raised.value.code == "DATASET_REVIEW_AUTHORITY_NOT_FOUND"
    assert str(raised.value) == (
        "DATASET_REVIEW_AUTHORITY_NOT_FOUND:read:dataset_review_authority"
    )


def test_authoritative_read_identity_and_proposal_mismatch_fail_closed():
    record = _record()
    with pytest.raises(DatasetReviewAuthorityError) as identity_error:
        validate_dataset_review_authority_record(
            record,
            expected_identity=DatasetVersionIdentity(
                "dataset_version_2", "dataset_product", "1.0.0"
            ),
            expected_proposal_fingerprint=PROPOSAL_FINGERPRINT,
        )
    assert identity_error.value.code == "DATASET_REVIEW_IDENTITY_MISMATCH"

    with pytest.raises(DatasetReviewAuthorityError) as fingerprint_error:
        validate_dataset_review_authority_record(
            record,
            expected_identity=IDENTITY,
            expected_proposal_fingerprint="sha256:" + "b" * 64,
        )
    assert fingerprint_error.value.code == (
        "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity", DatasetVersionIdentity("bad/path", "dataset_product", "1.0.0")),
        ("proposal_fingerprint", "sha256:" + "G" * 64),
        ("reviewer_reference", "raw reviewer note"),
        ("review_started_at", STARTED_AT.replace(tzinfo=None)),
        ("lifecycle_state", "approved"),
        ("record_fingerprint", "sha256:" + "0" * 64),
        ("authority_reference", "C:\\private\\authority"),
        ("authority_version", 0),
    ],
)
def test_corrupted_authoritative_record_fails_closed_without_repair(field, value):
    record = _record()
    corrupted = copy(record)
    object.__setattr__(corrupted, field, value)
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        validate_dataset_review_authority_record(
            corrupted,
            expected_identity=IDENTITY,
            expected_proposal_fingerprint=PROPOSAL_FINGERPRINT,
        )
    assert raised.value.code == "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"
    assert getattr(corrupted, field) == value


def test_invalid_result_binding_fails_closed():
    mismatched = _result(
        DatasetReviewOutcome.CONFLICT,
        request=_request(
            identity=DatasetVersionIdentity(
                "dataset_version_2", "dataset_product", "1.0.0"
            )
        ),
    )
    with pytest.raises(DatasetReviewAuthorityError) as raised:
        validate_dataset_review_start_result(mismatched, _request())
    assert raised.value.code == "DATASET_REVIEW_IDENTITY_MISMATCH"


def test_begin_dataset_review_remains_a_pure_matching_domain_transition():
    proposal = propose_dataset_version(_draft_payload())
    reviewed = begin_dataset_review(proposal)
    record = _record()
    assert proposal.status == "draft"
    assert reviewed.status == record.lifecycle_state == "reviewing"
    assert reviewed.identity == record.identity
    assert reviewed.payload["approved"] is record.approved is False
    assert reviewed.payload["frozen"] is record.frozen is False
    assert reviewed.payload["training_allowed"] is record.training_allowed is False


def test_contract_has_no_postgres_persistence_or_downstream_side_effects():
    tree = ast.parse(inspect.getsource(review_authority_module))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {
        "begin_dataset_review",
        "approve_dataset_version",
        "publish_dataset_version",
        "run_training",
        "evaluate_model",
        "promote_model",
    }
    source = inspect.getsource(review_authority_module).lower()
    assert not {"postgres", "psycopg", "create table", "insert into"} & set(
        source.split()
    )
