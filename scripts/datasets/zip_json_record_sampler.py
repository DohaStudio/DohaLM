"""ZIP 내부 대용량 JSON array에서 제한된 record 구조만 분석한다."""

from __future__ import annotations

import hashlib
import os
import shutil
import statistics
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from .analyzer import (
    AnalyzerConfig,
    DatasetEntry,
    LABEL_FIELD_NAMES,
    PII_FIELD_NAMES,
    TEXT_FIELD_NAMES,
    inventory_dataset,
)
from .json_record_stream import (
    ENTRY_READ_LIMIT_REACHED,
    INVALID_UTF8,
    MALFORMED_JSON_STRUCTURE,
    RECORD_OK,
    RECORD_PARSE_FAILED,
    RECORD_TOO_LARGE,
    RECORD_TRUNCATED,
    ROOT_NOT_ARRAY,
    RecordEvent,
    scan_json_array_records,
)
from .large_json_inspector import DEFAULT_LARGE_THRESHOLD_BYTES, LargeJsonCandidate, _large_candidates
from .manual_path_mapping import DEFAULT_MANUAL_SEED, ManualMapping
from .safe_sampler import (
    MAX_REJECTION_RECORDS,
    SamplerError,
    _atomic_json,
    _canonical_fingerprint,
    _iter_archives,
    _sha256_file,
    _sha256_text,
)


RECORD_SAMPLER_CONTRACT_VERSION = "1.0"
DEFAULT_MAX_ENTRIES = 3
DEFAULT_RECORDS_PER_ENTRY = 5
DEFAULT_MAX_RECORD_BYTES = 1024 * 1024
DEFAULT_MAX_READ_BYTES_PER_ENTRY = 16 * 1024 * 1024
DEFAULT_MAX_TOTAL_READ_BYTES = 32 * 1024 * 1024
DEFAULT_RECORD_SELECTION_SEED = "dohalm-zip-json-record-v1"

ALLOWED_SCHEMA_KEYS = frozenset({
    "text", "content", "instruction", "input", "output", "response",
    "question", "answer", "role", "label", "metadata", "source",
})


