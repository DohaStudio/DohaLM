from __future__ import annotations

import ast
import inspect
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest

import src.data.dataset_proposal_authority as authority_module
import src.data.postgres_dataset_proposal_authority as postgres_authority_module
from src.data.checksums import canonical_json_bytes
from src.data.dataset_governance import (
    DatasetVersionIdentity,
    DatasetVersionProposal,
    propose_dataset_version,
)
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalAuthorityRecord,
    DatasetProposalAuthorityResult,
    DatasetProposalEvidenceDecision,
    DatasetProposalEvidenceStatus,
    DatasetProposalOutcome,
    adjudicate_dataset_version_proposal,
    dataset_version_proposal_fingerprint,
)

PROPOSED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)


def _payload(**updates) -> dict:
    value = {
        "schema_name": "dataset_version",
        "schema_version": "1.0.0",
        "object_id": "dataset_version_product_1",
        "created_at": "2026-08-20T00:00:00Z",
        "created_by": "dataset_governance_owner",
        "producer": {"name": "dohalm-product-governance", "version": "1.0.0"},
        "workspace_id": "workspace_test",
        "dataset_id": "dataset_product",
        "dataset_version": "1.0.0",
        "status": "draft",
        "usage_purpose": "lyrics_training",
        "task": "lyrics_generation",
        "lineage": [
            {
                "object_id": "candidate_train",
                "schema_name": "learning_candidate",
                "schema_version": "1.0.0",
                "content_fingerprint": "sha256:" + "a" * 64,
            },
            {
                "object_id": "candidate_validation",
                "schema_name": "learning_candidate",
                "schema_version": "1.0.0",
                "content_fingerprint": "sha256:" + "b" * 64,
            },
            {
                "object_id": "candidate_test",
                "schema_name": "learning_candidate",
                "schema_version": "1.0.0",
                "content_fingerprint": "sha256:" + "c" * 64,
            },
        ],
        "created_from": "sha256:" + "d" * 64,
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
        "schema_manifest_id": "record_schema_product_1",
        "rights_summary": {"status": "pass", "exception_count": 0},
        "dataset_eligibility_evidence_id": "dataset_gate_product_1",
        "approval_evidence_ids": ["dataset_review_product_1"],
        "approved": False,
        "frozen": False,
        "training_allowed": False,
        "dataset_manifest_id": "dataset_manifest_product_1",
        "content_fingerprint": "sha256:" + "e" * 64,
        "extensions": {
            "dohalm.product_dataset_composition": {
                "composition_id": "composition:sha256:" + "f" * 64,
                "handoff_ids": ["handoff:sha256:" + "1" * 64],
            }
        },
    }
    value.update(updates)
    return value


class _CurrentEvidenceAuthority:
    def __init__(
        self,
        status: DatasetProposalEvidenceStatus = DatasetProposalEvidenceStatus.CURRENT,
        *,
        identity_mismatch: bool = False,
    ) -> None:
        self.status = status
        self.identity_mismatch = identity_mismatch
        self.calls: list[tuple[object, str, datetime]] = []

    def evaluate_current_proposal_evidence(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
        proposed_at: datetime,
    ) -> DatasetProposalEvidenceDecision:
        self.calls.append((proposal.identity, proposal_fingerprint, proposed_at))
        identity = proposal.identity
        if self.identity_mismatch:
            identity = type(identity)("dataset_version_other", "dataset_other", "2.0.0")
        return DatasetProposalEvidenceDecision(
            status=self.status,
            identity=identity,
            proposal_fingerprint=proposal_fingerprint,
            authority_reference="authority:current-evidence:test",
            authority_version=1,
        )


