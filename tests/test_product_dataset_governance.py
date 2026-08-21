from __future__ import annotations

import ast
import inspect
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest
from test_product_dataset_composition import (
    _Authority,
    _authority_input,
    _compose,
    _handoff,
    _handoffs,
)

import src.data.learning_candidate_dataset_handoff as handoff_module
import src.data.product_dataset_governance as integration_module
from src.data.checksums import checksum_value
from src.data.dataset_governance import DatasetGovernanceError, DatasetVersionIdentity
from src.data.dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalAuthorityRecord,
    DatasetProposalAuthorityResult,
    DatasetProposalEvidenceDecision,
    DatasetProposalEvidenceStatus,
    DatasetProposalOutcome,
    dataset_version_proposal_fingerprint,
)
from src.data.learning_candidate_consumer import ProducerIdentity
from src.data.product_dataset_composition import (
    ProductDatasetCompositionError,
    build_dataset_version_proposal_mapping,
)
from src.data.product_dataset_governance import propose_product_dataset_version

PROPOSED_AT = datetime(2026, 8, 24, tzinfo=timezone.utc)


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
        proposal,
        *,
        proposal_fingerprint: str,
        proposed_at: datetime,
    ) -> DatasetProposalEvidenceDecision:
        self.calls.append((proposal.identity, proposal_fingerprint, proposed_at))
        identity = proposal.identity
        if self.identity_mismatch:
            identity = DatasetVersionIdentity(
                "dataset_version_other",
                "dataset_other",
                "2.0.0",
            )
        return DatasetProposalEvidenceDecision(
            status=self.status,
            identity=identity,
            proposal_fingerprint=proposal_fingerprint,
            authority_reference="authority:product-dataset-evidence:test",
            authority_version=1,
        )


class _AtomicProposalAuthority:
    def __init__(self) -> None:
        self._lock = Lock()
        self.records: dict[object, tuple[object, str]] = {}
        self.calls = 0
        self.writes = 0

    def compare_and_create(
        self,
        proposal,
        *,
        proposal_fingerprint: str,
    ) -> DatasetProposalAuthorityResult:
        with self._lock:
            self.calls += 1
            existing = self.records.get(proposal.identity)
            if existing is None:
                self.records[proposal.identity] = (proposal, proposal_fingerprint)
                stored = self.records[proposal.identity]
                outcome = DatasetProposalOutcome.CREATED
                self.writes += 1
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
                authority_reference="authority:product-dataset-proposal:test",
                authority_version=1,
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
        stored = self.records.get(identity)
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
            authority_reference="authority:product-dataset-proposal:test",
            authority_version=1,
        )


def _propose(
    composition=None,
    *,
    authority=None,
    evidence=None,
    proposed_at: datetime = PROPOSED_AT,
):
    return propose_product_dataset_version(
        composition or _compose(),
        authority=authority or _AtomicProposalAuthority(),
        current_evidence_authority=evidence or _CurrentEvidenceAuthority(),
        proposed_at=proposed_at,
    )


def _rehash_handoff(handoff, **changes):
    changed = replace(handoff, **changes)
    return replace(
        changed,
        handoff_id=f"handoff:{checksum_value(handoff_module._handoff_projection(changed))}",
    )


