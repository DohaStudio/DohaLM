"""ADR-034 Model C Rights and Dataset CurrentEvidence composition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from .checksums import checksum_value
from .dataset_governance import DatasetVersionProposal
from .dataset_proposal_authority import (
    DatasetProposalEvidenceDecision,
    DatasetProposalEvidenceStatus,
)

_FP = re.compile(r"sha256:[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z][A-Za-z0-9._:@-]{1,255}")
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{1,255}")


class CurrentEvidenceError(RuntimeError):
    """Sanitized fail-closed CurrentEvidence boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}:current_evidence")


@dataclass(frozen=True, slots=True)
class SourceToken:
    source_authority_id: str
    schema_version: str
    subject_id: str
    evidence_id: str
    evidence_fingerprint: str
    projection_revision: int
    token_fingerprint: str

    def __post_init__(self) -> None:
        if not _valid_token(self):
            raise CurrentEvidenceError("CURRENT_EVIDENCE_TOKEN_INVALID")


@dataclass(frozen=True, slots=True)
class RightsReadModel:
    subject_id: str
    record_id: str
    source_authority_id: str
    schema_version: str
    internal_training: bool
    commercial_use: bool
    redistribution: bool
    model_publication: bool
    record_fingerprint: str
    token: SourceToken

    def __post_init__(self) -> None:
        if (
            not _valid_uuid(self.record_id)
            or self.subject_id != self.token.subject_id
            or self.record_id != self.token.evidence_id
            or self.source_authority_id != self.token.source_authority_id
            or self.schema_version != self.token.schema_version
            or self.record_fingerprint != self.token.evidence_fingerprint
        ):
            raise CurrentEvidenceError("RIGHTS_READ_MODEL_INVALID")


@dataclass(frozen=True, slots=True)
class DatasetEvidence:
    subject_id: str
    evidence_id: str
    evidence_fingerprint: str
    source_authority_id: str
    schema_version: str
    training_allowed: bool
    token: SourceToken

    def __post_init__(self) -> None:
        if (
            self.subject_id != self.token.subject_id
            or self.evidence_id != self.token.evidence_id
            or self.evidence_fingerprint != self.token.evidence_fingerprint
            or self.source_authority_id != self.token.source_authority_id
            or self.schema_version != self.token.schema_version
        ):
            raise CurrentEvidenceError("DATASET_EVIDENCE_INVALID")


class CurrentRightsAuthority(Protocol):
    def get_current_rights(self, subject_id: str) -> RightsReadModel: ...
    def verify_currentness(self, token: SourceToken) -> bool: ...


class CurrentDatasetEvidenceAuthority(Protocol):
    def get_current_evidence(self, subject_id: str) -> DatasetEvidence: ...
    def verify_currentness(self, token: SourceToken) -> bool: ...


@dataclass(frozen=True, slots=True)
class DatasetGovernanceSnapshot:
    snapshot_id: str
    schema_version: int
    proposal_fingerprint: str
    dataset_subject_id: str
    dataset_evidence: DatasetEvidence
    rights_subject_id: str
    rights: RightsReadModel
    captured_at: datetime
    coordinator_authority_id: str
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not _valid_uuid(self.snapshot_id)
            or self.schema_version != 1
            or not _valid_uuid(self.coordinator_authority_id)
            or _FP.fullmatch(self.proposal_fingerprint) is None
            or self.dataset_subject_id != self.dataset_evidence.subject_id
            or self.rights_subject_id != self.rights.subject_id
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
            or self.snapshot_fingerprint != snapshot_fingerprint(self)
        ):
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_INVALID")


class SnapshotAuthority(Protocol):
    def get_by_idempotency(
        self, idempotency_key: str
    ) -> DatasetGovernanceSnapshot | None: ...

    def put_if_absent(
        self, idempotency_key: str, snapshot: DatasetGovernanceSnapshot
    ) -> DatasetGovernanceSnapshot: ...

    def get(self, snapshot_id: str) -> DatasetGovernanceSnapshot: ...


def source_token_fingerprint(token: SourceToken) -> str:
    return _hash(
        {
            "evidence_fingerprint": token.evidence_fingerprint,
            "evidence_id": token.evidence_id,
            "projection_revision": token.projection_revision,
            "schema_version": token.schema_version,
            "source_authority_id": token.source_authority_id,
            "subject_id": token.subject_id,
        }
    )


