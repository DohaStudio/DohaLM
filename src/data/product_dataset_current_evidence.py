"""Exact Model C snapshot binding for Dataset review, approval, and publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .current_evidence_snapshot import (
    CurrentEvidenceError,
    DatasetGovernanceSnapshot,
    DatasetGovernanceSnapshotCoordinator,
    SnapshotBoundProposalEvidenceAuthority,
)
from .dataset_governance import DatasetVersionIdentity, DatasetVersionProposal
from .dataset_proposal_authority import DatasetProposalEvidenceDecision
from datetime import datetime


class DatasetLifecycleStage(str, Enum):
    REVIEW = "review"
    APPROVAL = "approval"
    PUBLICATION = "publication"


@dataclass(frozen=True, slots=True)
class CurrentEvidenceBinding:
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    stage: DatasetLifecycleStage
    snapshot_id: str
    snapshot_fingerprint: str


class CurrentEvidenceBindingAuthority(Protocol):
    def bind(self, binding: CurrentEvidenceBinding) -> CurrentEvidenceBinding: ...
    def read(
        self, identity: DatasetVersionIdentity, stage: DatasetLifecycleStage
    ) -> CurrentEvidenceBinding: ...


class InMemoryCurrentEvidenceBindingAuthority:
    """Append-only deterministic test authority, never production composition."""

    def __init__(self) -> None:
        self._bindings: dict[
            tuple[DatasetVersionIdentity, DatasetLifecycleStage], CurrentEvidenceBinding
        ] = {}

    def bind(self, binding: CurrentEvidenceBinding) -> CurrentEvidenceBinding:
        key = (binding.identity, binding.stage)
        existing = self._bindings.get(key)
        if existing is not None and existing != binding:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_BINDING_CONFLICT")
        self._bindings[key] = binding
        return binding

    def read(
        self, identity: DatasetVersionIdentity, stage: DatasetLifecycleStage
    ) -> CurrentEvidenceBinding:
        try:
            return self._bindings[(identity, stage)]
        except KeyError:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_BINDING_MISSING") from None


class BoundDatasetLifecycleCurrentEvidence:
    """Freeze one snapshot across review, approval, and publication transitions."""

    def __init__(
        self,
        *,
        coordinator: DatasetGovernanceSnapshotCoordinator,
        bindings: CurrentEvidenceBindingAuthority,
        dataset_subject_id: str,
        rights_subject_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._bindings = bindings
        self.proposal_authority = SnapshotBoundProposalEvidenceAuthority(
            coordinator,
            dataset_subject_id=dataset_subject_id,
            rights_subject_id=rights_subject_id,
        )

    def evaluate_current_proposal_evidence(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
        proposed_at: datetime,
    ) -> DatasetProposalEvidenceDecision:
        return self.proposal_authority.evaluate_current_proposal_evidence(
            proposal,
            proposal_fingerprint=proposal_fingerprint,
            proposed_at=proposed_at,
        )

    def freeze_stage(
        self,
        *,
        identity: DatasetVersionIdentity,
        proposal_fingerprint: str,
        stage: DatasetLifecycleStage,
    ) -> CurrentEvidenceBinding:
        snapshot = self._snapshot(proposal_fingerprint)
        if stage is not DatasetLifecycleStage.REVIEW:
            predecessor = (
                DatasetLifecycleStage.REVIEW
                if stage is DatasetLifecycleStage.APPROVAL
                else DatasetLifecycleStage.APPROVAL
            )
            previous = self._bindings.read(identity, predecessor)
            if (
                previous.proposal_fingerprint != proposal_fingerprint
                or previous.snapshot_id != snapshot.snapshot_id
                or previous.snapshot_fingerprint != snapshot.snapshot_fingerprint
            ):
                raise CurrentEvidenceError("CURRENT_EVIDENCE_BINDING_MISMATCH")
        self._coordinator.verify(snapshot.snapshot_id, snapshot.snapshot_fingerprint)
        return self._bindings.bind(
            CurrentEvidenceBinding(
                identity,
                proposal_fingerprint,
                stage,
                snapshot.snapshot_id,
                snapshot.snapshot_fingerprint,
            )
        )

    def require_current_publication(
        self, identity: DatasetVersionIdentity
    ) -> CurrentEvidenceBinding:
        binding = self._bindings.read(identity, DatasetLifecycleStage.PUBLICATION)
        self._coordinator.verify(binding.snapshot_id, binding.snapshot_fingerprint)
        return binding

    def _snapshot(self, proposal_fingerprint: str) -> DatasetGovernanceSnapshot:
        key = f"proposal:{proposal_fingerprint[7:]}"
        snapshot = self._coordinator.get_by_idempotency(key)
        if snapshot is None:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_MISSING")
        return snapshot


__all__ = [
    "BoundDatasetLifecycleCurrentEvidence",
    "CurrentEvidenceBinding",
    "CurrentEvidenceBindingAuthority",
    "DatasetLifecycleStage",
    "InMemoryCurrentEvidenceBindingAuthority",
]
