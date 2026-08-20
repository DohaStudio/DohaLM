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
    amp_overflow_count: int = 0
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


@dataclass(frozen=True)
class AmpOverflowEvent:
    """Text-free evidence for a recoverable AMP overflow attempt."""

    global_step: int
    next_optimizer_step: int
    attempt: int
    scale_before: float
    scale_after: float
    pending_tokens: int
    pending_records: int
    sampler_cursor: int | None
    model_parameters_finite: bool
    optimizer_state_finite: bool
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AmpNumericalDiagnostic:
    """Text-free, no-update evidence from one prospective loss-scale probe."""

    run_id: str
    global_step: int
    next_optimizer_step: int
    overflow_attempt: int
    probe_scale: float
    sampler_cursor: int | None
    pending_records: int
    pending_tokens: int
    batch_identity_sha256: str
    python_rng_sha256: str
    cpu_rng_sha256: str
    cuda_rng_sha256: str
    sampler_state_sha256: str | None
    model_state_sha256: str
    optimizer_state_sha256: str
    total_gradient_parameter_count: int
    scaled_finite_gradient_parameter_count: int
    scaled_non_finite_gradient_parameter_count: int
    scaled_non_finite_element_count: int
    scaled_gradients_finite: bool
    unscaled_finite_gradient_parameter_count: int
    unscaled_non_finite_gradient_parameter_count: int
    unscaled_non_finite_element_count: int
    unscaled_gradients_finite: bool
    first_offending_parameter_id: str | None
    first_offending_parameter_shape: tuple[int, ...] | None
    first_offending_parameter_dtype: str | None
    finite_gradient_max_abs: float
    finite_gradient_norm: float
    loss_finite: bool
    scaled_loss_finite: bool
    grad_scaler_found_inf: bool
    model_parameters_finite: bool
    optimizer_state_finite: bool
    model_state_unchanged: bool
    optimizer_state_unchanged: bool
    scheduler_state_unchanged: bool
    scaler_state_unchanged: bool
    sampler_state_unchanged: bool
    accounting_state_unchanged: bool
    rng_state_restored: bool
    optimizer_step_applied: bool
    actual_text_values_stored: bool
    token_ids_stored: bool
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonlMetricLogger:
    def __init__(self, path: Path, *, append: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._mode = "a" if append else "x"

    def write(
        self,
        metric: TrainingMetric | AmpOverflowEvent | AmpNumericalDiagnostic,
    ) -> None:
        value = metric.to_dict()
        if any(
            isinstance(item, float) and not math.isfinite(item)
            for item in value.values()
        ):
            raise TrainingError(
                "NON_FINITE_LOSS", "metric에 NaN 또는 Inf를 기록할 수 없습니다."
            )
        try:
            with self.path.open(self._mode, encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        value, ensure_ascii=False, sort_keys=True, allow_nan=False
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            self._mode = "a"
        except FileExistsError as exc:
            raise TrainingError(
                "CHECKPOINT_ALREADY_EXISTS", "기존 metric log를 덮어쓸 수 없습니다."
            ) from exc