def _competing_composition(difference: str):
    handoffs = _handoffs()
    authority = None
    changes = {}
    if difference == "producer":
        changes["producer"] = ProducerIdentity("competing-governance", "1.0.0")
    elif difference == "content":
        handoffs = (_handoff("train", "d"), *handoffs[1:])
    elif difference == "source":
        handoffs = (
            _rehash_handoff(
                handoffs[0],
                parent_candidate_ids=("parent_train_other",),
            ),
            *handoffs[1:],
        )
    elif difference == "member":
        handoffs = (_handoff("train_other", "d"), *handoffs[1:])
        authority = _Authority(("train_other", "validation", "test"))
    elif difference == "manifest":
        changes["dataset_manifest_id"] = "dataset_manifest_product_2"
    elif difference == "evidence":
        changes["dataset_eligibility_evidence_id"] = "dataset_gate_product_2"
    elif difference == "workspace":
        handoffs = tuple(
            _handoff(suffix, fingerprint, workspace_id="workspace_other")
            for suffix, fingerprint in (
                ("train", "a"),
                ("validation", "b"),
                ("test", "c"),
            )
        )
        changes["workspace_id"] = "workspace_other"
        authority = _Authority()
        for payload in (*authority.rights.values(), *authority.eligibility.values()):
            payload["workspace_id"] = "workspace_other"
    elif difference == "lineage":
        handoffs = (
            _rehash_handoff(
                handoffs[0],
                review_evidence_reference="review:train:other",
            ),
            *handoffs[1:],
        )
    else:
        raise AssertionError(f"unexpected test difference: {difference}")
    return _compose(
        handoffs,
        authority_input=_authority_input(handoffs, **changes),
        authority=authority,
    )


def test_exact_composition_creates_canonical_draft_through_existing_builder():
    composition = _compose()
    mapping = build_dataset_version_proposal_mapping(composition)
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority()

    result = _propose(composition, authority=authority, evidence=evidence)

    assert result.outcome is DatasetProposalOutcome.CREATED
    assert result.proposal.payload == mapping
    assert result.proposal.status == "draft"
    assert result.proposal.payload["approved"] is False
    assert result.proposal.payload["frozen"] is False
    assert result.proposal.payload["training_allowed"] is False
    assert result.proposal_fingerprint == dataset_version_proposal_fingerprint(
        result.proposal
    )
    assert evidence.calls == [
        (result.identity, result.proposal_fingerprint, PROPOSED_AT)
    ]
    assert authority.calls == authority.writes == 1


def test_same_composition_replays_existing_object_without_duplicate_write():
    authority = _AtomicProposalAuthority()
    first = _propose(authority=authority)
    second = _propose(
        authority=authority,
        proposed_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    assert first.outcome is DatasetProposalOutcome.CREATED
    assert second.outcome is DatasetProposalOutcome.REPLAYED
    assert second.proposal is first.proposal
    assert second.proposal_fingerprint == first.proposal_fingerprint
    assert authority.calls == 2
    assert authority.writes == len(authority.records) == 1


def test_different_composition_with_same_dataset_identity_conflicts_without_overwrite():
    handoffs = _handoffs()
    first_composition = _compose(handoffs)
    competing_composition = _compose(
        handoffs,
        authority_input=_authority_input(
            handoffs,
            producer=ProducerIdentity("competing-governance", "1.0.0"),
        ),
    )
    authority = _AtomicProposalAuthority()
    winner = _propose(first_composition, authority=authority)
    before = dict(authority.records)

    with pytest.raises(
        DatasetProposalAuthorityError,
        match="DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
    ):
        _propose(competing_composition, authority=authority)

    assert winner.outcome is DatasetProposalOutcome.CREATED
    assert authority.records == before
    assert authority.writes == 1


@pytest.mark.parametrize(
    "difference",
    (
        "producer",
        "content",
        "source",
        "member",
        "manifest",
        "evidence",
        "workspace",
        "lineage",
    ),
)
def test_each_valid_authoritative_difference_conflicts_without_mutation(difference):
    first_composition = _compose()
    competing_composition = _competing_composition(difference)
    authority = _AtomicProposalAuthority()
    winner = _propose(first_composition, authority=authority)
    before = dict(authority.records)

    assert competing_composition.object_id == first_composition.object_id
    assert competing_composition.dataset_id == first_composition.dataset_id
    assert competing_composition.dataset_version == first_composition.dataset_version
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
    ):
        _propose(competing_composition, authority=authority)

    assert winner.outcome is DatasetProposalOutcome.CREATED
    assert authority.records == before
    assert authority.writes == 1


