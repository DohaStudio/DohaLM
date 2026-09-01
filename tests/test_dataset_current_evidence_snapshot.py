from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.data.current_evidence_snapshot import (
    CurrentEvidenceError,
    DatasetEvidence,
    DatasetGovernanceSnapshotCoordinator,
    InMemorySnapshotAuthority,
    ProposalDatasetEvidenceTokenAuthority,
    RightsReadModel,
    SourceToken,
    source_token_fingerprint,
)
from src.data.dataset_governance import DatasetVersionIdentity
from src.data.dataset_governance import propose_dataset_version
from src.data.dataset_proposal_authority import (
    DatasetProposalEvidenceDecision,
    DatasetProposalEvidenceStatus,
    dataset_version_proposal_fingerprint,
)
from src.data.postgres_current_evidence import PostgresCurrentRightsAuthority
from src.data.product_dataset_current_evidence import (
    BoundDatasetLifecycleCurrentEvidence,
    DatasetLifecycleStage,
    InMemoryCurrentEvidenceBindingAuthority,
)
from test_dataset_proposal_authority import _payload

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
DATASET_SOURCE = "11111111-1111-4111-8111-111111111111"
RIGHTS_SOURCE = "22222222-2222-4222-8222-222222222222"
COORDINATOR = "33333333-3333-4333-8333-333333333333"
RIGHTS_SUBJECT = "44444444-4444-4444-8444-444444444444"
RIGHTS_RECORD = "55555555-5555-4555-8555-555555555555"
FP_DATASET = "sha256:" + "1" * 64
FP_RIGHTS = "sha256:" + "2" * 64
FP_PROPOSAL = "sha256:" + "3" * 64


def _token(
    source: str, schema: str, subject: str, evidence: str, fingerprint: str
) -> SourceToken:
    provisional = SourceToken(
        source,
        schema,
        subject,
        evidence,
        fingerprint,
        1,
        "sha256:" + "0" * 64,
    )
    return replace(provisional, token_fingerprint=source_token_fingerprint(provisional))


class _Dataset:
    def __init__(self) -> None:
        self.current = True
        self.token = _token(
            DATASET_SOURCE,
            "dataset-evidence-token-v1",
            "AIHUB-71748",
            "candidate-a-eligibility-v1",
            FP_DATASET,
        )

    def get_current_evidence(self, subject_id: str) -> DatasetEvidence:
        assert subject_id == "AIHUB-71748"
        return DatasetEvidence(
            subject_id,
            self.token.evidence_id,
            FP_DATASET,
            DATASET_SOURCE,
            self.token.schema_version,
            True,
            self.token,
        )

    def verify_currentness(self, token: SourceToken) -> bool:
        return self.current and token == self.token


class _Rights:
    def __init__(self) -> None:
        self.current = True
        self.unavailable = False
        self.token = _token(
            RIGHTS_SOURCE,
            "rights-source-token-v1",
            RIGHTS_SUBJECT,
            RIGHTS_RECORD,
            FP_RIGHTS,
        )

    def get_current_rights(self, subject_id: str) -> RightsReadModel:
        assert subject_id == RIGHTS_SUBJECT
        return RightsReadModel(
            subject_id,
            RIGHTS_RECORD,
            RIGHTS_SOURCE,
            self.token.schema_version,
            True,
            False,
            False,
            False,
            FP_RIGHTS,
            self.token,
        )

    def verify_currentness(self, token: SourceToken) -> bool:
        if self.unavailable:
            raise OSError("synthetic source failure")
        return self.current and token == self.token


def _coordinator(dataset: _Dataset, rights: _Rights):
    return DatasetGovernanceSnapshotCoordinator(
        coordinator_authority_id=COORDINATOR,
        dataset=dataset,
        rights=rights,
        snapshots=InMemorySnapshotAuthority(),
    )


def test_candidate_a_model_c_snapshot_is_idempotent_and_non_commercial() -> None:
    dataset, rights = _Dataset(), _Rights()
    coordinator = _coordinator(dataset, rights)
    first = coordinator.capture(
        idempotency_key="proposal:request-1",
        proposal_fingerprint=FP_PROPOSAL,
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
        captured_at=NOW,
    )
    replay = coordinator.capture(
        idempotency_key="proposal:request-1",
        proposal_fingerprint=FP_PROPOSAL,
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
        captured_at=NOW,
    )
    assert replay == first
    assert UUID(first.snapshot_id)
    assert first.snapshot_fingerprint.startswith("sha256:")
    assert first.rights.internal_training is True
    assert first.rights.commercial_use is False
    assert first.rights.redistribution is False
    assert first.rights.model_publication is False