class _AtomicProposalAuthority:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[object, tuple[DatasetVersionProposal, str, int]] = {}
        self.calls = 0

    def compare_and_create(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
    ) -> DatasetProposalAuthorityResult:
        with self._lock:
            self.calls += 1
            existing = self._records.get(proposal.identity)
            if existing is None:
                stored = (proposal, proposal_fingerprint, 1)
                self._records[proposal.identity] = stored
                outcome = DatasetProposalOutcome.CREATED
            elif existing[1] == proposal_fingerprint:
                stored = existing
                outcome = DatasetProposalOutcome.REPLAYED
            else:
                raise DatasetProposalAuthorityError(
                    "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
                    "compare_and_create",
                    identity=proposal.identity,
                    existing_fingerprint=existing[1],
                    incoming_fingerprint=proposal_fingerprint,
                )
            return DatasetProposalAuthorityResult(
                outcome=outcome,
                proposal=stored[0],
                identity=stored[0].identity,
                proposal_fingerprint=stored[1],
                authority_reference="authority:dataset-proposal:test",
                authority_version=stored[2],
            )

    def read_authoritative_proposal(
        self,
        identity: DatasetVersionIdentity,
    ) -> DatasetProposalAuthorityRecord:
        if type(identity) is not DatasetVersionIdentity or any(
            type(value) is not str or not 1 <= len(value) <= 256
            for value in (
                getattr(identity, "object_id", None),
                getattr(identity, "dataset_id", None),
                getattr(identity, "dataset_version", None),
            )
        ):
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_IDENTITY_INVALID",
                "read",
            )
        stored = self._records.get(identity)
        if stored is None:
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_NOT_FOUND",
                "read",
                identity=identity,
            )
        return DatasetProposalAuthorityRecord(
            proposal=stored[0],
            identity=stored[0].identity,
            proposal_fingerprint=stored[1],
            authority_reference="authority:dataset-proposal:test",
            authority_version=stored[2],
        )


def _adjudicate(
    payload: dict | None = None,
    *,
    authority: object | None = None,
    evidence: object | None = None,
    proposed_at: datetime = PROPOSED_AT,
):
    return adjudicate_dataset_version_proposal(
        payload or _payload(),
        authority=authority or _AtomicProposalAuthority(),
        current_evidence_authority=evidence or _CurrentEvidenceAuthority(),
        proposed_at=proposed_at,
    )


def test_absent_proposal_is_created_as_immutable_draft():
    result = _adjudicate()
    assert result.outcome is DatasetProposalOutcome.CREATED
    assert type(result.proposal) is DatasetVersionProposal
    assert result.proposal.status == "draft"
    assert result.proposal.payload["approved"] is False
    assert result.proposal.payload["frozen"] is False
    assert result.proposal.payload["training_allowed"] is False
    assert result.proposal_fingerprint == dataset_version_proposal_fingerprint(
        result.proposal
    )


def test_same_canonical_proposal_replays_existing_object():
    authority = _AtomicProposalAuthority()
    first = _adjudicate(authority=authority)
    second = _adjudicate(authority=authority)
    assert first.outcome is DatasetProposalOutcome.CREATED
    assert second.outcome is DatasetProposalOutcome.REPLAYED
    assert second.proposal is first.proposal
    assert authority.calls == 2