def test_different_dataset_identities_are_independent():
    handoffs = _handoffs()
    first = _compose(handoffs)
    second = _compose(
        handoffs,
        authority_input=_authority_input(
            handoffs,
            object_id="dataset_version_product_2",
            dataset_id="dataset_product_2",
            dataset_version="2.0.0",
        ),
    )
    authority = _AtomicProposalAuthority()

    results = [
        _propose(first, authority=authority),
        _propose(second, authority=authority),
    ]

    assert all(result.outcome is DatasetProposalOutcome.CREATED for result in results)
    assert len(authority.records) == authority.writes == 2


def test_canonical_handoff_input_order_replays_same_proposal():
    handoffs = _handoffs()
    authority_input = _authority_input(handoffs)
    first = _compose(handoffs, authority_input=authority_input)
    reordered = _compose(
        tuple(reversed(handoffs)),
        authority_input=authority_input,
    )
    authority = _AtomicProposalAuthority()

    created = _propose(first, authority=authority)
    replayed = _propose(reordered, authority=authority)

    assert first == reordered
    assert replayed.outcome is DatasetProposalOutcome.REPLAYED
    assert replayed.proposal is created.proposal


@pytest.mark.parametrize(
    "change",
    [
        {"content_fingerprint": "sha256:" + "9" * 64},
        {"source_fingerprint": "sha256:" + "8" * 64},
        {"composition_id": "composition:sha256:" + "7" * 64},
        {"workspace_id": "workspace_other"},
        {"dataset_manifest_id": "dataset_manifest_product_2"},
    ],
)
def test_tampered_composition_fails_before_evidence_or_authority(change):
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority()
    tampered = replace(_compose(), **change)

    with pytest.raises(ProductDatasetCompositionError):
        _propose(tampered, authority=authority, evidence=evidence)

    assert evidence.calls == []
    assert authority.calls == authority.writes == 0


def test_only_exact_product_dataset_composition_is_accepted():
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority()
    with pytest.raises(ProductDatasetCompositionError, match="COMPOSITION_INVALID"):
        _propose(
            build_dataset_version_proposal_mapping(_compose()),
            authority=authority,
            evidence=evidence,
        )
    assert evidence.calls == []
    assert authority.calls == 0


def test_invalid_builder_mapping_cannot_mutate_authority(monkeypatch):
    invalid = build_dataset_version_proposal_mapping(_compose())
    invalid["approved"] = True
    monkeypatch.setattr(
        integration_module,
        "build_dataset_version_proposal_mapping",
        lambda composition: invalid,
    )
    authority = _AtomicProposalAuthority()
    evidence = _CurrentEvidenceAuthority()

    with pytest.raises(DatasetGovernanceError):
        _propose(authority=authority, evidence=evidence)

    assert evidence.calls == []
    assert authority.calls == authority.writes == 0


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
        _propose(authority=authority, evidence=evidence)

    assert evidence.calls[0][2] == PROPOSED_AT
    assert authority.calls == authority.writes == 0


def test_replay_does_not_bypass_revoked_current_evidence():
    authority = _AtomicProposalAuthority()
    _propose(authority=authority)

    with pytest.raises(
        DatasetProposalAuthorityError, match="PROPOSAL_EVIDENCE_REVOKED"
    ):
        _propose(
            authority=authority,
            evidence=_CurrentEvidenceAuthority(DatasetProposalEvidenceStatus.REVOKED),
        )

    assert authority.calls == authority.writes == 1


def test_evidence_identity_mismatch_and_naive_proposed_at_fail_closed():
    authority = _AtomicProposalAuthority()
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_IDENTITY_MISMATCH",
    ):
        _propose(
            authority=authority,
            evidence=_CurrentEvidenceAuthority(identity_mismatch=True),
        )
    with pytest.raises(DatasetProposalAuthorityError, match="PROPOSED_AT_INVALID"):
        _propose(
            authority=authority,
            proposed_at=datetime(2026, 8, 24),
        )
    assert authority.calls == authority.writes == 0


