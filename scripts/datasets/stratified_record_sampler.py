"""Archive·entry·bounded record 구간을 분산한 비노출 schema review sampler."""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from .analyzer import AnalyzerConfig, DatasetEntry, inventory_dataset
from .json_record_stream import RECORD_OK, RecordEvent, scan_json_array_records
from .large_json_inspector import DEFAULT_LARGE_THRESHOLD_BYTES, LargeJsonCandidate, _large_candidates
from .manual_path_mapping import DEFAULT_MANUAL_SEED, ManualMapping
from .safe_sampler import SamplerError, _atomic_json, _canonical_fingerprint, _iter_archives, _sha256_file, _sha256_text
from .schema_review_bundle import analyze_review_record, build_schema_review_bundle, validate_preview_request


STRATIFIED_REVIEW_CONTRACT_VERSION = "1.1"
DEFAULT_MAX_ARCHIVES = 5
DEFAULT_MAX_ENTRIES_PER_ARCHIVE = 2
DEFAULT_RECORDS_PER_ENTRY = 5
DEFAULT_MAX_RECORD_BYTES = 1024 * 1024
DEFAULT_MAX_READ_BYTES_PER_ENTRY = 32 * 1024 * 1024
DEFAULT_MAX_TOTAL_READ_BYTES = 128 * 1024 * 1024
DEFAULT_SELECTION_SEED = "dohalm-stratified-record-review-v1"

SIZE_40_MIB = 40 * 1024 * 1024
SIZE_50_MIB = 50 * 1024 * 1024
RECORD_STRATA = ("early", "middle", "late")


