"""Phase 1 minimal data pipeline orchestration."""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.runtime.paths import repository_root

from .artifacts import AtomicArtifactDirectory, artifact_entry, count_jsonl, write_json, write_jsonl, write_yaml
from .checksums import checksum_value, file_checksum
from .config import DataConfig, load_data_config
from .deduplicate import deduplicate
from .discovery import discover_inputs
from .errors import DataIssue, DataPipelineError
from .models import CanonicalRecord, PipelineResult, RejectedRecord
from .readers import read_source
from .splitting import assign_splits, validate_no_leakage
from .validation import canonicalize, utc_now


SCHEMA_VERSION = "1.0"
PIPELINE_VERSION = "phase1-minimal-v1"
NORMALIZATION_VERSION = "nfc-lf-v1"


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "lineage", "Git SHA를 확인할 수 없습니다.")) from exc
    return result.stdout.strip()


def _check_approval(config: DataConfig) -> None:
    if config.license_status != "approved":
        raise DataPipelineError(DataIssue("UNAPPROVED_LICENSE", "approval", "license_status가 approved가 아닙니다."))
    if config.approval_status != "approved":
        raise DataPipelineError(DataIssue("UNAPPROVED_SOURCE", "approval", "approval_status가 approved가 아닙니다."))
    if config.pii_status != "clear":
        raise DataPipelineError(DataIssue("PII_NOT_CLEAR", "approval", "pii_status가 clear가 아닙니다."))


def _duplicate_id_rejections(records: list[CanonicalRecord]) -> tuple[list[CanonicalRecord], list[RejectedRecord]]:
    grouped: dict[str, list[CanonicalRecord]] = defaultdict(list)
    for record in records:
        grouped[record.source_record_id].append(record)
    kept: list[CanonicalRecord] = []
    rejected: list[RejectedRecord] = []
    for values in grouped.values():
        values.sort(key=lambda item: (item.source_path, item.source_record_id, item.record_id))
        kept.append(values[0])
        for record in values[1:]:
            rejected.append(
                RejectedRecord(
                    record.source_path,
                    record.source_record_id,
                    record.record_id,
                    "validation",
                    "DUPLICATE_RECORD_ID",
                    "dataset 안에서 source record ID가 중복됩니다.",
                    record.raw_record_checksum,
                    utc_now(),
                )
            )
    return kept, rejected


def _fingerprint(config: DataConfig, sources: list[Any], records: list[CanonicalRecord], assignments: list[Any]) -> str:
    return checksum_value(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": config.dataset_id,
            "dataset_version": config.dataset_version,
            "pipeline_version": PIPELINE_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "split": {
                "seed": config.split_seed,
                "train_ratio": config.train_ratio,
                "validation_ratio": config.validation_ratio,
                "test_ratio": config.test_ratio,
            },
            "input_files": [
                {"source_path": item.relative_path, "file_checksum": item.file_checksum} for item in sources
            ],
            "accepted_records": [
                {"record_id": item.record_id, "normalized_record_checksum": item.normalized_record_checksum}
                for item in sorted(records, key=lambda value: value.record_id)
            ],
            "split_mapping": [
                {"record_id": item.record_id, "split": item.split}
                for item in sorted(assignments, key=lambda value: (value.record_id, value.split))
            ],
        }
    )


def _source_entries(sources: list[Any], raw_counts: Counter[str], accepted: list[CanonicalRecord], rejected: list[RejectedRecord], duplicates: list[Any], config: DataConfig) -> list[dict[str, Any]]:
    accepted_counts = Counter(item.source_path for item in accepted)
    rejected_counts = Counter(item.source_path for item in rejected)
    duplicate_counts = Counter(item.source_path for item in duplicates)
    return [
        {
            "source_name": config.dataset_id,
            "source_path": source.relative_path,
            "format": source.format,
            "size_bytes": source.size_bytes,
            "file_checksum": source.file_checksum,
            "record_count": raw_counts[source.relative_path],
            "accepted_count": accepted_counts[source.relative_path],
            "rejected_count": rejected_counts[source.relative_path],
            "duplicate_count": duplicate_counts[source.relative_path],
            "license_status": config.license_status,
            "approval_status": config.approval_status,
            "pii_status": config.pii_status,
        }
        for source in sources
    ]


def validate_pipeline(config_path: str | Path, *, root: Path | None = None) -> PipelineResult:
    return _run(config_path, root=root, publish=False)


def build_pipeline(config_path: str | Path, *, root: Path | None = None) -> PipelineResult:
    return _run(config_path, root=root, publish=True)