def test_dataset_source_adapter_issues_and_revalidates_owner_token() -> None:
    proposal = propose_dataset_version(_payload())

    class Authority:
        status = DatasetProposalEvidenceStatus.CURRENT
        version = 7
        unavailable = False

        def evaluate_current_proposal_evidence(
            self, actual, *, proposal_fingerprint: str, proposed_at: datetime
        ):
            if self.unavailable:
                raise OSError("synthetic source failure")
            assert actual is proposal and proposed_at == NOW
            return DatasetProposalEvidenceDecision(
                self.status,
                proposal.identity,
                proposal_fingerprint,
                "authority:dataset-evidence:7",
                self.version,
            )

    source = Authority()
    adapter = ProposalDatasetEvidenceTokenAuthority(
        source_authority_id=DATASET_SOURCE,
        subject_id="AIHUB-71748",
        proposal=proposal,
        authority=source,
        clock=lambda: NOW,
    )
    evidence = adapter.get_current_evidence("AIHUB-71748")
    with pytest.raises(CurrentEvidenceError, match="DATASET_EVIDENCE_SUBJECT_MISMATCH"):
        adapter.get_current_evidence("AIHUB-71748-other")
    assert evidence.evidence_fingerprint == dataset_version_proposal_fingerprint(
        proposal
    )
    assert evidence.token.projection_revision == 7
    assert adapter.verify_currentness(evidence.token) is True
    assert (
        adapter.verify_currentness(
            replace(evidence.token, token_fingerprint="sha256:" + "f" * 64)
        )
        is False
    )
    source.version = 8
    assert adapter.verify_currentness(evidence.token) is False
    source.status = DatasetProposalEvidenceStatus.REVOKED
    with pytest.raises(CurrentEvidenceError, match="DATASET_EVIDENCE_NOT_CURRENT"):
        adapter.get_current_evidence("AIHUB-71748")
    source.status, source.unavailable = DatasetProposalEvidenceStatus.CURRENT, True
    with pytest.raises(
        CurrentEvidenceError, match="DATASET_EVIDENCE_SOURCE_UNAVAILABLE"
    ):
        adapter.get_current_evidence("AIHUB-71748")


def test_rights_revoke_dataset_change_and_source_failure_fail_closed() -> None:
    dataset, rights = _Dataset(), _Rights()
    coordinator = _coordinator(dataset, rights)
    snapshot = coordinator.capture(
        idempotency_key="proposal:request-2",
        proposal_fingerprint=FP_PROPOSAL,
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
        captured_at=NOW,
    )
    with pytest.raises(
        CurrentEvidenceError, match="CURRENT_EVIDENCE_SNAPSHOT_MISMATCH"
    ):
        coordinator.verify(snapshot.snapshot_id, "sha256:" + "f" * 64)
    rights.current = False
    with pytest.raises(CurrentEvidenceError, match="CURRENT_EVIDENCE_SNAPSHOT_STALE"):
        coordinator.verify(snapshot.snapshot_id, snapshot.snapshot_fingerprint)
    rights.current, dataset.current = True, False
    with pytest.raises(CurrentEvidenceError, match="CURRENT_EVIDENCE_SNAPSHOT_STALE"):
        coordinator.verify(snapshot.snapshot_id, snapshot.snapshot_fingerprint)
    dataset.current, rights.unavailable = True, True
    with pytest.raises(
        CurrentEvidenceError, match="CURRENT_EVIDENCE_SOURCE_UNAVAILABLE"
    ):
        coordinator.verify(snapshot.snapshot_id, snapshot.snapshot_fingerprint)