def test_fake_authoritative_read_returns_immutable_created_record_without_mutation():
    authority = _AtomicProposalAuthority()
    created = _adjudicate(authority=authority)
    before = dict(authority._records)

    loaded = authority.read_authoritative_proposal(created.identity)

    assert loaded == DatasetProposalAuthorityRecord(
        proposal=created.proposal,
        identity=created.identity,
        proposal_fingerprint=created.proposal_fingerprint,
        authority_reference=created.authority_reference,
        authority_version=created.authority_version,
    )
    assert authority._records == before
    with pytest.raises(FrozenInstanceError):
        loaded.authority_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "malformed_identity",
    [
        "missing",
        DatasetVersionIdentity("", "dataset", "1.0.0"),
        DatasetVersionIdentity("object", "d" * 257, "1.0.0"),
    ],
)
def test_fake_authoritative_read_missing_and_malformed_identity_fail_closed(
    malformed_identity,
):
    authority = _AtomicProposalAuthority()
    missing = DatasetVersionIdentity("missing", "missing", "1.0.0")
    with pytest.raises(DatasetProposalAuthorityError) as not_found:
        authority.read_authoritative_proposal(missing)
    assert not_found.value.code == "DATASET_PROPOSAL_AUTHORITY_NOT_FOUND"
    assert authority._records == {}

    with pytest.raises(DatasetProposalAuthorityError) as raised:
        authority.read_authoritative_proposal(
            malformed_identity  # type: ignore[arg-type]
        )
    assert raised.value.code == "DATASET_PROPOSAL_AUTHORITY_IDENTITY_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposal_fingerprint", "sha256:" + "0" * 64),
        ("object_id", "dataset_version_other"),
        ("canonical_payload", b"{}\n"),
        ("authority_version", 2),
    ],
)
def test_stored_authoritative_record_corruption_fails_closed_without_repair(
    field,
    value,
):
    proposal = propose_dataset_version(_payload())
    row = {
        "object_id": proposal.identity.object_id,
        "dataset_id": proposal.identity.dataset_id,
        "dataset_version": proposal.identity.dataset_version,
        "proposal_fingerprint": dataset_version_proposal_fingerprint(proposal),
        "canonical_payload": canonical_json_bytes(proposal.payload),
        "authority_reference": "dataset-proposal:" + "1" * 64,
        "authority_version": 1,
        "created_at": PROPOSED_AT,
    }
    row[field] = value
    corrupted = deepcopy(row)

    with pytest.raises(DatasetProposalAuthorityError) as raised:
        postgres_authority_module._authority_record(row)

    assert raised.value.code == "DATASET_PROPOSAL_AUTHORITY_CORRUPT"
    assert row == corrupted


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["producer"].update(name="other-governance"),
        lambda value: value.update(content_fingerprint="sha256:" + "9" * 64),
        lambda value: value.update(dataset_manifest_id="dataset_manifest_product_2"),
        lambda value: value.update(workspace_id="workspace_other"),
        lambda value: value["split_manifest"]["group_keys"].update(
            candidate_train="group_train_other"
        ),
        lambda value: value.update(created_at="2026-08-20T01:00:00Z"),
    ],
)
def test_same_identity_with_different_canonical_proposal_conflicts(mutate):
    authority = _AtomicProposalAuthority()
    _adjudicate(authority=authority)
    conflicting = _payload()
    mutate(conflicting)
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
    ):
        _adjudicate(conflicting, authority=authority)


def test_mapping_order_and_adjudication_time_do_not_change_replay():
    authority = _AtomicProposalAuthority()
    payload = _payload()
    first = _adjudicate(payload, authority=authority)
    reordered = dict(reversed(tuple(payload.items())))
    second = _adjudicate(
        reordered,
        authority=authority,
        proposed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert first.proposal_fingerprint == second.proposal_fingerprint
    assert second.outcome is DatasetProposalOutcome.REPLAYED


def test_authority_and_evidence_authority_are_mandatory_without_fallback():
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_AUTHORITY_MISSING",
    ):
        _adjudicate(authority=object())
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_AUTHORITY_MISSING",
    ):
        _adjudicate(evidence=object())
    signature = inspect.signature(adjudicate_dataset_version_proposal)
    assert signature.parameters["authority"].default is inspect.Parameter.empty
    assert (
        signature.parameters["current_evidence_authority"].default
        is inspect.Parameter.empty
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (DatasetProposalEvidenceStatus.MISSING, "PROPOSAL_EVIDENCE_MISSING"),
        (DatasetProposalEvidenceStatus.EXPIRED, "PROPOSAL_EVIDENCE_EXPIRED"),
        (DatasetProposalEvidenceStatus.REVOKED, "PROPOSAL_EVIDENCE_REVOKED"),
        (DatasetProposalEvidenceStatus.INVALID, "PROPOSAL_EVIDENCE_INVALID"),
    ],
)
def test_non_current_rights_or_eligibility_fails_before_authority(status, code):
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority(status)
    with pytest.raises(DatasetProposalAuthorityError, match=code):
        _adjudicate(authority=authority, evidence=evidence)
    assert authority.calls == 0


def test_current_evidence_identity_mismatch_fails_closed():
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_IDENTITY_MISMATCH",
    ):
        _adjudicate(evidence=_CurrentEvidenceAuthority(identity_mismatch=True))


def test_naive_proposed_at_is_rejected_before_evidence_or_authority():
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority()
    with pytest.raises(DatasetProposalAuthorityError, match="PROPOSED_AT_INVALID"):
        _adjudicate(
            authority=authority,
            evidence=evidence,
            proposed_at=datetime(2026, 8, 21),
        )
    assert evidence.calls == []
    assert authority.calls == 0


