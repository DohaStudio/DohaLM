"""ADR-034 Rights currentness gate for Training intent and activation."""

from __future__ import annotations

from typing import Protocol

from src.data.current_evidence_snapshot import DatasetGovernanceSnapshotCoordinator

from .errors import TrainingError


class ReadinessCurrentEvidenceBindingPort(Protocol):
    def resolve_snapshot_binding(
        self, readiness_authority_id: str, readiness_fingerprint: str
    ) -> tuple[str, str]: ...


class TrainingCurrentEvidencePort(Protocol):
    def verify_currentness(
        self, readiness_authority_id: str, readiness_fingerprint: str
    ) -> None: ...


class SnapshotTrainingCurrentEvidenceGate:
    """Resolve a trusted readiness binding and recheck both source tokens."""

    def __init__(
        self,
        bindings: ReadinessCurrentEvidenceBindingPort,
        coordinator: DatasetGovernanceSnapshotCoordinator,
    ) -> None:
        self._bindings = bindings
        self._coordinator = coordinator

    def verify_currentness(
        self, readiness_authority_id: str, readiness_fingerprint: str
    ) -> None:
        try:
            snapshot_id, snapshot_fingerprint = self._bindings.resolve_snapshot_binding(
                readiness_authority_id, readiness_fingerprint
            )
            self._coordinator.verify(snapshot_id, snapshot_fingerprint)
        except Exception:
            raise TrainingError(
                "TRAINING_CURRENT_EVIDENCE_STALE",
                "The bound Dataset Rights evidence is unavailable or no longer current.",
            ) from None


__all__ = [
    "ReadinessCurrentEvidenceBindingPort",
    "SnapshotTrainingCurrentEvidenceGate",
    "TrainingCurrentEvidencePort",
]
