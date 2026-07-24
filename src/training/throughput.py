"""Primitive throughput summaries for bounded training validation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .errors import TrainingError
from .metrics import TrainingMetric


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


@dataclass(frozen=True)
class ThroughputSummary:
    measured_optimizer_steps: int
    excluded_warmup_steps: int
    total_optimizer_steps: int
    total_tokens: int
    total_records: int
    tokens_per_second: float
    records_per_second: float
    optimizer_steps_per_second: float
    mean_step_time: float
    p50_step_time: float
    p95_step_time: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_throughput(metrics: Iterable[TrainingMetric], *, exclude_warmup_steps: int = 0) -> ThroughputSummary:
    values = list(metrics)
    if exclude_warmup_steps < 0 or exclude_warmup_steps >= len(values):
        raise TrainingError("INVALID_TRAINING_CONFIG", "throughput warmup 제외 범위가 유효하지 않습니다.")
    measured = values[exclude_warmup_steps:]
    durations = [metric.step_time for metric in measured]
    if not measured or any(not math.isfinite(value) or value <= 0 for value in durations):
        raise TrainingError("INVALID_TRAINING_CONFIG", "throughput 측정 시간이 유효하지 않습니다.")
    previous_tokens = values[exclude_warmup_steps - 1].tokens_seen if exclude_warmup_steps else 0
    previous_records = values[exclude_warmup_steps - 1].records_seen if exclude_warmup_steps else 0
    tokens = measured[-1].tokens_seen - previous_tokens
    records = measured[-1].records_seen - previous_records
    duration = sum(durations)
    if duration <= 0:
        raise TrainingError("INVALID_TRAINING_CONFIG", "throughput 분모는 0일 수 없습니다.")
    return ThroughputSummary(
        measured_optimizer_steps=len(measured),
        excluded_warmup_steps=exclude_warmup_steps,
        total_optimizer_steps=len(values),
        total_tokens=tokens,
        total_records=records,
        tokens_per_second=tokens / duration,
        records_per_second=records / duration,
        optimizer_steps_per_second=len(measured) / duration,
        mean_step_time=duration / len(measured),
        p50_step_time=_percentile(durations, 0.50),
        p95_step_time=_percentile(durations, 0.95),
    )