def _run(config_path: str | Path, *, root: Path | None, publish: bool) -> PipelineResult:
    repo = (root or repository_root()).resolve()
    config = load_data_config(config_path)
    _check_approval(config)
    sources = discover_inputs(config, repo)
    initial_files = {item.relative_path: item.file_checksum for item in sources}
    raw_records = [record for source in sources for record in read_source(source, config.dataset_id)]
    raw_counts = Counter(record.source_path for record in raw_records)
    canonical: list[CanonicalRecord] = []
    rejected: list[RejectedRecord] = []
    for record in raw_records:
        result = canonicalize(record, config)
        if isinstance(result, RejectedRecord):
            if result.reason_code == "UNAPPROVED_SOURCE":
                raise DataPipelineError(DataIssue("UNAPPROVED_SOURCE", "validation", result.reason_message, result.source_path, result.source_record_id))
            rejected.append(result)
        else:
            canonical.append(result)
    canonical, duplicate_id_rejections = _duplicate_id_rejections(canonical)
    rejected.extend(duplicate_id_rejections)
    accepted, duplicates = deduplicate(canonical)
    if not accepted:
        raise DataPipelineError(DataIssue("MANIFEST_MISMATCH", "validation", "승인된 record가 0개입니다."))
    splits, assignments = assign_splits(accepted, config)
    validate_no_leakage(splits)
    current_sources = discover_inputs(config, repo)
    current_files = {item.relative_path: item.file_checksum for item in current_sources}
    if initial_files != current_files:
        raise DataPipelineError(DataIssue("RAW_FILE_MUTATED", "integrity", "처리 중 입력 파일 집합 또는 bytes가 변경됐습니다."))
    fingerprint = _fingerprint(config, sources, accepted, assignments)
    split_counts = {name: len(values) for name, values in splits.items()}
    result = PipelineResult(
        None,
        fingerprint,
        len(sources),
        len(raw_records),
        len(accepted),
        len(rejected),
        len(duplicates),
        split_counts,
    )
    if not publish:
        return result
    final_path = (repo / config.output_dir / config.dataset_id / config.dataset_version).resolve()
    created_at = utc_now()
    atomic = AtomicArtifactDirectory(final_path)
    with atomic as staging:
        accepted_dicts = [item.to_dict() for item in accepted]
        rejection_dicts = [item.to_dict() for item in sorted(rejected, key=lambda item: (item.source_path, item.source_record_id or "", item.stage, item.reason_code))]
        duplicate_dicts = [item.to_dict() for item in sorted(duplicates, key=lambda item: (item.duplicate_type, item.duplicate_record_id))]
        write_jsonl(staging / "records.jsonl", accepted_dicts)
        for name in ("train", "validation", "test"):
            write_jsonl(staging / f"{name}.jsonl", [item.to_dict() for item in splits[name]])
        write_jsonl(staging / "rejections.jsonl", rejection_dicts)
        write_jsonl(staging / "duplicates.jsonl", duplicate_dicts)
        statistics = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": config.dataset_id,
            "dataset_version": config.dataset_version,
            "source_count": len(sources),
            "input_record_count": len(raw_records),
            "accepted_record_count": len(accepted),
            "rejected_record_count": len(rejected),
            "duplicate_record_count": len(duplicates),
            "split_counts": split_counts,
            "character_count": sum(len(item.text_normalized) for item in accepted),
            "byte_count": sum(len(item.text_normalized.encode("utf-8")) for item in accepted),
            "empty_rejection_count": sum(item.reason_code == "EMPTY_TEXT" for item in rejected),
            "schema_rejection_count": sum(item.reason_code in {"UNKNOWN_FIELD", "MISSING_REQUIRED_FIELD", "INVALID_FIELD_TYPE", "DUPLICATE_RECORD_ID"} for item in rejected),
            "pii_rejection_count": 0,
            "license_rejection_count": 0,
            "approval_rejection_count": 0,
        }
        write_json(staging / "statistics.json", statistics)
        resolved_config = config.to_dict()
        write_yaml(staging / "resolved-data-config.yaml", {"data": resolved_config})
        resolved_checksum = checksum_value({"data": resolved_config})
        prelim = [
            artifact_entry(staging / "records.jsonl", "canonical_records", len(accepted)),
            artifact_entry(staging / "train.jsonl", "train_split", split_counts["train"]),
            artifact_entry(staging / "validation.jsonl", "validation_split", split_counts["validation"]),
            artifact_entry(staging / "test.jsonl", "test_split", split_counts["test"]),
            artifact_entry(staging / "rejections.jsonl", "rejections", len(rejected)),
            artifact_entry(staging / "duplicates.jsonl", "duplicates", len(duplicates)),
            artifact_entry(staging / "statistics.json", "statistics", 1),
            artifact_entry(staging / "resolved-data-config.yaml", "resolved_config", 1),
        ]
        steps = [
            {"step_name": "discovery", "step_version": "1", "input_count": len(config.input_paths), "output_count": len(sources), "rejected_count": 0},
            {"step_name": "read", "step_version": "1", "input_count": len(sources), "output_count": len(raw_records), "rejected_count": 0},
            {"step_name": "validate", "step_version": "1", "input_count": len(raw_records), "output_count": len(canonical), "rejected_count": len(rejected)},
            {"step_name": "normalize", "step_version": "1", "input_count": len(canonical), "output_count": len(canonical), "rejected_count": 0},
            {"step_name": "deduplicate", "step_version": "1", "input_count": len(canonical), "output_count": len(accepted), "rejected_count": len(duplicates)},
            {"step_name": "split", "step_version": "1", "input_count": len(accepted), "output_count": sum(split_counts.values()), "rejected_count": 0},
            {"step_name": "leakage_check", "step_version": "1", "input_count": len(accepted), "output_count": len(accepted), "rejected_count": 0},
            {"step_name": "artifact_write", "step_version": "1", "input_count": len(accepted), "output_count": 10, "rejected_count": 0},
        ]
        lineage = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": config.dataset_id,
            "dataset_version": config.dataset_version,
            "pipeline_version": PIPELINE_VERSION,
            "git_sha": _git_sha(repository_root()),
            "resolved_config_checksum": resolved_checksum,
            "input_artifacts": [{"relative_path": item.relative_path, "checksum": item.file_checksum} for item in sources],
            "output_artifacts": prelim,
            "processing_steps": steps,
            "dataset_fingerprint": fingerprint,
        }
        write_json(staging / "lineage.json", lineage)
        artifacts = sorted(prelim + [artifact_entry(staging / "lineage.json", "lineage", 1)], key=lambda item: item["relative_path"])
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": config.dataset_id,
            "dataset_version": config.dataset_version,
            "pipeline_version": PIPELINE_VERSION,
            "created_at": created_at,
            "git_sha": _git_sha(repository_root()),
            "source_count": len(sources),
            "record_count": len(raw_records),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "duplicate_count": len(duplicates),
            "split_counts": split_counts,
            "license_status": config.license_status,
            "approval_status": config.approval_status,
            "split_seed": config.split_seed,
            "normalization_version": NORMALIZATION_VERSION,
            "checksum_algorithm": "sha256",
            "dataset_fingerprint": fingerprint,
            "sources": _source_entries(sources, raw_counts, accepted, rejected, duplicates, config),
            "artifacts": artifacts,
        }
        if len(raw_records) != len(accepted) + len(rejected) + len(duplicates) or sum(split_counts.values()) != len(accepted):
            raise DataPipelineError(DataIssue("MANIFEST_MISMATCH", "artifact_write", "manifest count 불변식이 깨졌습니다."))
        for item in manifest["sources"]:
            if item["record_count"] != item["accepted_count"] + item["rejected_count"] + item["duplicate_count"]:
                raise DataPipelineError(DataIssue("MANIFEST_MISMATCH", "artifact_write", "source count 불변식이 깨졌습니다."))
        write_json(staging / "source-manifest.json", manifest)
        for item in artifacts:
            target = staging / item["relative_path"]
            if file_checksum(target) != item["checksum"]:
                raise DataPipelineError(DataIssue("CHECKSUM_MISMATCH", "artifact_write", f"artifact checksum 불일치: {item['relative_path']}"))
        for name, expected in (("records.jsonl", len(accepted)), ("train.jsonl", split_counts["train"]), ("validation.jsonl", split_counts["validation"]), ("test.jsonl", split_counts["test"])):
            if count_jsonl(staging / name) != expected:
                raise DataPipelineError(DataIssue("MANIFEST_MISMATCH", "artifact_write", f"line count 불일치: {name}"))
        atomic.publish()
    artifact_names = tuple(
        sorted(
            [
                "records.jsonl",
                "train.jsonl",
                "validation.jsonl",
                "test.jsonl",
                "source-manifest.json",
                "rejections.jsonl",
                "duplicates.jsonl",
                "statistics.json",
                "lineage.json",
                "resolved-data-config.yaml",
            ]
        )
    )
    return PipelineResult(
        final_path,
        fingerprint,
        len(sources),
        len(raw_records),
        len(accepted),
        len(rejected),
        len(duplicates),
        split_counts,
        artifact_names,
    )
