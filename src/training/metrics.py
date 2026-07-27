"""Primitive-only structured training metrics and JSONL logging."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import TrainingError


@dataclass(frozen=True)
class TrainingMetric:
    global_step: int
    loss: float
    learning_rate: float
    gradient_norm: float
    gradient_norm_before_clip: float
    tokens_seen: int
    records_seen: int
    step_time: float
    tokens_per_second: float
    peak_memory_allocated: int
    peak_memory_reserved: int
    amp_step_skipped: bool = False
    micro_step: int = 0
    amp_scale: float = 1.0
    sampler_cursor: int | None = None
    equivalent_epoch: float = 0.0
    cpu_working_set_bytes: int | None = None
    remaining_disk_bytes: int | None = None
    run_output_bytes: int | None = None
    elapsed_wall_clock: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonlMetricLogger:
    def __init__(self, path: Path, *, append: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._mode = "a" if append else "x"

    def write(self, metric: TrainingMetric) -> None:
        value = metric.to_dict()
        if any(isinstance(item, float) and not math.isfinite(item) for item in value.values()):
            raise TrainingError("NON_FINITE_LOSS", "metric에 NaN 또는 Inf를 기록할 수 없습니다.")
        try:
            with self.path.open(self._mode, encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._mode = "a"
        except FileExistsError as exc:
            raise TrainingError("CHECKPOINT_ALREADY_EXISTS", "기존 metric log를 덮어쓸 수 없습니다.") from exc
