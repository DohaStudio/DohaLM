"""Serializable training progress and lineage state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TrainingState:
    global_step: int = 0
    micro_step: int = 0
    optimizer_step: int = 0
    epoch: int = 0
    tokens_seen: int = 0
    records_seen: int = 0
    best_metric: float | None = None
    last_loss: float | None = None
    last_learning_rate: float | None = None
    started_at: str = ""
    updated_at: str = ""
    model_config_fingerprint: str = ""
    training_config_fingerprint: str = ""
    dataset_fingerprint: str = ""
    tokenizer_fingerprint: str = ""
    sampler_state: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = utc_now()
        if not self.updated_at:
            self.updated_at = self.started_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TrainingState":
        return cls(**value)