def test_current_evidence_is_rechecked_before_replay():
    authority = _AtomicProposalAuthority()
    _adjudicate(authority=authority)
    revoked = _CurrentEvidenceAuthority(DatasetProposalEvidenceStatus.REVOKED)
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_REVOKED",
    ):
        _adjudicate(authority=authority, evidence=revoked)
    assert authority.calls == 1


def test_atomic_fake_first_wins_same_replays_and_conflicting_loser_fails():
    authority = _AtomicProposalAuthority()
    winner = _adjudicate(authority=authority)
    retry = _adjudicate(authority=authority)
    conflicting = _payload(producer={"name": "loser", "version": "1.0.0"})
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
    ):
        _adjudicate(conflicting, authority=authority)
    assert winner.outcome is DatasetProposalOutcome.CREATED
    assert retry.outcome is DatasetProposalOutcome.REPLAYED
    assert len(authority._records) == 1


def test_concurrent_identical_proposals_have_one_creator_and_existing_replays():
    authority = _AtomicProposalAuthority()
    barrier = Barrier(4)

    def submit():
        barrier.wait()
        return _adjudicate(authority=authority)

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: submit(), range(4)))

    assert [result.outcome for result in results].count(
        DatasetProposalOutcome.CREATED
    ) == 1
    assert [result.outcome for result in results].count(
        DatasetProposalOutcome.REPLAYED
    ) == 3
    assert len({id(result.proposal) for result in results}) == 1
    assert len(authority._records) == 1


def test_concurrent_different_proposals_have_one_creator_and_one_conflict():
    authority = _AtomicProposalAuthority()
    barrier = Barrier(2)
    payloads = [
        _payload(),
        _payload(producer={"name": "competing-governance", "version": "1.0.0"}),
    ]

    def submit(payload):
        barrier.wait()
        try:
            return _adjudicate(payload, authority=authority)
        except DatasetProposalAuthorityError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, payloads))

    assert (
        sum(
            isinstance(result, DatasetProposalAuthorityResult)
            and result.outcome is DatasetProposalOutcome.CREATED
            for result in results
        )
        == 1
    )
    conflicts = [
        result
        for result in results
        if isinstance(result, DatasetProposalAuthorityError)
    ]
    assert len(conflicts) == 1
    assert conflicts[0].code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
    assert len(authority._records) == 1


def test_input_mapping_is_not_mutated_and_result_is_snapshot():
    payload = _payload()
    original = deepcopy(payload)
    result = _adjudicate(payload)
    payload["lineage"][0]["object_id"] = "candidate_mutated"
    assert original != payload
    assert result.proposal.payload == original


def test_conflict_error_is_sanitized_but_exposes_safe_fingerprints():
    authority = _AtomicProposalAuthority()
    _adjudicate(authority=authority)
    conflicting = _payload(
        producer={"name": "C:\\private\\token-secret", "version": "1.0.0"}
    )
    with pytest.raises(DatasetProposalAuthorityError) as raised:
        _adjudicate(conflicting, authority=authority)
    assert raised.value.code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
    assert raised.value.existing_fingerprint.startswith("sha256:")
    assert raised.value.incoming_fingerprint.startswith("sha256:")
    assert "private" not in str(raised.value)
    assert "token" not in str(raised.value)


def test_authority_result_is_revalidated():
    class InvalidAuthority:
        def compare_and_create(self, proposal, *, proposal_fingerprint):
            return DatasetProposalAuthorityResult(
                outcome=DatasetProposalOutcome.CREATED,
                proposal=proposal,
                identity=proposal.identity,
                proposal_fingerprint="sha256:" + "0" * 64,
                authority_reference="authority:invalid",
                authority_version=1,
            )

    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_AUTHORITY_RESULT_INVALID",
    ):
        _adjudicate(authority=InvalidAuthority())


def test_no_review_approval_publication_training_or_persistence_calls():
    tree = ast.parse(inspect.getsource(authority_module))
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
    source = inspect.getsource(authority_module)
    assert "sqlite" not in source.lower()
    assert "postgres" not in source.lower()
    assert "CREATE TABLE" not in source