def snapshot_fingerprint(snapshot: DatasetGovernanceSnapshot) -> str:
    return _hash(
        {
            "captured_at": snapshot.captured_at.isoformat(),
            "coordinator_authority_id": snapshot.coordinator_authority_id,
            "dataset_evidence_fingerprint": snapshot.dataset_evidence.evidence_fingerprint,
            "dataset_evidence_id": snapshot.dataset_evidence.evidence_id,
            "dataset_source_authority_id": snapshot.dataset_evidence.source_authority_id,
            "dataset_source_token": snapshot.dataset_evidence.token.token_fingerprint,
            "dataset_subject_id": snapshot.dataset_subject_id,
            "proposal_fingerprint": snapshot.proposal_fingerprint,
            "rights_record_fingerprint": snapshot.rights.record_fingerprint,
            "rights_record_id": snapshot.rights.record_id,
            "rights_source_authority_id": snapshot.rights.source_authority_id,
            "rights_source_token": snapshot.rights.token.token_fingerprint,
            "rights_subject_id": snapshot.rights_subject_id,
            "schema_version": snapshot.schema_version,
            "snapshot_id": snapshot.snapshot_id,
        }
    )


class DatasetGovernanceSnapshotCoordinator:
    """Resolve owner-issued tokens, persist an immutable snapshot, and recheck it."""

    def __init__(
        self,
        *,
        coordinator_authority_id: str,
        dataset: CurrentDatasetEvidenceAuthority,
        rights: CurrentRightsAuthority,
        snapshots: SnapshotAuthority,
    ) -> None:
        if not _valid_uuid(coordinator_authority_id):
            raise CurrentEvidenceError("SNAPSHOT_COORDINATOR_INVALID")
        self._authority_id = coordinator_authority_id
        self._dataset = dataset
        self._rights = rights
        self._snapshots = snapshots

    def capture(
        self,
        *,
        idempotency_key: str,
        proposal_fingerprint: str,
        dataset_subject_id: str,
        rights_subject_id: str,
        captured_at: datetime,
    ) -> DatasetGovernanceSnapshot:
        if (
            _REF.fullmatch(idempotency_key) is None
            or _FP.fullmatch(proposal_fingerprint) is None
            or _IDENT.fullmatch(dataset_subject_id) is None
            or _IDENT.fullmatch(rights_subject_id) is None
            or captured_at.tzinfo is None
        ):
            raise CurrentEvidenceError("SNAPSHOT_REQUEST_INVALID")
        existing = self._snapshots.get_by_idempotency(idempotency_key)
        if existing is not None:
            if existing.proposal_fingerprint != proposal_fingerprint:
                raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_CONFLICT")
            self.verify(existing.snapshot_id, existing.snapshot_fingerprint)
            return existing
        dataset = self._dataset.get_current_evidence(dataset_subject_id)
        rights = self._rights.get_current_rights(rights_subject_id)
        if not dataset.training_allowed or not rights.internal_training:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_TRAINING_NOT_ALLOWED")
        snapshot_id = str(uuid5(UUID(self._authority_id), idempotency_key))
        provisional = object.__new__(DatasetGovernanceSnapshot)
        values = {
            "snapshot_id": snapshot_id,
            "schema_version": 1,
            "proposal_fingerprint": proposal_fingerprint,
            "dataset_subject_id": dataset_subject_id,
            "dataset_evidence": dataset,
            "rights_subject_id": rights_subject_id,
            "rights": rights,
            "captured_at": captured_at,
            "coordinator_authority_id": self._authority_id,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "snapshot_fingerprint", "")
        fingerprint = snapshot_fingerprint(provisional)
        snapshot = DatasetGovernanceSnapshot(**values, snapshot_fingerprint=fingerprint)
        persisted = self._snapshots.put_if_absent(idempotency_key, snapshot)
        self.verify(persisted.snapshot_id, persisted.snapshot_fingerprint)
        return persisted

    def verify(self, snapshot_id: str, snapshot_fingerprint_value: str) -> None:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot.snapshot_fingerprint != snapshot_fingerprint_value:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_MISMATCH")
        try:
            current = self._dataset.verify_currentness(snapshot.dataset_evidence.token)
            current = current and self._rights.verify_currentness(snapshot.rights.token)
        except Exception as exc:
            if isinstance(exc, CurrentEvidenceError):
                raise
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SOURCE_UNAVAILABLE") from None
        if not current:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_STALE")

    def get_by_idempotency(
        self, idempotency_key: str
    ) -> DatasetGovernanceSnapshot | None:
        return self._snapshots.get_by_idempotency(idempotency_key)


