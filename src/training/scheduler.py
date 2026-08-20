"""Optimizer-step-based linear and candidate cosine schedules."""

from __future__ import annotations

import math
from typing import Any

from torch.optim import Optimizer

from .errors import TrainingError


class LinearWarmupDecayScheduler:
    def __init__(self, optimizer: Optimizer, *, warmup_steps: int, max_steps: int):
        if warmup_steps < 0 or max_steps <= 0 or warmup_steps > max_steps:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG", "scheduler step 범위가 유효하지 않습니다."
            )
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.max_steps = max_steps
        self.current_step = 0
        self.base_lrs = [float(group["lr"]) for group in optimizer.param_groups]
        self._apply()

    def factor(self, step: int) -> float:
        if step < 0:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG", "scheduler step은 음수일 수 없습니다."
            )
        if self.warmup_steps and step < self.warmup_steps:
            return step / self.warmup_steps
        if step >= self.max_steps:
            return 0.0
        decay_span = self.max_steps - self.warmup_steps
        return 1.0 if decay_span == 0 else (self.max_steps - step) / decay_span

    def _apply(self) -> None:
        factor = self.factor(self.current_step)
        for base_lr, group in zip(
            self.base_lrs, self.optimizer.param_groups, strict=True
        ):
            group["lr"] = max(0.0, base_lr * factor)

    def step(self) -> None:
        self.current_step += 1
        self._apply()

    def get_last_lr(self) -> list[float]:
        return [float(group["lr"]) for group in self.optimizer.param_groups]

    def state_dict(self) -> dict[str, Any]:
        return {
            "current_step": self.current_step,
            "warmup_steps": self.warmup_steps,
            "max_steps": self.max_steps,
            "base_lrs": self.base_lrs,
            "scheduler_type": "linear",
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("scheduler_type", "linear") != "linear":
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "linear scheduler type이 checkpoint와 일치하지 않습니다.",
            )
        self._load_common_state(state)

    def _load_common_state(self, state: dict[str, Any]) -> None:
        if (
            state.get("warmup_steps") != self.warmup_steps
            or state.get("max_steps") != self.max_steps
        ):
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "scheduler 설정이 checkpoint와 일치하지 않습니다.",
            )
        if state.get("base_lrs") != self.base_lrs:
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "scheduler base learning rate가 일치하지 않습니다.",
            )
        step = state.get("current_step")
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 0 <= step <= self.max_steps
        ):
            raise TrainingError(
                "RESUME_STATE_MISMATCH", "scheduler current_step이 유효하지 않습니다."
            )
        self.current_step = step
        self._apply()


class CosineWarmupDecayScheduler(LinearWarmupDecayScheduler):
    """Linear warmup followed by cosine decay to a bounded minimum LR."""

    def __init__(
        self,
        optimizer: Optimizer,
        *,
        warmup_steps: int,
        max_steps: int,
        min_lr_ratio: float = 0.0,
    ):
        if not 0.0 <= min_lr_ratio <= 1.0:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG", "min_lr_ratio는 0 이상 1 이하여야 합니다."
            )
        self.min_lr_ratio = float(min_lr_ratio)
        super().__init__(optimizer, warmup_steps=warmup_steps, max_steps=max_steps)

    def factor(self, step: int) -> float:
        if step < 0:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG", "scheduler step은 음수일 수 없습니다."
            )
        if self.warmup_steps and step < self.warmup_steps:
            return step / self.warmup_steps
        if step >= self.max_steps:
            return self.min_lr_ratio
        decay_span = self.max_steps - self.warmup_steps
        if decay_span == 0:
            return self.min_lr_ratio
        progress = (step - self.warmup_steps) / decay_span
        cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
        return self.min_lr_ratio + (1.0 - self.min_lr_ratio) * cosine

    def state_dict(self) -> dict[str, Any]:
        value = super().state_dict()
        value["min_lr_ratio"] = self.min_lr_ratio
        value["scheduler_type"] = "cosine"
        return value

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if (
            state.get("scheduler_type") != "cosine"
            or state.get("min_lr_ratio") != self.min_lr_ratio
        ):
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "cosine scheduler 설정이 checkpoint와 일치하지 않습니다.",
            )
        self._load_common_state(state)

    def load_state_dict_for_horizon_extension(
        self,
        state: dict[str, Any],
        *,
        expected_source_step: int,
    ) -> None:
        """Restore an approved terminal cosine state onto a longer global horizon."""
        if (
            state.get("scheduler_type") != "cosine"
            or state.get("min_lr_ratio") != self.min_lr_ratio
            or state.get("warmup_steps") != self.warmup_steps
            or state.get("base_lrs") != self.base_lrs
            or state.get("current_step") != expected_source_step
            or state.get("max_steps") != expected_source_step
            or self.max_steps <= expected_source_step
        ):
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "Approved cosine horizon extension does not match the source checkpoint.",
            )
        self.current_step = expected_source_step
        self._apply()


def create_scheduler(
    optimizer: Optimizer,
    *,
    scheduler_type: str,
    warmup_steps: int,
    max_steps: int,
    min_lr_ratio: float,
) -> LinearWarmupDecayScheduler:
    if scheduler_type == "linear":
        return LinearWarmupDecayScheduler(
            optimizer, warmup_steps=warmup_steps, max_steps=max_steps
        )
    if scheduler_type == "cosine":
        return CosineWarmupDecayScheduler(
            optimizer,
            warmup_steps=warmup_steps,
            max_steps=max_steps,
            min_lr_ratio=min_lr_ratio,
        )
    raise TrainingError(
        "INVALID_TRAINING_CONFIG", "지원하지 않는 scheduler type입니다."
    )