def schema_review_output_root(
    config: AnalyzerConfig,
    requested: str | Path | None,
    repository_root: Path,
) -> Path:
    allowed_root = (config.external_root / "analysis" / "schema-review").resolve()
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
            raise SamplerError("schema review 출력은 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("schema review 출력은 external analysis/schema-review 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("schema review 결과를 Git 저장소 안에 기록할 수 없습니다.")
    return output


def size_bucket(byte_size: int) -> str:
    if byte_size < SIZE_40_MIB:
        return "under_40_mib"
    if byte_size < SIZE_50_MIB:
        return "40_to_50_mib"
    return "50_mib_or_more"


def compressed_ratio_bucket(info: zipfile.ZipInfo) -> str:
    if info.file_size <= 0:
        return "empty"
    ratio = info.compress_size / info.file_size
    if ratio < 0.25:
        return "under_0_25"
    if ratio < 0.50:
        return "0_25_to_0_50"
    return "0_50_or_more"


def _entry_rank(dataset_id: str, candidate: LargeJsonCandidate, seed: str) -> str:
    archive_hash = _sha256_text(candidate.archive_relative_path)
    payload = "\n".join((
        seed,
        dataset_id,
        archive_hash,
        candidate.entry_name_hash,
        size_bucket(candidate.info.file_size),
        candidate.rule.rule_id,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_stratified_entries(
    dataset_id: str,
    candidates: Iterable[LargeJsonCandidate],
    *,
    max_archives: int,
    max_entries_per_archive: int,
    selection_seed: str,
) -> list[LargeJsonCandidate]:
    if max_archives <= 0 or max_entries_per_archive <= 0:
        raise SamplerError("archive와 entry 선택 상한은 0보다 커야 합니다.")
    grouped: dict[str, list[LargeJsonCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[_sha256_text(candidate.archive_relative_path)].append(candidate)

    archive_rows = []
    for archive_hash, rows in grouped.items():
        ranked = sorted(rows, key=lambda item: (_entry_rank(dataset_id, item, selection_seed), item.entry_name_hash))
        archive_rank = hashlib.sha256(
            "\n".join((selection_seed, dataset_id, archive_hash, ranked[0].selection_rank)).encode("utf-8")
        ).hexdigest()
        archive_rows.append((archive_rank, archive_hash, ranked))
    archive_rows.sort(key=lambda row: (row[0], row[1]))

    selected: list[LargeJsonCandidate] = []
    for _, _, rows in archive_rows[:max_archives]:
        by_bucket: dict[str, list[LargeJsonCandidate]] = defaultdict(list)
        for candidate in rows:
            by_bucket[size_bucket(candidate.info.file_size)].append(candidate)
        for bucket_rows in by_bucket.values():
            bucket_rows.sort(key=lambda item: (_entry_rank(dataset_id, item, selection_seed), item.entry_name_hash))
        archive_selected: list[LargeJsonCandidate] = []
        for bucket in sorted(by_bucket):
            if len(archive_selected) >= max_entries_per_archive:
                break
            archive_selected.append(by_bucket[bucket].pop(0))
        remaining = sorted(
            (item for bucket_rows in by_bucket.values() for item in bucket_rows),
            key=lambda item: (_entry_rank(dataset_id, item, selection_seed), item.entry_name_hash),
        )
        archive_selected.extend(remaining[: max_entries_per_archive - len(archive_selected)])
        selected.extend(archive_selected)
    return selected


def record_stratum(record_index: int, records_seen: int) -> str:
    if records_seen <= 0:
        raise ValueError("records_seen은 0보다 커야 합니다.")
    position = min(2, (record_index * 3) // records_seen)
    return RECORD_STRATA[position]


def _record_rank(
    dataset_id: str,
    archive_hash: str,
    entry_hash: str,
    record_index: int,
    stratum: str,
    seed: str,
) -> str:
    payload = "\n".join((seed, dataset_id, archive_hash, entry_hash, str(record_index), stratum))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_stratified_records(
    records: Iterable[dict[str, Any]],
    *,
    records_seen: int,
    records_per_entry: int,
    dataset_id: str,
    archive_hash: str,
    entry_hash: str,
    selection_seed: str,
) -> list[dict[str, Any]]:
    if records_per_entry <= 0:
        raise SamplerError("records-per-entry는 0보다 커야 합니다.")
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in RECORD_STRATA}
    for row in records:
        stratum = record_stratum(row["record_index"], records_seen)
        ranked = {
            **row,
            "record_stratum": stratum,
            "selection_rank": _record_rank(
                dataset_id, archive_hash, entry_hash, row["record_index"], stratum, selection_seed,
            ),
        }
        grouped[stratum].append(ranked)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["selection_rank"], row["record_index"]))

    base, remainder = divmod(records_per_entry, len(RECORD_STRATA))
    quotas = {
        name: base + int(index < remainder)
        for index, name in enumerate(RECORD_STRATA)
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for name in RECORD_STRATA:
        for row in grouped[name][: quotas[name]]:
            selected.append(row)
            selected_ids.add(row["record_index"])
    if len(selected) < records_per_entry:
        remaining_rows = sorted(
            (row for rows in grouped.values() for row in rows if row["record_index"] not in selected_ids),
            key=lambda row: (row["selection_rank"], row["record_index"]),
        )
        selected.extend(remaining_rows[: records_per_entry - len(selected)])
    return sorted(selected, key=lambda row: (RECORD_STRATA.index(row["record_stratum"]), row["selection_rank"]))


def _inspect_entry(
    entry: DatasetEntry,
    candidate: LargeJsonCandidate,
    *,
    records_per_entry: int,
    max_record_bytes: int,
    max_read_bytes: int,
    selection_seed: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], Counter[str]]:
    archive_hash = _sha256_text(candidate.archive_relative_path)
    parsed_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()

    def on_record(event: RecordEvent) -> None:
        if event.status != RECORD_OK:
            rejection_counts[event.status] += 1
            return
        analysis = analyze_review_record(event.value)
        parsed_rows.append({
            "archive_relative_path_hash": archive_hash,
            "entry_name_hash": candidate.entry_name_hash,
            "mapping_rule_id": candidate.rule.rule_id,
            "entry_size_bucket": size_bucket(candidate.info.file_size),
            "compressed_ratio_bucket": compressed_ratio_bucket(candidate.info),
            "record_index": event.record_index,
            "record_byte_size": event.byte_size,
            "record_checksum": event.checksum,
            **analysis,
        })

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
        raise SamplerError("층화 대상으로 선택한 ZIP JSON entry를 제한 범위에서 검사할 수 없습니다.") from exc

    selected = select_stratified_records(
        parsed_rows,
        records_seen=scan.records_seen,
        records_per_entry=records_per_entry,
        dataset_id=entry.dataset_id,
        archive_hash=archive_hash,
        entry_hash=candidate.entry_name_hash,
        selection_seed=selection_seed,
    ) if scan.records_seen else []
    rejection_counts.update({scan.status: 1}) if scan.status != RECORD_OK else None
    summary = {
        "archive_relative_path_hash": archive_hash,
        "entry_name_hash": candidate.entry_name_hash,
        "mapping_rule_id": candidate.rule.rule_id,
        "entry_size_bucket": size_bucket(candidate.info.file_size),
        "compressed_ratio_bucket": compressed_ratio_bucket(candidate.info),
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "scan_status": scan.status,
        "bytes_read": scan.bytes_read,
        "records_seen": scan.records_seen,
        "records_parsed": scan.records_parsed,
        "records_selected": len(selected),
        "records_rejected": scan.records_rejected,
        "record_strata_counts": dict(sorted(Counter(row["record_stratum"] for row in selected).items())),
        "bounded_range_only": True,
    }
    return summary, selected, rejection_counts


def _planned_entry(candidate: LargeJsonCandidate) -> dict[str, Any]:
    return {
        "archive_relative_path_hash": _sha256_text(candidate.archive_relative_path),
        "entry_name_hash": candidate.entry_name_hash,
        "mapping_rule_id": candidate.rule.rule_id,
        "entry_size_bucket": size_bucket(candidate.info.file_size),
        "compressed_ratio_bucket": compressed_ratio_bucket(candidate.info),
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "scan_status": "DRY_RUN_PLANNED",
        "bytes_read": 0,
        "records_seen": 0,
        "records_parsed": 0,
        "records_selected": 0,
        "records_rejected": 0,
        "record_strata_counts": {},
        "bounded_range_only": True,
    }


def _archive_checksums(candidates: Iterable[LargeJsonCandidate]) -> dict[str, str]:
    unique: dict[str, Path] = {}
    for candidate in candidates:
        unique.setdefault(_sha256_text(candidate.archive_relative_path), candidate.archive_path)
    return {archive_hash: _sha256_file(path) for archive_hash, path in sorted(unique.items())}


def review_stratified_records(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    *,
    max_archives: int,
    max_entries_per_archive: int,
    records_per_entry: int,
    max_record_bytes: int,
    max_read_bytes_per_entry: int,
    max_total_read_bytes: int,
    selection_seed: str,
    dry_run: bool,
    preview_requested: bool = False,
) -> dict[str, Any]:
    validate_preview_request(requested=preview_requested)
    if min(
        max_archives, max_entries_per_archive, records_per_entry, max_record_bytes,
        max_read_bytes_per_entry, max_total_read_bytes,
    ) <= 0:
        raise SamplerError("archive, entry, record와 byte 제한은 0보다 커야 합니다.")
    if mapping.dataset_id != entry.dataset_id:
        raise SamplerError("mapping dataset_id가 schema review 대상과 일치하지 않습니다.")

    before = inventory_dataset(entry)
    archives = _iter_archives(entry, None)
    candidates = _large_candidates(
        entry, mapping, archives, threshold_bytes=DEFAULT_LARGE_THRESHOLD_BYTES, seed=DEFAULT_MANUAL_SEED,
    )
    selected_entries = select_stratified_entries(
        entry.dataset_id,
        candidates,
        max_archives=max_archives,
        max_entries_per_archive=max_entries_per_archive,
        selection_seed=selection_seed,
    )
    mode = "dry-run" if dry_run else "inspection"
    limits = {
        "max_archives": max_archives,
        "max_entries_per_archive": max_entries_per_archive,
        "records_per_entry": records_per_entry,
        "max_record_bytes": max_record_bytes,
        "max_read_bytes_per_entry": max_read_bytes_per_entry,
        "max_total_read_bytes": max_total_read_bytes,
    }
    fingerprint = _canonical_fingerprint({
        "contract_version": STRATIFIED_REVIEW_CONTRACT_VERSION,
        "mode": mode,
        "dataset_id": entry.dataset_id,
        "mapping_fingerprint": mapping.fingerprint,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "selection_seed": selection_seed,
        "limits": limits,
        "selected_entries": [
            [_sha256_text(item.archive_relative_path), item.entry_name_hash, size_bucket(item.info.file_size)]
            for item in selected_entries
        ],
    })
    run_id = f"schema-review-{'dry' if dry_run else 'inspect'}-" + fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 schema review 결과가 이미 존재하여 덮어쓰지 않습니다.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()

    try:
        pre_checksums = {} if dry_run else _archive_checksums(selected_entries)
        entry_rows: list[dict[str, Any]] = []
        selected_records: list[dict[str, Any]] = []
        rejection_counts: Counter[str] = Counter()
        total_read = 0
        total_limit_reached = False
        if dry_run:
            entry_rows = [_planned_entry(candidate) for candidate in selected_entries]
        else:
            for candidate in selected_entries:
                remaining = max_total_read_bytes - total_read
                if remaining <= 0:
                    total_limit_reached = True
                    break
                entry_limit = min(max_read_bytes_per_entry, remaining)
                summary, records, rejected = _inspect_entry(
                    entry,
                    candidate,
                    records_per_entry=records_per_entry,
                    max_record_bytes=max_record_bytes,
                    max_read_bytes=entry_limit,
                    selection_seed=selection_seed,
                )
                if entry_limit < max_read_bytes_per_entry and summary["scan_status"] != RECORD_OK:
                    summary["scan_status"] = "TOTAL_READ_LIMIT_REACHED"
                    total_limit_reached = True
                total_read += summary["bytes_read"]
                entry_rows.append(summary)
                selected_records.extend(records)
                rejection_counts.update(rejected)
                if total_read >= max_total_read_bytes:
                    total_limit_reached = True
                    break

        after = inventory_dataset(entry)
        post_checksums = {} if dry_run else _archive_checksums(selected_entries)
        source_mutation = (
            before["inventory_metadata_digest"] != after["inventory_metadata_digest"]
            or pre_checksums != post_checksums
        )
        if source_mutation:
            raise SamplerError("schema review 중 원본 ZIP 변경이 탐지됐습니다.")

        bundle = build_schema_review_bundle(selected_records)
        archive_counts = Counter(row["archive_relative_path_hash"] for row in entry_rows)
        size_counts = Counter(row["entry_size_bucket"] for row in entry_rows)
        ratio_counts = Counter(row["compressed_ratio_bucket"] for row in entry_rows)
        record_strata_counts = Counter(row["record_stratum"] for row in selected_records)
        strata_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "strategy": "archive_stratified_prefix_scan_and_bounded_record_index_stratification",
            "random_seek_performed": False,
            "bounded_range_only": True,
            "selected_archive_count": len({_sha256_text(item.archive_relative_path) for item in selected_entries}),
            "selected_entry_count": len(selected_entries),
            "inspected_entry_count": 0 if dry_run else len(entry_rows),
            "archive_entry_counts": dict(sorted(archive_counts.items())),
            "entry_size_bucket_counts": dict(sorted(size_counts.items())),
            "compressed_ratio_bucket_counts": dict(sorted(ratio_counts.items())),
            "record_strata_counts": dict(sorted(record_strata_counts.items())),
            "entries": entry_rows,
            "selected_records": [
                {
                    "archive_relative_path_hash": row["archive_relative_path_hash"],
                    "entry_name_hash": row["entry_name_hash"],
                    "record_index": row["record_index"],
                    "record_stratum": row["record_stratum"],
                    "selection_rank": row["selection_rank"],
                    "schema_signature_hash": row["schema_signature"],
                }
                for row in selected_records
            ],
        }
        run_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "status": "dry_run_planned" if dry_run else "inspection_complete",
            "mapping_fingerprint": mapping.fingerprint,
            "selection_seed": selection_seed,
            "limits": limits,
            "candidate_entry_count": len(candidates),
            "entries_selected": len(selected_entries),
            "entries_inspected": 0 if dry_run else len(entry_rows),
            "records_seen": sum(row["records_seen"] for row in entry_rows),
            "records_parsed": sum(row["records_parsed"] for row in entry_rows),
            "records_selected": len(selected_records),
            "records_rejected": sum(row["records_rejected"] for row in entry_rows),
            "rejection_status_counts": dict(sorted(rejection_counts.items())),
            "total_bytes_read": total_read,
            "total_read_limit_reached": total_limit_reached,
            "full_entry_extraction_performed": False,
            "full_json_parse_performed": False,
            "record_content_saved": False,
            "preview_enabled": False,
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
            "run_fingerprint": fingerprint,
        }
        _atomic_json(staging / "run-summary.json", run_summary)
        _atomic_json(staging / "strata-summary.json", strata_summary)
        _atomic_json(staging / "schema-signatures.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id,
            "schema_confirmed": False, "signatures": bundle["schema_signatures"],
        })
        _atomic_json(staging / "field-review-manifest.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id,
            "selected_record_count": bundle["selected_record_count"],
            "fields": bundle["field_review_manifest"],
        })
        _atomic_json(staging / "pii-review-checklist.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id,
            "automatic_pii_decision": False,
            "no_field_name_signal_does_not_mean_pii_absent": True,
            "checks": bundle["pii_review_checklist"],
        })
        _atomic_json(staging / "manual-review-required.json", {
            "schema_version": "1.0", "dataset_id": entry.dataset_id, "run_id": run_id,
            "schema_confirmed": False,
            "pii_absence_confirmed": False,
            "text_quality_confirmed": False,
            "tokenizer_corpus_approved": False,
            "preview": {
                "enabled": False,
                "implementation_status": "blocked_not_implemented",
                "separate_user_approval_required": True,
            },
        })
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
        "archives_selected": strata_summary["selected_archive_count"],
        "entries_selected": len(selected_entries),
        "entries_inspected": run_summary["entries_inspected"],
        "records_seen": run_summary["records_seen"],
        "records_parsed": run_summary["records_parsed"],
        "records_selected": run_summary["records_selected"],
        "total_bytes_read": total_read,
        "source_mutation_detected": False,
        "output_location": "external_analysis_schema_review_root",
    }
