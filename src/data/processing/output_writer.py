"""Atomic writer for validated SFT records; callers own approval enforcement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Iterable, Mapping

import yaml


ALLOWED_OUTPUTS = (
    "train.jsonl",
    "validation.jsonl",
    "manifest.yaml",
    "statistics.json",
    "checksums.sha256",
    "processing-result.yaml",
)


class OutputWriterError(RuntimeError):
    pass


def _safe_record(record: Mapping[str, object]) -> dict[str, object]:
    if set(record) != {"instruction", "input", "output", "system"}:
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if not isinstance(record["instruction"], str) or not isinstance(record["output"], str):
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if record["input"] is not None and not isinstance(record["input"], str):
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    if record["system"] is not None and not isinstance(record["system"], str):
        raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
    return dict(record)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> int:
    count = 0
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(_safe_record(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _checksum(path: Path) -> str:
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
) -> dict[str, object]:
    final = Path(run_root)
    staging = final.with_name(final.name + ".staging")
    if final.exists() or staging.exists():
        raise OutputWriterError("RUN_ID_ALREADY_USED")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        counts = {
            "train": _write_jsonl(staging / "train.jsonl", train_records),
            "validation": _write_jsonl(staging / "validation.jsonl", validation_records),
        }
        (staging / "manifest.yaml").write_text(yaml.safe_dump(dict(manifest), sort_keys=False), encoding="utf-8")
        (staging / "statistics.json").write_text(json.dumps(dict(statistics), sort_keys=True), encoding="utf-8")
        (staging / "processing-result.yaml").write_text(yaml.safe_dump(dict(result), sort_keys=False), encoding="utf-8")
        checksums = {
            name: _checksum(staging / name)
            for name in ALLOWED_OUTPUTS
            if name != "checksums.sha256"
        }
        checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items()))
        (staging / "checksums.sha256").write_text(checksum_text, encoding="ascii")
        if set(path.name for path in staging.iterdir()) != set(ALLOWED_OUTPUTS):
            raise OutputWriterError("OUTPUT_SCHEMA_MISMATCH")
        os.replace(staging, final)
        return {"counts": counts, "checksums": checksums, "finalized": True}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
