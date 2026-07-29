"""Post-write validation, source snapshots, budgets, and finalization gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Callable, Mapping

from src.data.aihub_71748_near_duplicate import normalize_near_duplicate_text


ALLOWED_OUTPUTS = frozenset({
    "train.jsonl", "validation.jsonl", "manifest.yaml", "statistics.json",
    "checksums.sha256", "processing-result.yaml",
})
CHECKSUM_TARGETS = tuple(sorted(ALLOWED_OUTPUTS - {"checksums.sha256"}))


class PostValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceSnapshot:
    zip_count: int
    total_bytes: int
    filename_aggregate: str
    modified_time_aggregate: str


def snapshot_source_metadata(root: str | Path) -> SourceSnapshot:
    paths = sorted(Path(root).rglob("*.zip"), key=lambda item: item.as_posix().casefold())
    if not paths:
        raise PostValidationError("SOURCE_SNAPSHOT_REQUIRED")
    names = hashlib.sha256()
    modified = hashlib.sha256()
    total = 0
    for path in paths:
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        names.update(relative.encode("utf-8"))
        names.update(b"\n")
        modified.update(relative.encode("utf-8"))
        modified.update(b"\0")
        modified.update(str(stat.st_mtime_ns).encode("ascii"))
        modified.update(b"\n")
        total += stat.st_size
    return SourceSnapshot(len(paths), total, names.hexdigest(), modified.hexdigest())


def validate_source_immutable(before: SourceSnapshot, after: SourceSnapshot) -> None:
    if after.zip_count > before.zip_count:
        raise PostValidationError("SOURCE_FILE_ADDED")
    if after.zip_count < before.zip_count:
        raise PostValidationError("SOURCE_FILE_REMOVED")
    if before != after:
        raise PostValidationError("SOURCE_DATASET_MUTATED")


@dataclass(frozen=True)
class DiskBudget:
    minimum_free_bytes: int = 4_294_967_296
    staging_multiplier: int = 2
    safety_margin_ratio: float = 0.25


class DiskGuard:
    def __init__(
        self,
        root: str | Path,
        budget: DiskBudget = DiskBudget(),
        *,
        provider: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    ) -> None:
        self.root = Path(root)
        while not self.root.exists() and self.root != self.root.parent:
            self.root = self.root.parent
        self.budget = budget
        self.provider = provider
        self.free_bytes_before = self._measure()
        self.free_bytes_current = self.free_bytes_before
        self.bytes_written = 0
        self.check(estimated_remaining_bytes=0)

    def _measure(self) -> int:
        try:
            value = self.provider(self.root)
        except Exception:
            raise PostValidationError("DISK_MEASUREMENT_FAILED") from None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PostValidationError("DISK_MEASUREMENT_FAILED")
        return value

    def check(self, *, estimated_remaining_bytes: int, bytes_written: int | None = None) -> None:
        self.free_bytes_current = self._measure()
        if bytes_written is not None:
            self.bytes_written = bytes_written
        reserve = int(estimated_remaining_bytes * (self.budget.staging_multiplier + self.budget.safety_margin_ratio))
        if self.free_bytes_current - reserve < self.budget.minimum_free_bytes:
            code = "DISK_BUDGET_INSUFFICIENT" if self.bytes_written == 0 else "DISK_BUDGET_EXCEEDED_DURING_WRITE"
            raise PostValidationError(code)

    def summary(self) -> dict[str, int]:
        return {
            "free_bytes_before": self.free_bytes_before,
            "free_bytes_current": self.free_bytes_current,
            "bytes_written": self.bytes_written,
            "minimum_free_bytes": self.budget.minimum_free_bytes,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        raise PostValidationError("CHECKSUM_GENERATION_FAILED") from None
    return digest.hexdigest()


def generate_checksums(root: str | Path) -> Mapping[str, str]:
    directory = Path(root)
    if any(not (directory / name).is_file() for name in CHECKSUM_TARGETS):
        raise PostValidationError("CHECKSUM_ENTRY_MISSING")
    checksums = {name: _sha256(directory / name) for name in CHECKSUM_TARGETS}
    text = "".join(f"{digest}  {name}\n" for name, digest in checksums.items())
    try:
        (directory / "checksums.sha256").write_text(text, encoding="ascii")
    except OSError:
        raise PostValidationError("CHECKSUM_GENERATION_FAILED") from None
    return checksums


def validate_checksums(root: str | Path) -> Mapping[str, str]:
    directory = Path(root)
    try:
        lines = (directory / "checksums.sha256").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        raise PostValidationError("CHECKSUM_FILE_INVALID") from None
    entries: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or len(parts[0]) != 64
            or any(character not in "0123456789abcdef" for character in parts[0])
            or Path(parts[1]).name != parts[1]
        ):
            raise PostValidationError("CHECKSUM_FILE_INVALID")
        if parts[1] in entries:
            raise PostValidationError("CHECKSUM_FILE_INVALID")
        entries[parts[1]] = parts[0]
    if set(entries) - set(CHECKSUM_TARGETS):
        raise PostValidationError("CHECKSUM_ENTRY_UNEXPECTED")
    if set(CHECKSUM_TARGETS) - set(entries):
        raise PostValidationError("CHECKSUM_ENTRY_MISSING")
    if any(_sha256(directory / name) != digest for name, digest in entries.items()):
        raise PostValidationError("CHECKSUM_MISMATCH")
    return dict(sorted(entries.items()))


def validate_output_budget(
    root: str | Path,
    *,
    expected_files: int = 6,
    maximum_files: int = 6,
    maximum_total_bytes: int = 536_870_912,
) -> dict[str, int]:
    directory = Path(root)
    try:
        entries = list(directory.iterdir())
    except OSError:
        raise PostValidationError("OUTPUT_FILE_COUNT_MISMATCH") from None
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise PostValidationError("OUTPUT_FILE_NOT_ALLOWED")
    names = {entry.name for entry in entries}
    if names - ALLOWED_OUTPUTS:
        raise PostValidationError("OUTPUT_FILE_NOT_ALLOWED")
    if len(entries) > maximum_files:
        raise PostValidationError("OUTPUT_FILE_BUDGET_EXCEEDED")
    if len(entries) != expected_files or names != ALLOWED_OUTPUTS:
        raise PostValidationError("OUTPUT_FILE_COUNT_MISMATCH")
    total = sum(entry.stat().st_size for entry in entries)
    if total > maximum_total_bytes:
        raise PostValidationError("OUTPUT_TOTAL_BYTES_EXCEEDED")
    return {"file_count": len(entries), "total_bytes": total}


def _read_jsonl(path: Path) -> tuple[list[tuple[str, str]], dict[str, int]]:
    pairs: list[tuple[str, str]] = []
    counts = {"lines": 0, "malformed_lines": 0, "invalid_schema_lines": 0, "forbidden_field_lines": 0}
    try:
        stream = path.open("r", encoding="utf-8")
    except (OSError, UnicodeError):
        raise PostValidationError("JSONL_VALIDATION_FAILED") from None
    try:
        with stream:
            for line in stream:
                counts["lines"] += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    raise PostValidationError("JSONL_MALFORMED_RECORD") from None
                if not isinstance(record, dict) or set(record) != {"instruction", "input", "output", "system"}:
                    raise PostValidationError("JSONL_FORBIDDEN_FIELD")
                if (
                    not isinstance(record["instruction"], str)
                    or not record["instruction"].strip()
                    or not isinstance(record["output"], str)
                    or not record["output"].strip()
                    or (record["input"] is not None and not isinstance(record["input"], str))
                    or (record["system"] is not None and not isinstance(record["system"], str))
                ):
                    raise PostValidationError("JSONL_SCHEMA_MISMATCH")
                pairs.append((record["instruction"], record["output"]))
    except UnicodeError:
        raise PostValidationError("JSONL_VALIDATION_FAILED") from None
    return pairs, counts


def validate_jsonl_and_splits(
    root: str | Path,
    *,
    expected_training: int,
    expected_validation: int,
    minimum_training: int,
    minimum_validation: int,
) -> dict[str, object]:
    directory = Path(root)
    training, train_counts = _read_jsonl(directory / "train.jsonl")
    validation, validation_counts = _read_jsonl(directory / "validation.jsonl")
    if len(training) != expected_training or len(validation) != expected_validation:
        raise PostValidationError("JSONL_COUNT_MISMATCH")
    if len(training) < minimum_training:
        raise PostValidationError("TRAINING_SIZE_BELOW_MINIMUM")
    if len(validation) < minimum_validation:
        raise PostValidationError("VALIDATION_SIZE_BELOW_MINIMUM")
    exact = set(training)
    normalized = {
        (normalize_near_duplicate_text(question), normalize_near_duplicate_text(answer))
        for question, answer in training
    }
    for pair in validation:
        if pair in exact:
            raise PostValidationError("CROSS_SPLIT_EXACT_QA_PRESENT")
        candidate = tuple(normalize_near_duplicate_text(value) for value in pair)
        if candidate in normalized:
            raise PostValidationError("CROSS_SPLIT_NORMALIZED_QA_PRESENT")
    return {
        "train_lines": train_counts["lines"],
        "validation_lines": validation_counts["lines"],
        "malformed_lines": 0,
        "invalid_schema_lines": 0,
        "forbidden_field_lines": 0,
        "jsonl_valid": True,
        "split_isolation_valid": True,
    }


@dataclass(frozen=True)
class FinalizationGate:
    approval_consumed: bool
    processing_calls: int
    payload_open_sessions: int
    payload_session_closed: bool
    statistics_valid: bool
    record_budget_valid: bool
    exclusion_threshold_valid: bool
    jsonl_valid: bool
    split_valid: bool
    checksum_valid: bool
    source_immutable: bool
    runtime_hard_limit_exceeded: bool
    memory_hard_limit_exceeded: bool
    disk_budget_valid: bool
    output_budget_valid: bool
    unresolved_records: int
    malformed_records: int
    join_failures: int


def validate_finalization_gate(gate: FinalizationGate) -> None:
    required = (
        gate.approval_consumed,
        gate.processing_calls == 1,
        gate.payload_open_sessions == 1,
        gate.payload_session_closed,
        gate.statistics_valid,
        gate.record_budget_valid,
        gate.exclusion_threshold_valid,
        gate.jsonl_valid,
        gate.split_valid,
        gate.checksum_valid,
        gate.source_immutable,
        not gate.runtime_hard_limit_exceeded,
        not gate.memory_hard_limit_exceeded,
        gate.disk_budget_valid,
        gate.output_budget_valid,
        gate.unresolved_records == 0,
        gate.malformed_records == 0,
        gate.join_failures == 0,
    )
    if not all(required):
        raise PostValidationError("FINALIZATION_GATE_FAILED")