def test_review_approval_publication_bind_exact_snapshot_and_recheck() -> None:
    dataset, rights = _Dataset(), _Rights()
    coordinator = _coordinator(dataset, rights)
    snapshot = coordinator.capture(
        idempotency_key=f"proposal:{FP_PROPOSAL[7:]}",
        proposal_fingerprint=FP_PROPOSAL,
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
        captured_at=NOW,
    )
    lifecycle = BoundDatasetLifecycleCurrentEvidence(
        coordinator=coordinator,
        bindings=InMemoryCurrentEvidenceBindingAuthority(),
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
    )
    identity = DatasetVersionIdentity("object-1", "AIHUB-71748", "pilot-v2")
    bindings = [
        lifecycle.freeze_stage(
            identity=identity, proposal_fingerprint=FP_PROPOSAL, stage=stage
        )
        for stage in DatasetLifecycleStage
    ]
    assert {item.snapshot_id for item in bindings} == {snapshot.snapshot_id}
    assert {item.snapshot_fingerprint for item in bindings} == {
        snapshot.snapshot_fingerprint
    }
    rights.current = False
    with pytest.raises(CurrentEvidenceError, match="CURRENT_EVIDENCE_SNAPSHOT_STALE"):
        lifecycle.require_current_publication(identity)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, query, parameters):
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor):
        self.value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def cursor(self):
        return self.value


class _Factory:
    role = "doharights_reader"

    def __init__(self, cursor):
        self.cursor = cursor

    def connection(self):
        return _Connection(self.cursor)


def test_postgres_rights_reader_uses_only_owner_functions_and_rejects_wrong_role() -> (
    None
):
    payload = {
        "source_authority": {
            "source_authority_id": RIGHTS_SOURCE,
            "schema_version": "rights-authority-v1",
        },
        "subject": {
            "rights_subject_id": RIGHTS_SUBJECT,
            "dataset_source_identity": "AIHUB-71748",
            "kind": "source_dataset",
            "bound_identity": "AIHUB-71748",
        },
        "permissions": {
            "internal_training": True,
            "commercial_use": False,
            "redistribution": False,
            "external_model_publication": False,
            "analysis": True,
            "derivative_generation": True,
        },
        "status": "approved_limited",
        "source_classification": {
            "source_type": "external",
            "user_created": False,
            "generated": False,
            "reference": False,
            "uploaded": False,
            "external": True,
        },
        "retention": {
            "allowed": True,
            "mode": "indefinite_while_current",
            "scope": "training",
            "expires_at": None,
        },
        "consent_evidence_references": [],
        "jurisdiction": "KR",
        "review": {
            "reviewer_authority_id": COORDINATOR,
            "reviewed_at": NOW.isoformat(),
        },
        "producer_authority_id": DATASET_SOURCE,
        "effective_at": NOW.isoformat(),
        "current_use_authorization": {
            "authorized": True,
            "scope": "internal_noncommercial_model_training_and_evaluation",
            "fresh_acquisition_required": False,
            "existing_material_reuse": True,
            "historical_acquisition_receipt": "not_recovered",
            "provider_reacquisition_requirement_found": False,
        },
        "evidence_references": [
            {
                "reference_id": "evidence:aihub-current-policy",
                "evidence_type": "provider_usage_policy",
            }
        ],
    }
    cursor = _Cursor([(payload, RIGHTS_RECORD, FP_RIGHTS, 1, "sha256:" + "7" * 64)])
    adapter = PostgresCurrentRightsAuthority(
        _Factory(cursor), source_authority_id=RIGHTS_SOURCE
    )
    read = adapter.get_current_rights(RIGHTS_SUBJECT)
    assert read.internal_training is True
    assert read.metadata is not None
    assert read.metadata.retention_mode == "indefinite_while_current"
    assert "get_current_use_rights" in cursor.query
    assert all(
        word not in cursor.query.upper() for word in ("INSERT", "UPDATE", "DELETE")
    )
    multiple = PostgresCurrentRightsAuthority(
        _Factory(_Cursor([cursor.rows[0], cursor.rows[0]])),
        source_authority_id=RIGHTS_SOURCE,
    )
    with pytest.raises(CurrentEvidenceError, match="RIGHTS_MULTIPLE_CURRENT"):
        multiple.get_current_rights(RIGHTS_SUBJECT)
    with pytest.raises(CurrentEvidenceError, match="RIGHTS_SOURCE_AUTHORITY_MISMATCH"):
        adapter.verify_currentness(
            replace(read.token, source_authority_id=DATASET_SOURCE)
        )

    class Wrong(_Factory):
        role = "doharights_producer"

    with pytest.raises(
        CurrentEvidenceError, match="RIGHTS_READER_CONFIGURATION_INVALID"
    ):
        PostgresCurrentRightsAuthority(Wrong(cursor), source_authority_id=RIGHTS_SOURCE)