def record_sample_output_root(
    config: AnalyzerConfig,
    requested: str | Path | None,
    repository_root: Path,
) -> Path:
    allowed_root = (config.external_root / "analysis" / "record-samples").resolve()
    if requested is None:
        output = allowed_root
    else:
        raw = str(requested)
        if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            output = Path(raw).resolve()
        else:
            output = (config.external_root / Path(raw)).resolve()
    for dataset in config.entries.values():
        source = dataset.root.resolve()
        if output == source or source in output.parents or output in source.parents:
            raise SamplerError("record 분석 출력은 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("record 분석 출력은 external analysis/record-samples 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("record 분석 결과를 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _record_rank(
    dataset_id: str,
    archive_relative_path: str,
    entry_name_hash: str,
    record_index: int,
    seed: str,
) -> str:
    payload = "\n".join((seed, dataset_id, archive_relative_path, entry_name_hash, str(record_index)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _key_row(key: str) -> dict[str, Any]:
    normalized = key.casefold()
    return {
        "key_name_hash": _sha256_text(key),
        "sanitized_name": normalized if normalized in ALLOWED_SCHEMA_KEYS else None,
    }


def _candidate_classification(key: str) -> str:
    normalized = key.casefold()
    if normalized in PII_FIELD_NAMES:
        return "pii_review_required"
    if normalized in {"metadata", "source"}:
        return "metadata"
    if normalized in {"label", "role"} or normalized in LABEL_FIELD_NAMES:
        return "label"
    if normalized in {"text", "content", "instruction", "input", "output", "response", "question", "answer"}:
        return "likely_text"
    if normalized in TEXT_FIELD_NAMES:
        return "possible_text"
    return "not_recommended"


def _schema_signature(value: Any, depth: int = 0) -> str:
    if depth >= 64:
        return "depth_limit"
    if isinstance(value, dict):
        children = [
            f"{_sha256_text(str(key))}:{_schema_signature(child, depth + 1)}"
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        ]
        return "{" + ",".join(children) + "}"
    if isinstance(value, list):
        children = sorted({_schema_signature(child, depth + 1) for child in value[:100]})
        return "[" + "|".join(children) + "]"
    return _value_type(value)


def analyze_record(value: Any) -> dict[str, Any]:
    """record 원문 없이 key·type·길이 기반 구조 통계를 만든다."""

    value_types: Counter[str] = Counter()
    allowed_names: set[str] = set()
    hashed_names: dict[str, dict[str, Any]] = {}
    string_lengths: list[int] = []
    text_candidates: dict[str, dict[str, Any]] = {}
    label_candidates: dict[str, dict[str, Any]] = {}
    metadata_candidates: dict[str, dict[str, Any]] = {}
    pii_warnings: dict[str, dict[str, Any]] = {}
    key_count = 0
    maximum_depth = 0
    array_field_count = 0
    string_field_count = 0
    stack: list[tuple[Any, int, str | None]] = [(value, 0, None)]

    while stack:
        current, depth, field_name = stack.pop()
        maximum_depth = max(maximum_depth, depth)
        kind = _value_type(current)
        value_types[kind] += 1
        if isinstance(current, str):
            string_lengths.append(len(current))
            string_field_count += int(field_name is not None)
        elif isinstance(current, list):
            array_field_count += int(field_name is not None)
            stack.extend((item, depth + 1, None) for item in reversed(current))
        elif isinstance(current, dict):
            for raw_key, child in reversed(list(current.items())):
                key = str(raw_key)
                key_count += 1
                row = _key_row(key)
                if row["sanitized_name"] is not None:
                    allowed_names.add(row["sanitized_name"])
                else:
                    hashed_names.setdefault(row["key_name_hash"], row)
                classification = _candidate_classification(key)
                candidate = {
                    "key_name_hash": row["key_name_hash"],
                    "sanitized_name": row["sanitized_name"],
                    "classification": classification,
                    "value_type": _value_type(child),
                    "string_length": len(child) if isinstance(child, str) else None,
                }
                if classification in {"likely_text", "possible_text"}:
                    text_candidates[row["key_name_hash"]] = candidate
                elif classification == "label":
                    label_candidates[row["key_name_hash"]] = candidate
                elif classification == "metadata":
                    metadata_candidates[row["key_name_hash"]] = candidate
                elif classification == "pii_review_required":
                    pii_warnings[row["key_name_hash"]] = {
                        "key_name_hash": row["key_name_hash"],
                        "warning": "pii_field_name_signal",
                        "action": "manual_review_required",
                    }
                stack.append((child, depth + 1, key))

    shape = _schema_signature(value)
    return {
        "record_type": _value_type(value),
        "key_count": key_count,
        "allowed_key_names": sorted(allowed_names),
        "hashed_key_names": [hashed_names[key] for key in sorted(hashed_names)],
        "value_type_counts": dict(sorted(value_types.items())),
        "maximum_nested_depth": maximum_depth,
        "array_field_count": array_field_count,
        "string_field_count": string_field_count,
        "string_length_statistics": {
            "count": len(string_lengths),
            "minimum": min(string_lengths, default=0),
            "maximum": max(string_lengths, default=0),
            "average": statistics.fmean(string_lengths) if string_lengths else 0.0,
        },
        "text_field_candidates": [text_candidates[key] for key in sorted(text_candidates)],
        "label_field_candidates": [label_candidates[key] for key in sorted(label_candidates)],
        "metadata_field_candidates": [metadata_candidates[key] for key in sorted(metadata_candidates)],
        "pii_field_name_warnings": [pii_warnings[key] for key in sorted(pii_warnings)],
        "schema_signature": _sha256_text(shape),
    }


def _record_manifest_row(
    event: RecordEvent,
    analysis: Mapping[str, Any],
    *,
    archive_relative_path_hash: str,
    entry_name_hash: str,
    mapping_rule_id: str,
    selection_rank: str,
) -> dict[str, Any]:
    return {
        "archive_relative_path_hash": archive_relative_path_hash,
        "entry_name_hash": entry_name_hash,
        "mapping_rule_id": mapping_rule_id,
        "record_index": event.record_index,
        "selection_rank": selection_rank,
        "record_type": analysis["record_type"],
        "byte_size": event.byte_size,
        "checksum": event.checksum,
        "schema_signature": analysis["schema_signature"],
        "key_count": analysis["key_count"],
        "allowed_key_names": analysis["allowed_key_names"],
        "hashed_key_names": analysis["hashed_key_names"],
        "value_type_counts": analysis["value_type_counts"],
        "maximum_nested_depth": analysis["maximum_nested_depth"],
        "array_field_count": analysis["array_field_count"],
        "string_field_count": analysis["string_field_count"],
        "string_length_statistics": analysis["string_length_statistics"],
        "text_field_candidates": analysis["text_field_candidates"],
        "label_field_candidates": analysis["label_field_candidates"],
        "metadata_field_candidates": analysis["metadata_field_candidates"],
        "pii_field_name_warnings": analysis["pii_field_name_warnings"],
        "parse_status": RECORD_OK,
    }


def _inspect_entry(
    entry: DatasetEntry,
    candidate: LargeJsonCandidate,
    *,
    records_per_entry: int,
    max_record_bytes: int,
    max_read_bytes: int,
    selection_seed: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    archive_hash = _sha256_text(candidate.archive_relative_path)
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def on_record(event: RecordEvent) -> None:
        if event.status != RECORD_OK:
            if len(rejected) < MAX_REJECTION_RECORDS:
                rejected.append({
                    "archive_relative_path_hash": archive_hash,
                    "entry_name_hash": candidate.entry_name_hash,
                    "mapping_rule_id": candidate.rule.rule_id,
                    "record_index": event.record_index,
                    "status": event.status,
                    "byte_size": event.byte_size,
                    "checksum": event.checksum,
                })
            return
        rank = _record_rank(
            entry.dataset_id,
            candidate.archive_relative_path,
            candidate.entry_name_hash,
            event.record_index,
            selection_seed,
        )
        if len(selected) >= records_per_entry and rank >= selected[-1]["selection_rank"]:
            return
        analysis = analyze_record(event.value)
        selected.append(_record_manifest_row(
            event,
            analysis,
            archive_relative_path_hash=archive_hash,
            entry_name_hash=candidate.entry_name_hash,
            mapping_rule_id=candidate.rule.rule_id,
            selection_rank=rank,
        ))
        selected.sort(key=lambda row: (row["selection_rank"], row["record_index"]))
        if len(selected) > records_per_entry:
            selected.pop()

    try:
        with zipfile.ZipFile(candidate.archive_path) as archive:
            with archive.open(candidate.info, "r") as source:
                scan = scan_json_array_records(
                    source,
                    max_record_bytes=max_record_bytes,
                    max_read_bytes=max_read_bytes,
                    on_record=on_record,
                )
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise SamplerError("선택한 ZIP JSON entry를 제한 범위에서 검사할 수 없습니다.") from exc

    entry_summary = {
        "archive_relative_path_hash": archive_hash,
        "entry_name_hash": candidate.entry_name_hash,
        "mapping_rule_id": candidate.rule.rule_id,
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "entry_selection_rank": candidate.selection_rank,
        "scan_status": scan.status,
        "bytes_read": scan.bytes_read,
        "records_seen": scan.records_seen,
        "records_parsed": scan.records_parsed,
        "records_selected": len(selected),
        "records_rejected": scan.records_rejected,
        "array_started": scan.array_started,
        "root_closed": scan.root_closed,
        "truncated": scan.truncated,
        "parse_error": scan.parse_error,
    }
    if scan.status != RECORD_OK:
        rejected.append({
            "archive_relative_path_hash": archive_hash,
            "entry_name_hash": candidate.entry_name_hash,
            "mapping_rule_id": candidate.rule.rule_id,
            "record_index": None,
            "status": scan.status,
            "byte_size": None,
            "checksum": None,
        })
    return entry_summary, selected, rejected


def _planned_entry(candidate: LargeJsonCandidate) -> dict[str, Any]:
    return {
        "archive_relative_path_hash": _sha256_text(candidate.archive_relative_path),
        "entry_name_hash": candidate.entry_name_hash,
        "mapping_rule_id": candidate.rule.rule_id,
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "entry_selection_rank": candidate.selection_rank,
        "scan_status": "DRY_RUN_PLANNED",
        "bytes_read": 0,
        "records_seen": 0,
        "records_parsed": 0,
        "records_selected": 0,
        "records_rejected": 0,
    }


def _schema_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    signatures: Counter[str] = Counter(row["schema_signature"] for row in rows)
    allowed: Counter[str] = Counter()
    hashed: Counter[str] = Counter()
    types: Counter[str] = Counter()
    text_fields: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "occurrences": 0, "sanitized_name": None, "classification": None,
        "value_types": Counter(), "string_lengths": [],
    })
    pii: Counter[str] = Counter()
    for row in rows:
        allowed.update(row["allowed_key_names"])
        hashed.update(item["key_name_hash"] for item in row["hashed_key_names"])
        types.update(row["value_type_counts"])
        pii.update(item["key_name_hash"] for item in row["pii_field_name_warnings"])
        for field in row["text_field_candidates"]:
            aggregate = text_fields[field["key_name_hash"]]
            aggregate["occurrences"] += 1
            aggregate["sanitized_name"] = field["sanitized_name"]
            aggregate["classification"] = field["classification"]
            aggregate["value_types"][field["value_type"]] += 1
            if field["string_length"] is not None:
                aggregate["string_lengths"].append(field["string_length"])
    field_rows = []
    for key_hash, value in sorted(text_fields.items()):
        lengths = value["string_lengths"]
        field_rows.append({
            "key_name_hash": key_hash,
            "sanitized_name": value["sanitized_name"],
            "classification": value["classification"],
            "record_occurrence_count": value["occurrences"],
            "record_occurrence_ratio": value["occurrences"] / len(rows) if rows else 0.0,
            "value_type_counts": dict(sorted(value["value_types"].items())),
            "string_length_range": [min(lengths), max(lengths)] if lengths else None,
        })
    return {
        "schema_version": "1.0",
        "selected_record_count": len(rows),
        "schema_signatures": [
            {"schema_signature": signature, "count": count}
            for signature, count in sorted(signatures.items())
        ],
        "allowed_key_name_counts": dict(sorted(allowed.items())),
        "hashed_key_name_counts": dict(sorted(hashed.items())),
        "value_type_counts": dict(sorted(types.items())),
        "text_field_candidates": field_rows,
        "pii_field_name_warning_counts": dict(sorted(pii.items())),
        "schema_confirmed": False,
        "pii_absence_confirmed": False,
    }


def _archive_checksums(candidates: Iterable[LargeJsonCandidate]) -> dict[str, str]:
    unique: dict[str, Path] = {}
    for candidate in candidates:
        unique.setdefault(_sha256_text(candidate.archive_relative_path), candidate.archive_path)
    return {archive_hash: _sha256_file(path) for archive_hash, path in sorted(unique.items())}


def sample_zip_json_records(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    *,
    requested_archive: str | None,
    max_entries: int,
    records_per_entry: int,
    max_record_bytes: int,
    max_read_bytes_per_entry: int,
    max_total_read_bytes: int,
    dry_run: bool,
    selection_seed: str = DEFAULT_RECORD_SELECTION_SEED,
) -> dict[str, Any]:
    if min(max_entries, records_per_entry, max_record_bytes, max_read_bytes_per_entry, max_total_read_bytes) <= 0:
        raise SamplerError("entry, record와 byte 제한은 0보다 커야 합니다.")
    if mapping.dataset_id != entry.dataset_id:
        raise SamplerError("mapping dataset_id가 record 검사 대상과 일치하지 않습니다.")

    before = inventory_dataset(entry)
    archives = _iter_archives(entry, requested_archive)
    candidates = _large_candidates(
        entry,
        mapping,
        archives,
        threshold_bytes=DEFAULT_LARGE_THRESHOLD_BYTES,
        seed=DEFAULT_MANUAL_SEED,
    )
    selected_entries = candidates[:max_entries]
    mode = "dry-run" if dry_run else "inspection"
    fingerprint = _canonical_fingerprint({
        "contract_version": RECORD_SAMPLER_CONTRACT_VERSION,
        "mode": mode,
        "dataset_id": entry.dataset_id,
        "mapping_fingerprint": mapping.fingerprint,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "selection_seed": selection_seed,
        "limits": {
            "max_entries": max_entries,
            "records_per_entry": records_per_entry,
            "max_record_bytes": max_record_bytes,
            "max_read_bytes_per_entry": max_read_bytes_per_entry,
            "max_total_read_bytes": max_total_read_bytes,
        },
        "selected_entries": [[item.entry_name_hash, item.selection_rank] for item in selected_entries],
    })
    run_id = f"record-{'dry' if dry_run else 'inspect'}-" + fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 record 분석 결과가 이미 존재하여 덮어쓰지 않습니다.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()

    try:
        pre_checksums = {} if dry_run else _archive_checksums(selected_entries)
        entry_rows: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        total_bytes_read = 0
        total_limit_reached = False
        if dry_run:
            entry_rows = [_planned_entry(candidate) for candidate in selected_entries]
        else:
            for candidate in selected_entries:
                remaining = max_total_read_bytes - total_bytes_read
                if remaining <= 0:
                    total_limit_reached = True
                    break
                entry_limit = min(max_read_bytes_per_entry, remaining)
                entry_row, entry_records, entry_rejected = _inspect_entry(
                    entry,
                    candidate,
                    records_per_entry=records_per_entry,
                    max_record_bytes=max_record_bytes,
                    max_read_bytes=entry_limit,
                    selection_seed=selection_seed,
                )
                if entry_limit < max_read_bytes_per_entry and entry_row["scan_status"] == ENTRY_READ_LIMIT_REACHED:
                    entry_row["scan_status"] = "TOTAL_READ_LIMIT_REACHED"
                    total_limit_reached = True
                total_bytes_read += entry_row["bytes_read"]
                entry_rows.append(entry_row)
                records.extend(entry_records)
                rejected.extend(entry_rejected)
                if total_bytes_read >= max_total_read_bytes:
                    total_limit_reached = True
                    break

        after = inventory_dataset(entry)
        post_checksums = {} if dry_run else _archive_checksums(selected_entries)
        source_mutation = (
            before["inventory_metadata_digest"] != after["inventory_metadata_digest"]
            or pre_checksums != post_checksums
        )
        if source_mutation:
            raise SamplerError("record 분석 중 원본 ZIP 변경이 탐지됐습니다.")

        records.sort(key=lambda row: (row["entry_name_hash"], row["selection_rank"], row["record_index"]))
        schema = _schema_summary(records)
        manual_review = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "reasons": sorted({
                row["scan_status"] for row in entry_rows if row["scan_status"] not in {RECORD_OK, "DRY_RUN_PLANNED"}
            }),
            "pii_field_name_warning_count": sum(len(row["pii_field_name_warnings"]) for row in records),
            "schema_confirmed": False,
            "pii_absence_confirmed": False,
            "tokenizer_corpus_approved": False,
        }
        limits = {
            "max_entries": max_entries,
            "records_per_entry": records_per_entry,
            "max_record_bytes": max_record_bytes,
            "max_read_bytes_per_entry": max_read_bytes_per_entry,
            "max_total_read_bytes": max_total_read_bytes,
        }
        manifest = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "mapping_fingerprint": mapping.fingerprint,
            "selection_seed": selection_seed,
            "selection_strategy": "stable_sha256_rank_within_bounded_read",
            "representativeness": "bounded_read_only_not_full_file_sample",
            "limits": limits,
            "archives_scanned": len(archives),
            "entries_inspected": 0 if dry_run else len(entry_rows),
            "records_seen": sum(row["records_seen"] for row in entry_rows),
            "records_parsed": sum(row["records_parsed"] for row in entry_rows),
            "records_selected": len(records),
            "records_rejected": sum(row["records_rejected"] for row in entry_rows),
            "source_mutation_detected": False,
            "record_content_saved": False,
            "records": records,
            "run_fingerprint": fingerprint,
        }
        run_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "mode": mode,
            "status": "dry_run_planned" if dry_run else "inspection_complete",
            "candidate_entry_count": len(candidates),
            "entries_selected": len(selected_entries),
            "entries_inspected": 0 if dry_run else len(entry_rows),
            "records_seen": manifest["records_seen"],
            "records_parsed": manifest["records_parsed"],
            "records_selected": len(records),
            "records_rejected": manifest["records_rejected"],
            "total_bytes_read": total_bytes_read,
            "total_read_limit_reached": total_limit_reached,
            "full_entry_extraction_performed": False,
            "full_json_parse_performed": False,
            "record_content_saved": False,
            "source_mutation_detected": False,
            "selected_archive_checksums": [
                {
                    "archive_relative_path_hash": archive_hash,
                    "checksum_before": checksum,
                    "checksum_after": post_checksums[archive_hash],
                    "unchanged": checksum == post_checksums[archive_hash],
                }
                for archive_hash, checksum in sorted(pre_checksums.items())
            ],
        }
        _atomic_json(staging / "run-summary.json", run_summary)
        _atomic_json(staging / "entry-summary.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id, "entries": entry_rows,
        })
        _atomic_json(staging / "record-manifest.json", manifest)
        _atomic_json(staging / "schema-summary.json", schema)
        _atomic_json(staging / "rejected-records.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id,
            "records": rejected[:MAX_REJECTION_RECORDS],
            "records_omitted": max(0, len(rejected) - MAX_REJECTION_RECORDS),
        })
        _atomic_json(staging / "manual-review-required.json", manual_review)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return {
        "success": True,
        "dataset_id": entry.dataset_id,
        "run_id": run_id,
        "run_status": run_summary["status"],
        "dry_run": dry_run,
        "candidate_entry_count": len(candidates),
        "entries_selected": len(selected_entries),
        "entries_inspected": run_summary["entries_inspected"],
        "records_seen": run_summary["records_seen"],
        "records_parsed": run_summary["records_parsed"],
        "records_selected": run_summary["records_selected"],
        "records_rejected": run_summary["records_rejected"],
        "total_bytes_read": total_bytes_read,
        "source_mutation_detected": False,
        "output_location": "external_analysis_record_samples_root",
    }
