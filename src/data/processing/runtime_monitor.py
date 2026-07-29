"""Measured runtime and RSS guardrails for processing."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable


class RuntimeMonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBudget:
    soft_limit_seconds: float = 1200.0
    hard_limit_seconds: float = 1800.0
    maximum_records: int = 11_902
    maximum_output_bytes: int = 512 * 1024 * 1024
    soft_memory_bytes: int = 1536 * 1024 * 1024
    hard_memory_bytes: int = 2048 * 1024 * 1024


def process_rss_bytes() -> int:
    """Return current RSS using an OS facility, or fail closed."""

    try:
        import psutil

        value = int(psutil.Process(os.getpid()).memory_info().rss)
        if value > 0:
            return value
    except (ImportError, OSError, ValueError, AttributeError):
        pass

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(Counters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            handle = kernel32.GetCurrentProcess()
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise OSError
            value = int(counters.WorkingSetSize)
        except (AttributeError, OSError, ValueError):
            raise RuntimeMonitorError("MEMORY_MEASUREMENT_UNAVAILABLE") from None
    else:
        try:
            import resource

            value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if value < 1024 * 1024:
                value *= 1024
        except (ImportError, OSError, ValueError):
            raise RuntimeMonitorError("MEMORY_MEASUREMENT_UNAVAILABLE") from None
    if value <= 0:
        raise RuntimeMonitorError("MEMORY_MEASUREMENT_UNAVAILABLE")
    return value


class RuntimeMonitor:
    def __init__(
        self,
        budget: RuntimeBudget = RuntimeBudget(),
        *,
        clock: Callable[[], float] = time.monotonic,
        memory_provider: Callable[[], int] = process_rss_bytes,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.budget = budget
        self.clock = clock
        self.memory_provider = memory_provider
        self.cancelled = cancelled
        self.started = clock()
        self.phase = "initialized"
        self.source_records = 0
        self.output_records = 0
        self.exclusion_count = 0
        self.output_bytes = 0
        self.current_rss_bytes = 0
        self.peak_rss_bytes = 0
        self.soft_runtime_triggered = False
        self.soft_memory_triggered = False
        self.check("initialized")

    def check(
        self,
        phase: str,
        *,
        source_records: int | None = None,
        output_records: int | None = None,
        exclusion_count: int | None = None,
        output_bytes: int | None = None,
    ) -> None:
        self.phase = phase
        if source_records is not None:
            self.source_records = source_records
        if output_records is not None:
            self.output_records = output_records
        if exclusion_count is not None:
            self.exclusion_count = exclusion_count
        if output_bytes is not None:
            self.output_bytes = output_bytes
        try:
            current = self.memory_provider()
        except RuntimeMonitorError:
            raise
        except Exception:
            raise RuntimeMonitorError("MEMORY_MEASUREMENT_UNAVAILABLE") from None
        if isinstance(current, bool) or not isinstance(current, int) or current <= 0:
            raise RuntimeMonitorError("MEMORY_MEASUREMENT_UNAVAILABLE")
        self.current_rss_bytes = current
        self.peak_rss_bytes = max(self.peak_rss_bytes, current)
        elapsed = self.elapsed_seconds()
        self.soft_runtime_triggered |= elapsed > self.budget.soft_limit_seconds
        self.soft_memory_triggered |= current > self.budget.soft_memory_bytes
        if self.cancelled():
            raise RuntimeMonitorError("PROCESSING_CANCELLED")
        if elapsed > self.budget.hard_limit_seconds:
            raise RuntimeMonitorError("RUNTIME_HARD_LIMIT_EXCEEDED")
        if current > self.budget.hard_memory_bytes:
            raise RuntimeMonitorError("MEMORY_HARD_LIMIT_EXCEEDED")
        if self.source_records > self.budget.maximum_records:
            raise RuntimeMonitorError("RECORD_BUDGET_EXCEEDED")
        if self.output_bytes > self.budget.maximum_output_bytes:
            raise RuntimeMonitorError("OUTPUT_TOTAL_BYTES_EXCEEDED")

    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock() - self.started)

    def summary(self) -> dict[str, object]:
        return {
            "elapsed_seconds": self.elapsed_seconds(),
            "source_records": self.source_records,
            "output_records": self.output_records,
            "exclusion_count": self.exclusion_count,
            "exclusion_rate": 0.0 if not self.source_records else self.exclusion_count / self.source_records,
            "current_rss_mib": self.current_rss_bytes / (1024 * 1024),
            "peak_rss_mib": self.peak_rss_bytes / (1024 * 1024),
            "soft_runtime_triggered": self.soft_runtime_triggered,
            "soft_memory_triggered": self.soft_memory_triggered,
            "current_phase": self.phase,
        }
