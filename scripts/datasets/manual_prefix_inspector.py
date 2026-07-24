"""ZIP entry 첫 component를 원문 비노출 통계로 비교하는 로컬 검사기."""

from __future__ import annotations

import os
import shutil
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .analyzer import AnalyzerConfig, DatasetEntry, inventory_dataset
from .manual_path_mapping import ManualMapping
from .safe_sampler import (
    SamplerError,
    _atomic_json,
    _canonical_fingerprint,
    _iter_archives,
    _sanitized_prefix_preview,
    _sha256_text,
)


PREFIX_REVIEW_CONTRACT_VERSION = "1.0"


def manual_prefix_output_root(config: AnalyzerConfig, requested: str | Path | None, repository_root: Path) -> Path:
    allowed_root = (config.external_root / "analysis" / "manual-prefix-review").resolve()
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
            raise SamplerError("prefix review 출력은 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("prefix review 출력은 external analysis/manual-prefix-review 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("prefix review 결과를 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _category_counts(value: str) -> dict[str, int]:
    return dict(sorted(Counter(unicodedata.category(char) for char in value).items()))


def _component_profile(component: str, entry_count: int, extensions: Counter[str]) -> dict[str, Any]:
    categories = _category_counts(component)
    punctuation = {key: count for key, count in categories.items() if key.startswith("P")}
    has_ascii = any(ord(char) < 128 and char.isalnum() for char in component)
    has_hangul = any("가" <= char <= "힣" or 0x1100 <= ord(char) <= 0x11FF for char in component)
    return {
        "first_component_hash": _sha256_text(component),
        "sanitized_preview": _sanitized_prefix_preview("/" + component + "/placeholder.json"),
        "entry_count": entry_count,
        "extension_distribution": dict(sorted(extensions.items())),
        "unicode_normalization": {
            "nfc_changes_original": unicodedata.normalize("NFC", component) != component,
            "nfd_changes_original": unicodedata.normalize("NFD", component) != component,
            "casefold_changes_original": component.casefold() != component,
        },
        "code_point_category_summary": categories,
        "punctuation_category_summary": punctuation,
        "whitespace_count": sum(char.isspace() for char in component),
        "has_whitespace": any(char.isspace() for char in component),
        "has_dash": any(unicodedata.category(char) == "Pd" or char == "-" for char in component),
        "has_underscore": "_" in component,
        "ascii_hangul_mixed": has_ascii and has_hangul,
        "code_point_count": len(component),
    }


def _category_delta(observed: str, candidate: str) -> dict[str, int]:
    left = Counter(unicodedata.category(char) for char in observed)
    right = Counter(unicodedata.category(char) for char in candidate)
    return {key: left[key] - right[key] for key in sorted(set(left) | set(right)) if left[key] != right[key]}


def _candidate_comparisons(component: str, profile: dict[str, Any], mapping: ManualMapping) -> list[dict[str, Any]]:
    rows = []
    for rule in mapping.rules:
        if profile["sanitized_preview"] != rule.sanitized_source_prefix:
            continue
        candidate = rule.source_prefix.strip("/")
        rows.append({
            "mapping_rule_id": rule.rule_id,
            "source_prefix_hash": rule.source_prefix_hash,
            "observed_component_hash": profile["first_component_hash"],
            "sanitized_preview": profile["sanitized_preview"],
            "exact_match": component == candidate,
            "nfc_match": unicodedata.normalize("NFC", component) == unicodedata.normalize("NFC", candidate),
            "nfd_match": unicodedata.normalize("NFD", component) == unicodedata.normalize("NFD", candidate),
            "casefold_match": component.casefold() == candidate.casefold(),
            "code_point_count_delta": len(component) - len(candidate),
            "whitespace_count_delta": sum(char.isspace() for char in component) - sum(
                char.isspace() for char in candidate
            ),
            "code_point_category_delta": _category_delta(component, candidate),
        })
    return rows


def inspect_manual_prefixes(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    *,
    requested_archive: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    if not dry_run:
        raise SamplerError("prefix review는 --dry-run 읽기 전용 모드만 지원합니다.")
    if mapping.dataset_id != entry.dataset_id:
        raise SamplerError("mapping dataset_id가 prefix review 대상과 일치하지 않습니다.")
    before = inventory_dataset(entry)
    archives = _iter_archives(entry, requested_archive)
    counts: Counter[str] = Counter()
    extensions: dict[str, Counter[str]] = defaultdict(Counter)
    archives_corrupted = 0
    for archive_path in archives:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    normalized = info.filename.replace("\\", "/").lstrip("/")
                    parts = [part for part in normalized.split("/") if part]
                    if not parts:
                        continue
                    component = parts[0]
                    counts[component] += 1
                    extension = PurePosixPath(normalized).suffix.lower() or "[none]"
                    extensions[component][extension] += 1
        except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
            archives_corrupted += 1
    profiles = []
    comparisons = []
    for component in sorted(counts, key=lambda value: _sha256_text(value)):
        profile = _component_profile(component, counts[component], extensions[component])
        profiles.append(profile)
        comparisons.extend(_candidate_comparisons(component, profile, mapping))
    fingerprint = _canonical_fingerprint({
        "contract_version": PREFIX_REVIEW_CONTRACT_VERSION,
        "dataset_id": entry.dataset_id,
        "mapping_file_fingerprint": mapping.fingerprint,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "groups": [[row["first_component_hash"], row["entry_count"]] for row in profiles],
    })
    run_id = "prefix-review-dry-" + fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 prefix review 결과가 이미 존재하여 덮어쓰지 않습니다.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        after = inventory_dataset(entry)
        if before["inventory_metadata_digest"] != after["inventory_metadata_digest"]:
            raise SamplerError("prefix review 중 원본 metadata 변경이 탐지됐습니다.")
        report = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "status": "manual_prefix_review_complete",
            "dry_run": True,
            "source_root": "configured_external_root",
            "output_root": "configured_external_analysis_manual_prefix_review",
            "mapping_file_fingerprint": mapping.fingerprint,
            "archives_scanned": len(archives),
            "archives_corrupted": archives_corrupted,
            "entries_grouped": sum(counts.values()),
            "prefix_group_count": len(profiles),
            "prefix_groups": profiles,
            "mapping_candidate_comparisons": comparisons,
            "original_component_values_recorded": False,
            "source_mutation_detected": False,
            "run_fingerprint": fingerprint,
            "created_at": datetime.now(UTC).isoformat(),
        }
        _atomic_json(staging / "prefix-summary.json", report)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "success": True,
        "dataset_id": entry.dataset_id,
        "run_id": run_id,
        "run_status": report["status"],
        "entries_grouped": report["entries_grouped"],
        "prefix_group_count": report["prefix_group_count"],
        "source_mutation_detected": False,
        "output_location": "external_analysis_manual_prefix_review_root",
    }
