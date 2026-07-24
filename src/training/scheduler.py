"""Optimizer-step-based linear warmup and linear decay."""

from __future__ import annotations

from typing import Any

from torch.optim import Optimizer

from .errors import TrainingError


class LinearWarmupDecayScheduler:
    def __init__(self, optimizer: Optimizer, *, warmup_steps: int, max_steps: int):
        if warmup_steps < 0 or max_steps <= 0 or warmup_steps > max_steps:
            raise TrainingError("INVALID_TRAINING_CONFIG", "scheduler step 범위가 유효하지 않습니다.")
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.max_steps = max_steps
        self.current_step = 0
        self.base_lrs = [float(group["lr"]) for group in optimizer.param_groups]
        self._apply()

    def factor(self, step: int) -> float:
        if step < 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "scheduler step은 음수일 수 없습니다.")
        if self.warmup_steps and step < self.warmup_steps:
            return step / self.warmup_steps
        if step >= self.max_steps:
            return 0.0
        decay_span = self.max_steps - self.warmup_steps
        return 1.0 if decay_span == 0 else (self.max_steps - step) / decay_span

    def _apply(self) -> None:
        factor = self.factor(self.current_step)
        for base_lr, group in zip(self.base_lrs, self.optimizer.param_groups, strict=True):
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
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if state.get("warmup_steps") != self.warmup_steps or state.get("max_steps") != self.max_steps:
            raise TrainingError("RESUME_STATE_MISMATCH", "scheduler 설정이 checkpoint와 일치하지 않습니다.")
        if state.get("base_lrs") != self.base_lrs:
            raise TrainingError("RESUME_STATE_MISMATCH", "scheduler base learning rate가 일치하지 않습니다.")
        step = state.get("current_step")
        if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step <= self.max_steps:
            raise TrainingError("RESUME_STATE_MISMATCH", "scheduler current_step이 유효하지 않습니다.")
        self.current_step = step
        self._apply()
