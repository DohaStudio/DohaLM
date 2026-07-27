"""External benchmark interface; all registrations are fail-closed by default."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import EvaluationError


@dataclass(frozen=True)
class BenchmarkRegistration:
    dataset_id: str
    version: str | None
    license_status: str
    evaluation_purpose_approval: str
    contamination_status: str
    redistribution_status: str
    download_status: str
    logical_external_path: str | None

    def require_eligible(self) -> None:
        required = {
            "license_status": "approved",
            "evaluation_purpose_approval": "approved",
            "contamination_status": "passed",
            "download_status": "available_local",
        }
        for field, expected in required.items():
            if getattr(self, field) != expected:
                raise EvaluationError("BENCHMARK_NOT_APPROVED", f"benchmark {field} is not {expected}")
        if not self.version or not self.logical_external_path:
            raise EvaluationError("BENCHMARK_NOT_APPROVED", "benchmark version and logical path are required")


class BenchmarkAdapter(Protocol):
    """Interface only; implementations require a separately approved registration."""

    registration: BenchmarkRegistration

    def evaluate(self) -> dict[str, object]: ...
