"""Streaming batch and atomic artifact support for corpus adapters."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from src.data.artifacts import AtomicArtifactDirectory, write_json
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum

from .contracts import AdapterOutcome


ARTIFACT_SCHEMA_VERSION = "1.0"


def iter_adapted(records: Iterable[Any], adapter: Any) -> Iterator[AdapterOutcome]:
    """Adapt a one-pass iterable without materializing the input records."""

    for record in records:
        yield adapter.adapt_record(record)


class AdapterArtifactWriter:
    """Write adapter results incrementally and publish all four files atomically."""

    def __init__(self, output: Path, adapter: Any):
        self.output = output
        self.adapter = adapter

    def publish(
        self,
        outcomes: Iterable[AdapterOutcome],
        *,
        source_path: Path | None = None,
    ) -> dict[str, Any]:
        source_checksum_before = file_checksum(source_path) if source_path is not None else None
        atomic = AtomicArtifactDirectory(self.output)
        accepted_count = 0
        rejected_count = 0
        input_hashes: list[str] = []
        output_hashes: list[str] = []
        schema_counts: Counter[str] = Counter()
        reason_counts: Counter[str] = Counter()
        warning_counts: Counter[str] = Counter()

        with atomic as staging:
            accepted_path = staging / "accepted.jsonl"
            rejected_path = staging / "rejections.jsonl"
            with accepted_path.open("wb") as accepted_handle, rejected_path.open("wb") as rejected_handle:
                for outcome in outcomes:
                    value = outcome.accepted or outcome.rejected
                    assert value is not None
                    input_hashes.append(value["source_record_hash"])
                    if outcome.accepted is not None:
                        accepted_count += 1
                        output_hashes.append(value["lineage"]["output_record_hash"])
                        schema_counts[value["schema_signature"]] += 1
                        warning_counts.update(value.get("schema_warnings", []))
                        accepted_handle.write(canonical_json_bytes(value))
                    else:
                        rejected_count += 1
                        reason_counts[value["reason_code"]] += 1
                        rejected_handle.write(canonical_json_bytes(value))
                for handle in (accepted_handle, rejected_handle):
                    handle.flush()
                    os.fsync(handle.fileno())

            input_fingerprint = checksum_value({"source_record_hashes": sorted(input_hashes)})
            output_fingerprint = checksum_value({"output_record_hashes": sorted(output_hashes)})
            source_checksum_after = file_checksum(source_path) if source_path is not None else None
            source_mutation_detected = source_checksum_before != source_checksum_after
            if source_mutation_detected:
                raise RuntimeError("source input changed while the adapter was running")

            manifest = {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "adapter_name": self.adapter.name,
                "adapter_version": self.adapter.version,
                "dataset_id": self.adapter.dataset_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "input_record_count": accepted_count + rejected_count,
                "accepted_record_count": accepted_count,
                "rejected_record_count": rejected_count,
                "input_fingerprint": input_fingerprint,
                "output_fingerprint": output_fingerprint,
                "normalization_policy": self.adapter.normalization_policy,
                "schema_signatures": sorted(schema_counts),
                "rejection_reason_counts": dict(sorted(reason_counts.items())),
                "license_status": self.adapter.license_status,
                "approval_status": self.adapter.approval_status,
                "pii_status": self.adapter.pii_status,
                "source_mutation_detected": source_mutation_detected,
                "usage_status": self.adapter.usage_status,
                "usage_block_reasons": list(self.adapter.usage_block_reasons),
                "fingerprint": checksum_value({
                    "schema_version": ARTIFACT_SCHEMA_VERSION,
                    "adapter_name": self.adapter.name,
                    "adapter_version": self.adapter.version,
                    "dataset_id": self.adapter.dataset_id,
                    "input_record_count": accepted_count + rejected_count,
                    "accepted_record_count": accepted_count,
                    "rejected_record_count": rejected_count,
                    "input_fingerprint": input_fingerprint,
                    "output_fingerprint": output_fingerprint,
                    "normalization_policy": self.adapter.normalization_policy,
                    "schema_signatures": sorted(schema_counts),
                    "rejection_reason_counts": dict(sorted(reason_counts.items())),
                    "license_status": self.adapter.license_status,
                    "approval_status": self.adapter.approval_status,
                    "pii_status": self.adapter.pii_status,
                }),
            }
            schema_summary = {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "dataset_id": self.adapter.dataset_id,
                "schema_signature_counts": dict(sorted(schema_counts.items())),
                "schema_warning_counts": dict(sorted(warning_counts.items())),
                "unknown_field_policy": "ignore_value_hash_key_name",
                "values_recorded": False,
            }
            write_json(staging / "adapter-manifest.json", manifest)
            write_json(staging / "schema-summary.json", schema_summary)
            atomic.publish()
        return manifest


def load_synthetic_json_records(path: Path, *, max_read_bytes: int) -> Iterator[Any]:
    """Stream a bounded synthetic JSON array one record at a time.

    The byte cap prevents accidental use with an actual dataset. The synthetic-only
    CLI additionally restricts the path to the tracked fixture tree.
    """

    size = path.stat().st_size
    if size > max_read_bytes:
        raise ValueError("synthetic input exceeds --max-read-bytes")
    import json

    decoder = json.JSONDecoder()
    chunk_characters = 64 * 1024
    with path.open("r", encoding="utf-8") as handle:
        buffer = ""
        position = 0
        eof = False

        def refill() -> None:
            nonlocal buffer, position, eof
            if position:
                buffer = buffer[position:]
                position = 0
            chunk = handle.read(chunk_characters)
            if chunk:
                buffer += chunk
            else:
                eof = True

        def skip_whitespace() -> None:
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or eof:
                    return
                refill()

        refill()
        skip_whitespace()
        if position >= len(buffer) or buffer[position] != "[":
            raise ValueError("synthetic input root must be a JSON array")
        position += 1
        first = True
        while True:
            skip_whitespace()
            if position >= len(buffer):
                raise ValueError("unterminated synthetic JSON array")
            if buffer[position] == "]":
                position += 1
                break
            if not first:
                if buffer[position] != ",":
                    raise ValueError("synthetic JSON array requires a comma between records")
                position += 1
                skip_whitespace()
            while True:
                try:
                    value, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ValueError("invalid synthetic JSON record") from exc
                    refill()
                    continue
                position = end
                yield value
                first = False
                break

        skip_whitespace()
        if position < len(buffer) or not eof and handle.read(1):
            remainder = buffer[position:] + handle.read()
            if remainder.strip():
                raise ValueError("unexpected content after synthetic JSON array")
