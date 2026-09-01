from __future__ import annotations

import pytest

from src.training.current_evidence_gate import SnapshotTrainingCurrentEvidenceGate
from src.training.errors import TrainingError


def test_training_gate_rechecks_snapshot_and_fails_closed() -> None:
    class Bindings:
        def resolve_snapshot_binding(self, authority_id: str, fingerprint: str):
            assert authority_id == "66666666-6666-4666-8666-666666666666"
            assert fingerprint == "sha256:" + "6" * 64
            return "snapshot-1", "sha256:" + "7" * 64

    class Coordinator:
        current = True

        def verify(self, snapshot_id: str, fingerprint: str) -> None:
            assert snapshot_id == "snapshot-1"
            assert fingerprint == "sha256:" + "7" * 64
            if not self.current:
                raise RuntimeError("synthetic stale source")

    coordinator = Coordinator()
    gate = SnapshotTrainingCurrentEvidenceGate(Bindings(), coordinator)  # type: ignore[arg-type]
    gate.verify_currentness(
        "66666666-6666-4666-8666-666666666666", "sha256:" + "6" * 64
    )
    coordinator.current = False
    with pytest.raises(TrainingError, match="TRAINING_CURRENT_EVIDENCE_STALE"):
        gate.verify_currentness(
            "66666666-6666-4666-8666-666666666666", "sha256:" + "6" * 64
        )
