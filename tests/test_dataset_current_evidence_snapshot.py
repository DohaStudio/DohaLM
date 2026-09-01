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
    RightsReadModel,
    SourceToken,
    source_token_fingerprint,
)
from src.data.dataset_governance import DatasetVersionIdentity
from src.data.postgres_current_evidence import PostgresCurrentRightsAuthority
from src.data.product_dataset_current_evidence import (
    BoundDatasetLifecycleCurrentEvidence,
    DatasetLifecycleStage,
    InMemoryCurrentEvidenceBindingAuthority,
)
from src.training.current_evidence_gate import SnapshotTrainingCurrentEvidenceGate
from src.training.errors import TrainingError

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


def test_training_gate_rechecks_rights_and_stops_stale_activation() -> None:
    dataset, rights = _Dataset(), _Rights()
    coordinator = _coordinator(dataset, rights)
    snapshot = coordinator.capture(
        idempotency_key="proposal:training",
        proposal_fingerprint=FP_PROPOSAL,
        dataset_subject_id="AIHUB-71748",
        rights_subject_id=RIGHTS_SUBJECT,
        captured_at=NOW,
    )

    class Bindings:
        def resolve_snapshot_binding(self, authority_id: str, fingerprint: str):
            assert authority_id == "66666666-6666-4666-8666-666666666666"
            assert fingerprint == "sha256:" + "6" * 64
            return snapshot.snapshot_id, snapshot.snapshot_fingerprint

    gate = SnapshotTrainingCurrentEvidenceGate(Bindings(), coordinator)
    gate.verify_currentness(
        "66666666-6666-4666-8666-666666666666", "sha256:" + "6" * 64
    )
    rights.current = False
    with pytest.raises(TrainingError, match="TRAINING_CURRENT_EVIDENCE_STALE"):
        gate.verify_currentness(
            "66666666-6666-4666-8666-666666666666", "sha256:" + "6" * 64
        )


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
        "subject": {"rights_subject_id": RIGHTS_SUBJECT},
        "permissions": {
            "internal_training": True,
            "commercial_use": False,
            "redistribution": False,
            "external_model_publication": False,
        },
    }
    cursor = _Cursor([(payload, RIGHTS_RECORD, FP_RIGHTS, 1, "sha256:" + "7" * 64)])
    adapter = PostgresCurrentRightsAuthority(
        _Factory(cursor), source_authority_id=RIGHTS_SOURCE
    )
    read = adapter.get_current_rights(RIGHTS_SUBJECT)
    assert read.internal_training is True
    assert "get_current_rights" in cursor.query
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