def test_authority_dependencies_are_mandatory_without_fallback():
    signature = inspect.signature(propose_product_dataset_version)
    assert signature.parameters["authority"].default is inspect.Parameter.empty
    assert (
        signature.parameters["current_evidence_authority"].default
        is inspect.Parameter.empty
    )
    with pytest.raises(
        DatasetProposalAuthorityError, match="PROPOSAL_AUTHORITY_MISSING"
    ):
        _propose(authority=object())
    with pytest.raises(
        DatasetProposalAuthorityError,
        match="PROPOSAL_EVIDENCE_AUTHORITY_MISSING",
    ):
        _propose(evidence=object())


def test_composition_authority_fields_and_lineage_are_preserved_exactly():
    composition = _compose()
    before = deepcopy(composition)
    mapping = build_dataset_version_proposal_mapping(composition)
    result = _propose(composition)
    payload = result.proposal.payload

    assert payload == mapping
    assert payload["created_from"] == composition.source_fingerprint
    assert payload["content_fingerprint"] == composition.content_fingerprint
    assert payload["workspace_id"] == composition.workspace_id
    assert payload["producer"] == {
        "name": composition.producer.name,
        "version": composition.producer.version,
    }
    assert payload["schema_manifest_id"] == composition.schema_manifest_id
    assert payload["dataset_manifest_id"] == composition.dataset_manifest_id
    assert (
        payload["dataset_eligibility_evidence_id"]
        == composition.dataset_eligibility_evidence_id
    )
    extension = payload["extensions"]["dohalm.product_dataset_composition"]
    assert extension["composition_id"] == composition.composition_id
    canonical_members = sorted(
        composition.members, key=lambda member: member.candidate_id
    )
    assert extension["handoff_ids"] == [
        member.handoff_id for member in canonical_members
    ]
    assert len(extension["member_bindings"]) == len(composition.members)
    assert composition == before


def test_integration_conflict_error_does_not_render_private_input():
    handoffs = _handoffs()
    authority = _AtomicProposalAuthority()
    _propose(_compose(handoffs), authority=authority)
    competing = _compose(
        handoffs,
        authority_input=_authority_input(
            handoffs,
            producer=ProducerIdentity("C:\\private\\token-secret", "1.0.0"),
        ),
    )

    with pytest.raises(DatasetProposalAuthorityError) as raised:
        _propose(competing, authority=authority)

    assert raised.value.code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
    assert "private" not in str(raised.value)
    assert "token" not in str(raised.value)


def test_concurrent_same_composition_has_one_create_and_existing_replays():
    composition = _compose()
    authority = _AtomicProposalAuthority()
    barrier = Barrier(4)

    def submit():
        barrier.wait()
        return _propose(composition, authority=authority)

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: submit(), range(4)))

    assert [result.outcome for result in results].count(
        DatasetProposalOutcome.CREATED
    ) == 1
    assert [result.outcome for result in results].count(
        DatasetProposalOutcome.REPLAYED
    ) == 3
    assert len({id(result.proposal) for result in results}) == 1
    assert authority.writes == len(authority.records) == 1


def test_concurrent_conflicting_compositions_have_one_winner_without_overwrite():
    handoffs = _handoffs()
    compositions = (
        _compose(handoffs),
        _compose(
            handoffs,
            authority_input=_authority_input(
                handoffs,
                producer=ProducerIdentity("competing-governance", "1.0.0"),
            ),
        ),
    )
    authority = _AtomicProposalAuthority()
    barrier = Barrier(2)

    def submit(composition):
        barrier.wait()
        try:
            return _propose(composition, authority=authority)
        except DatasetProposalAuthorityError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, compositions))

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
    assert authority.writes == len(authority.records) == 1


def test_integration_has_no_review_approval_publication_training_or_persistence():
    tree = ast.parse(inspect.getsource(integration_module))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called == {
        "adjudicate_dataset_version_proposal",
        "build_dataset_version_proposal_mapping",
    }
    source = inspect.getsource(integration_module).lower()
    assert not {
        "begin_dataset_review",
        "approve_dataset_version",
        "publish_dataset_version",
        "run_training",
        "evaluate_model",
        "promote_model",
        "sqlite",
        "postgres",
        "redis",
    } & set(source.split())