class SnapshotBoundProposalEvidenceAuthority:
    """Adapt Model C snapshots to the existing Dataset proposal evidence port."""

    def __init__(
        self,
        coordinator: DatasetGovernanceSnapshotCoordinator,
        *,
        dataset_subject_id: str,
        rights_subject_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._dataset_subject_id = dataset_subject_id
        self._rights_subject_id = rights_subject_id

    def evaluate_current_proposal_evidence(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
        proposed_at: datetime,
    ) -> DatasetProposalEvidenceDecision:
        try:
            snapshot = self._coordinator.capture(
                idempotency_key=f"proposal:{proposal_fingerprint[7:]}",
                proposal_fingerprint=proposal_fingerprint,
                dataset_subject_id=self._dataset_subject_id,
                rights_subject_id=self._rights_subject_id,
                captured_at=proposed_at,
            )
        except CurrentEvidenceError as exc:
            status = (
                DatasetProposalEvidenceStatus.REVOKED
                if exc.code
                in {
                    "CURRENT_EVIDENCE_SNAPSHOT_STALE",
                    "CURRENT_EVIDENCE_TRAINING_NOT_ALLOWED",
                }
                else DatasetProposalEvidenceStatus.INVALID
            )
            return DatasetProposalEvidenceDecision(
                status,
                proposal.identity,
                proposal_fingerprint,
                "current-evidence:invalid",
                1,
            )
        return DatasetProposalEvidenceDecision(
            DatasetProposalEvidenceStatus.CURRENT,
            proposal.identity,
            proposal_fingerprint,
            f"current-evidence:{snapshot.snapshot_id}",
            snapshot.schema_version,
        )


class InMemorySnapshotAuthority:
    """Deterministic test double; production composition must use PostgreSQL."""

    def __init__(self) -> None:
        self._by_id: dict[str, DatasetGovernanceSnapshot] = {}
        self._by_key: dict[str, DatasetGovernanceSnapshot] = {}

    def get_by_idempotency(
        self, idempotency_key: str
    ) -> DatasetGovernanceSnapshot | None:
        return self._by_key.get(idempotency_key)

    def put_if_absent(
        self, idempotency_key: str, snapshot: DatasetGovernanceSnapshot
    ) -> DatasetGovernanceSnapshot:
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            if existing != snapshot:
                raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_CONFLICT")
            return existing
        self._by_key[idempotency_key] = snapshot
        self._by_id[snapshot.snapshot_id] = snapshot
        return snapshot

    def get(self, snapshot_id: str) -> DatasetGovernanceSnapshot:
        try:
            return self._by_id[snapshot_id]
        except KeyError:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_MISSING") from None


def _valid_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def _valid_token(token: SourceToken) -> bool:
    return (
        _valid_uuid(token.source_authority_id)
        and _REF.fullmatch(token.schema_version) is not None
        and _IDENT.fullmatch(token.subject_id) is not None
        and _IDENT.fullmatch(token.evidence_id) is not None
        and _FP.fullmatch(token.evidence_fingerprint) is not None
        and token.projection_revision >= 1
        and _FP.fullmatch(token.token_fingerprint) is not None
    )


def _hash(value: dict[str, object]) -> str:
    return checksum_value(value)


__all__ = [
    "CurrentDatasetEvidenceAuthority",
    "CurrentEvidenceError",
    "CurrentRightsAuthority",
    "DatasetEvidence",
    "DatasetGovernanceSnapshot",
    "DatasetGovernanceSnapshotCoordinator",
    "InMemorySnapshotAuthority",
    "RightsReadModel",
    "SnapshotAuthority",
    "SnapshotBoundProposalEvidenceAuthority",
    "SourceToken",
    "snapshot_fingerprint",
    "source_token_fingerprint",
]
