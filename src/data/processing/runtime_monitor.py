"""Aggregate-only runtime limits for a future approved processing run."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable


class RuntimeMonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBudget:
    maximum_seconds: float = 1800.0
    maximum_records: int = 20_000
    maximum_output_bytes: int = 512 * 1024 * 1024
    maximum_memory_bytes: int = 2 * 1024 * 1024 * 1024


class RuntimeMonitor:
    def __init__(
        self,
        budget: RuntimeBudget = RuntimeBudget(),
        *,
        clock: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.budget = budget
        self.clock = clock
        self.cancelled = cancelled
        self.started = clock()
        self.phase = "initialized"
        self.processed_records = 0
        self.source_records = 0
        self.output_records = 0
        self.exclusion_count = 0
        self.memory_estimate_bytes = 0
        self.disk_estimate_bytes = 0

    def check(
        self,
        phase: str,
        *,
        source_records: int | None = None,
        output_records: int | None = None,
        exclusion_count: int | None = None,
        output_bytes: int = 0,
        memory_bytes: int = 0,
    ) -> None:
        self.phase = phase
        if source_records is not None:
            self.source_records = source_records
            self.processed_records = source_records
        if output_records is not None:
            self.output_records = output_records
        if exclusion_count is not None:
            self.exclusion_count = exclusion_count
        self.memory_estimate_bytes = memory_bytes
        self.disk_estimate_bytes = output_bytes
        if self.cancelled():
            raise RuntimeMonitorError("PROCESSING_CANCELLED")
        if self.clock() - self.started > self.budget.maximum_seconds:
            raise RuntimeMonitorError("RUNTIME_BUDGET_EXCEEDED")
        if self.source_records > self.budget.maximum_records:
            raise RuntimeMonitorError("RECORD_BUDGET_EXCEEDED")
        if output_bytes > self.budget.maximum_output_bytes:
            raise RuntimeMonitorError("OUTPUT_BUDGET_EXCEEDED")
        if memory_bytes > self.budget.maximum_memory_bytes:
            raise RuntimeMonitorError("MEMORY_BUDGET_EXCEEDED")

    def summary(self) -> dict[str, object]:
        return {
            "elapsed_seconds": max(0.0, self.clock() - self.started),
            "processed_records": self.processed_records,
            "source_records": self.source_records,
            "output_records": self.output_records,
            "exclusion_count": self.exclusion_count,
            "exclusion_rate": 0.0 if not self.source_records else self.exclusion_count / self.source_records,
            "memory_estimate_bytes": self.memory_estimate_bytes,
            "disk_estimate_bytes": self.disk_estimate_bytes,
            "current_phase": self.phase,
        }
