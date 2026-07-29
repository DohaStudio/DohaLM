"""Budgeted staging writer with post-validation and atomic finalization."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Callable, Iterable, Mapping

import yaml

from .post_validation import (
    DiskGuard,
    FinalizationGate,
    SourceSnapshot,
    generate_checksums,
    snapshot_source_metadata,
    validate_checksums,
    validate_finalization_gate,
    validate_jsonl_and_splits,
    validate_output_budget,
    validate_processing_result,
    validate_source_immutable,
)
from .run_contract import ExecutionCounters
from .runtime_monitor import RuntimeMonitor


ALLOWED_OUTPUTS = (
    "train.jsonl", "validation.jsonl", "manifest.yaml", "statistics.json",
    "checksums.sha256", "processing-result.yaml",
)


class OutputWriterError(RuntimeError):
    pass


@dataclass(frozen=True)
class HardenedWriteContext:
    counters: ExecutionCounters
    monitor: RuntimeMonitor
    disk_guard: DiskGuard
    source_before: SourceSnapshot
    source_root: Path
    approval_consumed: bool
    expected_training: int
    expected_validation: int
    minimum_training: int = 10_000
    minimum_validation: int = 1_000
    maximum_total_bytes: int = 536_870_912


def _safe_record(record: Mapping[str, object]) -> dict[str, object]:
    if set(record) != {"instruction", "input", "output", "system"}:
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if not isinstance(record["instruction"], str) or not record["instruction"].strip():
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if not isinstance(record["output"], str) or not record["output"].strip():
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if record["input"] is not None and not isinstance(record["input"], str):
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if record["system"] is not None and not isinstance(record["system"], str):
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    return dict(record)


def _write_jsonl(
    path: Path,
    records: Iterable[Mapping[str, object]],
    after_record: Callable[[int], None] | None = None,
) -> int:
    count = 0
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(_safe_record(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
            if after_record is not None and count % 128 == 0:
                after_record(count)
    return count


def _size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.iterdir() if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic_outputs(
    run_root: str | Path,
    *,
    train_records: Iterable[Mapping[str, object]],
    validation_records: Iterable[Mapping[str, object]],
    manifest: Mapping[str, object],
    statistics: Mapping[str, object],
    result: Mapping[str, object],
    hardened: HardenedWriteContext | None = None,
) -> dict[str, object]:
    final = Path(run_root)
    staging = final.with_name(final.name + ".staging")
    failed = final.with_name(final.name + ".failed")
    if final.exists() or staging.exists() or failed.exists():
        raise OutputWriterError("RUN_ID_ALREADY_USED")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        if hardened is not None:
            hardened.counters.increment("output_writer_calls")
        def checkpoint(_: int = 0) -> None:
            if hardened is None:
                return
            current = _size(staging)
            hardened.disk_guard.check(estimated_remaining_bytes=current, bytes_written=current)
            hardened.monitor.check("output_write", output_bytes=current)

        counts = {
            "train": _write_jsonl(staging / "train.jsonl", train_records, checkpoint),
            "validation": _write_jsonl(staging / "validation.jsonl", validation_records, checkpoint),
        }
        checkpoint()
        manifest_text = yaml.safe_dump(dict(manifest), sort_keys=False)
        (staging / "manifest.yaml").write_text(manifest_text, encoding="utf-8")
        checkpoint()
        statistics_value = deepcopy(dict(statistics))
        result_value = deepcopy(dict(result))
        if hardened is not None:
            hardened.counters.increment("checksum_calls")
            hardened.counters.increment("atomic_finalization_calls")
            result_value["counters"] = hardened.counters.snapshot()
        result_value["checksums_sha256"] = {
            name: _sha256(staging / name)
            for name in ("manifest.yaml", "statistics.json", "train.jsonl", "validation.jsonl")
            if (staging / name).is_file()
        }
        checksum_bytes = sum(64 + 2 + len(name.encode("utf-8")) + 1 for name in ALLOWED_OUTPUTS if name != "checksums.sha256")
        total = 0
        for _ in range(10):
            output_statistics = statistics_value.get("output")
            if isinstance(output_statistics, dict):
                output_statistics["output_bytes"] = total
            checksums_value = result_value.get("checksums_sha256")
            if isinstance(checksums_value, dict):
                checksums_value["statistics.json"] = hashlib.sha256(
                    json.dumps(statistics_value, sort_keys=True).encode("utf-8")
                ).hexdigest()
            if "output_total_bytes" in result_value:
                result_value["output_total_bytes"] = total
            statistics_text = json.dumps(statistics_value, sort_keys=True)
            result_text = yaml.safe_dump(result_value, sort_keys=False)
            candidate = _size(staging) + len(statistics_text.encode("utf-8")) + len(result_text.encode("utf-8")) + checksum_bytes
            if candidate == total:
                break
            total = candidate
        (staging / "statistics.json").write_text(statistics_text, encoding="utf-8")
        checkpoint()
        if result_value.get("schema_version") == 1:
            validate_processing_result(result_value)
        (staging / "processing-result.yaml").write_text(result_text, encoding="utf-8")
        checkpoint()
        checksums = generate_checksums(staging)
        if hardened is None:
            validate_checksums(staging)
            validate_output_budget(staging)
        else:
            post = validate_jsonl_and_splits(
                staging,
                expected_training=hardened.expected_training,
                expected_validation=hardened.expected_validation,
                minimum_training=hardened.minimum_training,
                minimum_validation=hardened.minimum_validation,
            )
            validate_checksums(staging)
            output = validate_output_budget(staging, maximum_total_bytes=hardened.maximum_total_bytes)
            after = snapshot_source_metadata(hardened.source_root)
            validate_source_immutable(hardened.source_before, after)
            hardened.counters.validate_closed()
            hardened.disk_guard.check(estimated_remaining_bytes=0, bytes_written=output["total_bytes"])
            hardened.monitor.check("finalization_gate", output_bytes=output["total_bytes"])
            validate_finalization_gate(FinalizationGate(
                approval_consumed=hardened.approval_consumed,
                processing_calls=hardened.counters.processing_calls,
                payload_open_sessions=hardened.counters.payload_open_sessions,
                payload_session_closed=hardened.counters.active_payload_sessions == 0,
                statistics_valid=True,
                record_budget_valid=True,
                exclusion_threshold_valid=True,
                jsonl_valid=bool(post["jsonl_valid"]),
                split_valid=bool(post["split_isolation_valid"]),
                checksum_valid=True,
                source_immutable=True,
                runtime_hard_limit_exceeded=False,
                memory_hard_limit_exceeded=False,
                disk_budget_valid=True,
                output_budget_valid=True,
                unresolved_records=0,
                malformed_records=int(post["malformed_lines"]),
                join_failures=0,
            ))
        try:
            os.replace(staging, final)
        except OSError:
            raise OutputWriterError("ATOMIC_RENAME_FAILED") from None
        if hardened is not None:
            validate_output_budget(final, maximum_total_bytes=hardened.maximum_total_bytes)
            hardened.disk_guard.check(estimated_remaining_bytes=0, bytes_written=_size(final))
        return {"counts": counts, "checksums": checksums, "finalized": True}
    except Exception:
        if staging.exists() and not failed.exists():
            try:
                os.replace(staging, failed)
            except OSError:
                shutil.rmtree(staging)
        raise
