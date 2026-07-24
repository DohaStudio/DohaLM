"""승인된 절대 ZIP entry prefix만 상대 경로로 치환하는 수동 표본 모드."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from src.config.loader import load_yaml

from .analyzer import AnalyzerConfig, DatasetEntry, inventory_dataset
from .safe_sampler import (
    DEFAULT_EXTENSIONS,
    MAX_ENTRY_PATH_LENGTH,
    MAX_REJECTION_RECORDS,
    SUPPORTED_ZIP_COMPRESSION,
    SamplerError,
    _archive_id,
    _atomic_json,
    _canonical_fingerprint,
    _entry_extension,
    _extract_candidate,
    _is_within,
    _iter_archives,
    _rejection,
    _sanitized_prefix_preview,
    _sha256_text,
    build_schema_summary,
    validate_entry,
)


MAPPING_SCHEMA_VERSION = "1.0"
MANUAL_MAPPING_CONTRACT_VERSION = "1.1"
DEFAULT_MANUAL_SEED = "dohalm-manual-path-mapping-v1"


@dataclass(frozen=True)
class MappingRule:
    rule_id: str
    source_prefix: str
    target_prefix: str
    allowed_extensions: frozenset[str]

    @property
    def sanitized_source_prefix(self) -> str:
        return _sanitized_prefix_preview(self.source_prefix)

    @property
    def source_prefix_hash(self) -> str:
        return _sha256_text(self.source_prefix)


@dataclass(frozen=True)
class MappingApproval:
    status: str
    approved_by: str
    approved_at: str


@dataclass(frozen=True)
class ManualMapping:
    dataset_id: str
    approval: MappingApproval
    rules: tuple[MappingRule, ...]
    fingerprint: str


@dataclass(frozen=True)
class ManualCandidate:
    archive_path: Path
    archive_relative_path: str
    archive_id: str
    info: zipfile.ZipInfo
    entry_relative_path: str
    output_relative_path: str
    selection_rank: str
    original_entry_hash: str
    rule_id: str
    sanitized_source_prefix: str


def _normalize_extension(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SamplerError("mapping allowed_extensions는 비어 있지 않은 문자열이어야 합니다.")
    normalized = value.strip().lower()
    if not normalized.startswith("."):
        normalized = "." + normalized
    if normalized not in DEFAULT_EXTENSIONS:
        raise SamplerError("mapping allowed_extensions에는 지원되는 text 형식만 사용할 수 있습니다.")
    return normalized


def _primitive_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise SamplerError("approved_at은 비어 있지 않은 문자열 또는 YAML 날짜여야 합니다.")


def _validate_source_prefix(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise SamplerError("source_prefix는 /로 시작해야 합니다.")
    if value.startswith("//") or "\\" in value or "\x00" in value:
        raise SamplerError("source_prefix에는 UNC, 역슬래시 또는 NUL을 사용할 수 없습니다.")
    if len(value) > MAX_ENTRY_PATH_LENGTH:
        raise SamplerError("source_prefix가 허용 길이를 초과합니다.")
    path = PurePosixPath(value)
    if any(part in {".", ".."} for part in path.parts):
        raise SamplerError("source_prefix에는 현재·상위 경로 요소를 사용할 수 없습니다.")
    if not value.endswith("/"):
        raise SamplerError("source_prefix는 경계가 명확하도록 /로 끝나야 합니다.")
    return value


def _validate_target_prefix(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise SamplerError("target_prefix는 비어 있지 않은 상대경로여야 합니다.")
    if "\x00" in value or "\\" in value:
        raise SamplerError("target_prefix에는 NUL 또는 역슬래시를 사용할 수 없습니다.")
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise SamplerError("target_prefix에는 absolute, drive 또는 UNC 경로를 사용할 수 없습니다.")
    path = PurePosixPath(value)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SamplerError("target_prefix에는 빈 요소, . 또는 ..를 사용할 수 없습니다.")
    normalized = path.as_posix().rstrip("/") + "/"
    if len(normalized) > MAX_ENTRY_PATH_LENGTH:
        raise SamplerError("target_prefix가 허용 길이를 초과합니다.")
    return normalized


def _prefixes_overlap(first: str, second: str) -> bool:
    return first.startswith(second) or second.startswith(first)


def load_manual_mapping(path: str | Path, expected_dataset_id: str) -> ManualMapping:
    raw = load_yaml(path)
    if set(raw) != {"schema_version", "dataset_id", "approval", "rules"}:
        raise SamplerError("mapping 최상위에는 schema_version, dataset_id, approval, rules만 있어야 합니다.")
    if not isinstance(raw["schema_version"], str) or raw["schema_version"] != MAPPING_SCHEMA_VERSION:
        raise SamplerError("지원하지 않는 mapping schema_version입니다.")
    if raw["dataset_id"] != expected_dataset_id:
        raise SamplerError("mapping dataset_id가 CLI dataset과 일치하지 않습니다.")

    approval_raw = raw["approval"]
    if not isinstance(approval_raw, dict) or set(approval_raw) != {"status", "approved_by", "approved_at"}:
        raise SamplerError("mapping approval에는 status, approved_by, approved_at만 있어야 합니다.")
    if approval_raw["status"] != "approved":
        raise SamplerError("사용자가 approved로 승인한 mapping만 실행할 수 있습니다.")
    approved_by = approval_raw["approved_by"]
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise SamplerError("approved mapping에는 approved_by가 필요합니다.")
    approval = MappingApproval("approved", approved_by.strip(), _primitive_timestamp(approval_raw["approved_at"]))

    rules_raw = raw["rules"]
    if not isinstance(rules_raw, list) or not rules_raw:
        raise SamplerError("mapping rules는 비어 있지 않은 목록이어야 합니다.")
    rules: list[MappingRule] = []
    source_prefixes: list[str] = []
    target_prefixes: list[str] = []
    canonical_rules: list[dict[str, Any]] = []
    for item in rules_raw:
        if not isinstance(item, dict) or set(item) != {"source_prefix", "target_prefix", "allowed_extensions"}:
            raise SamplerError("각 mapping rule에는 source_prefix, target_prefix, allowed_extensions만 있어야 합니다.")
        source = _validate_source_prefix(item["source_prefix"])
        target = _validate_target_prefix(item["target_prefix"])
        extensions_raw = item["allowed_extensions"]
        if not isinstance(extensions_raw, list) or not extensions_raw:
            raise SamplerError("mapping allowed_extensions는 비어 있지 않은 목록이어야 합니다.")
        extensions = frozenset(_normalize_extension(value) for value in extensions_raw)
        if source in source_prefixes:
            raise SamplerError("source_prefix는 중복될 수 없습니다.")
        if any(_prefixes_overlap(source, existing) for existing in source_prefixes):
            raise SamplerError("서로 겹치는 source_prefix는 모호하므로 허용하지 않습니다.")
        if any(_prefixes_overlap(target, existing) for existing in target_prefixes):
            raise SamplerError("target_prefix는 동일하거나 서로 포함되도록 충돌할 수 없습니다.")
        canonical = {
            "source_prefix": source,
            "target_prefix": target,
            "allowed_extensions": sorted(extensions),
        }
        rule_id = "rule-" + _canonical_fingerprint(canonical).removeprefix("sha256:")[:12]
        rules.append(MappingRule(rule_id, source, target, extensions))
        source_prefixes.append(source)
        target_prefixes.append(target)
        canonical_rules.append(canonical)

    fingerprint_payload = {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "dataset_id": expected_dataset_id,
        "approval": {
            "status": approval.status,
            "approved_by": approval.approved_by,
            "approved_at": approval.approved_at,
        },
        "rules": canonical_rules,
    }
    return ManualMapping(
        dataset_id=expected_dataset_id,
        approval=approval,
        rules=tuple(rules),
        fingerprint=_canonical_fingerprint(fingerprint_payload),
    )


def manual_sample_output_root(
    config: AnalyzerConfig,
    requested: str | Path | None,
    repository_root: Path,
) -> Path:
    allowed_root = (config.external_root / "analysis" / "manual-samples").resolve()
    if requested is None:
        output = allowed_root
    else:
        raw = str(requested)
        if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            output = Path(raw).resolve()
        else:
            output = (config.external_root / Path(raw)).resolve()
    for dataset in config.entries.values():
        root = dataset.root.resolve()
        if output == root or root in output.parents or output in root.parents:
            raise SamplerError("수동 표본 출력 경로는 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("수동 mapping 출력은 configured external root의 analysis/manual-samples 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("수동 표본을 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _matching_rule(name: str, mapping: ManualMapping) -> MappingRule | None:
    matches = [rule for rule in mapping.rules if name.startswith(rule.source_prefix)]
    if len(matches) > 1:
        raise SamplerError("entry가 둘 이상의 mapping rule과 일치합니다.")
    return matches[0] if matches else None


def _map_entry_path(name: str, rule: MappingRule) -> str:
    remainder = name[len(rule.source_prefix) :]
    if not remainder:
        raise SamplerError("mapping source_prefix 자체는 파일 entry가 될 수 없습니다.")
    return PurePosixPath(rule.target_prefix, remainder).as_posix()


def _manual_rank(
    dataset_id: str,
    archive_relative_path: str,
    original_entry_hash: str,
    rule_id: str,
    seed: str,
) -> str:
    payload = "\n".join((seed, dataset_id, archive_relative_path, original_entry_hash, rule_id))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manual_rejection(
    archive_relative_path: str,
    info: zipfile.ZipInfo | None,
    reason_code: str,
    reason_message: str,
    *,
    rule: MappingRule | None,
    mapping_matched: bool,
    rejection_stage: str,
) -> dict[str, Any]:
    row = _rejection(archive_relative_path, info, reason_code, reason_message)
    row.pop("entry_relative_path", None)
    row.update({
        "mapping_rule_id": rule.rule_id if rule else None,
        "source_prefix_hash": rule.source_prefix_hash if rule else None,
        "sanitized_source_prefix": rule.sanitized_source_prefix if rule else None,
        "mapping_matched": mapping_matched,
        "post_mapping_rejection": bool(mapping_matched and rejection_stage != "mapping_lookup"),
        "rejection_stage": rejection_stage,
    })
    return row


def _stage_for_reason(reason_code: str) -> str:
    if reason_code == "MAPPING_RULE_NOT_FOUND":
        return "mapping_lookup"
    if reason_code in {
        "ABSOLUTE_ENTRY_PATH", "WINDOWS_DRIVE_PATH", "UNC_PATH", "PATH_TRAVERSAL",
        "NUL_IN_ENTRY_NAME", "EMPTY_ENTRY_NAME", "ENTRY_PATH_TOO_LONG", "MAPPING_EMPTY_REMAINDER",
    }:
        return "mapping_validation"
    if reason_code == "ENTRY_TOO_LARGE":
        return "size_validation"
    if reason_code == "UNSUPPORTED_EXTENSION":
        return "extension_validation"
    if reason_code in {"OUTPUT_ESCAPE", "DUPLICATE_OUTPUT_PATH"}:
        return "output_validation"
    if reason_code == "TOTAL_LIMIT_EXCEEDED":
        return "selection"
    return "entry_validation"


def _new_rule_statistics(mapping: ManualMapping) -> dict[str, Counter[str]]:
    return {rule.rule_id: Counter() for rule in mapping.rules}


def _rule_statistics_rows(mapping: ManualMapping, statistics: Mapping[str, Counter[str]]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": rule.rule_id,
            "source_prefix_hash": rule.source_prefix_hash,
            "sanitized_source_prefix": rule.sanitized_source_prefix,
            "matched_entries": statistics[rule.rule_id]["matched_entries"],
            "safe_entries": statistics[rule.rule_id]["safe_entries"],
            "rejected_entries": statistics[rule.rule_id]["rejected_entries"],
            "entry_too_large": statistics[rule.rule_id]["entry_too_large"],
            "unsupported_extension": statistics[rule.rule_id]["unsupported_extension"],
            "path_validation_failed": statistics[rule.rule_id]["path_validation_failed"],
            "selected_entries": statistics[rule.rule_id]["selected_entries"],
        }
        for rule in mapping.rules
    ]


def _scan_mapped_archives(
    entry: DatasetEntry,
    archives: Iterable[Path],
    mapping: ManualMapping,
    *,
    allowed_extensions: frozenset[str],
    max_file_bytes: int,
    selection_seed: str,
) -> tuple[
    list[ManualCandidate],
    list[dict[str, Any]],
    dict[str, int],
    dict[str, Counter[str]],
    Counter[str],
    Counter[str],
]:
    candidates: list[ManualCandidate] = []
    rejections: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    rule_statistics = _new_rule_statistics(mapping)
    unmatched_extensions: Counter[str] = Counter()
    unmatched_prefix_groups: Counter[str] = Counter()
    output_paths: set[str] = set()

    for archive_path in archives:
        counters["archives_scanned"] += 1
        archive_relative = archive_path.relative_to(entry.root).as_posix()
        archive_id = _archive_id(archive_relative)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    counters["entries_scanned"] += 1
                    reason_code: str | None = None
                    reason_message: str | None = None
                    rule = _matching_rule(info.filename, mapping)
                    mapping_matched = rule is not None
                    if rule is not None:
                        rule_statistics[rule.rule_id]["matched_entries"] += 1
                    if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
                        reason_code = "UNSUPPORTED_ARCHIVE"
                        reason_message = "지원하지 않는 ZIP 압축 방식입니다."
                    elif not info.filename.startswith("/"):
                        reason_code = "MAPPING_RULE_NOT_FOUND"
                        reason_message = "수동 mapping은 승인된 선행 / prefix에만 적용됩니다."
                    elif info.filename.startswith("//"):
                        reason_code = "UNC_PATH"
                        reason_message = "UNC 형태 entry 경로는 mapping할 수 없습니다."
                    elif "\x00" in info.filename:
                        reason_code = "NUL_IN_ENTRY_NAME"
                        reason_message = "entry 이름에 NUL이 포함돼 있습니다."
                    elif len(info.filename) > MAX_ENTRY_PATH_LENGTH:
                        reason_code = "ENTRY_PATH_TOO_LONG"
                        reason_message = "entry 경로가 허용 길이를 초과합니다."
                    elif any(part == ".." for part in PurePosixPath(info.filename).parts):
                        reason_code = "PATH_TRAVERSAL"
                        reason_message = "상위 경로 이동 요소는 mapping할 수 없습니다."

                    if reason_code is None and rule is None:
                        reason_code = "MAPPING_RULE_NOT_FOUND"
                        reason_message = "entry에 명시적으로 승인된 mapping rule이 없습니다."

                    mapped_path: str | None = None
                    if reason_code is None and rule is not None:
                        try:
                            mapped_path = _map_entry_path(info.filename, rule)
                        except SamplerError as exc:
                            reason_code = "MAPPING_EMPTY_REMAINDER"
                            reason_message = str(exc)

                    if reason_code is None and rule is not None and mapped_path is not None:
                        mapped_info = copy.copy(info)
                        mapped_info.filename = mapped_path
                        effective_extensions = allowed_extensions.intersection(rule.allowed_extensions)
                        decision = validate_entry(
                            mapped_info,
                            Path("/") / "isolated" / archive_id,
                            allowed_extensions=frozenset(effective_extensions),
                            max_file_bytes=max_file_bytes,
                        )
                        if decision.reason_code:
                            reason_code = decision.reason_code
                            reason_message = decision.reason_message
                        else:
                            mapped_path = decision.safe_path

                    if reason_code is not None or rule is None or mapped_path is None:
                        counters["entries_rejected"] += 1
                        stage = _stage_for_reason(reason_code or "MAPPING_REJECTED")
                        if rule is not None:
                            stats = rule_statistics[rule.rule_id]
                            stats["rejected_entries"] += 1
                            stats["entry_too_large"] += int(reason_code == "ENTRY_TOO_LARGE")
                            stats["unsupported_extension"] += int(reason_code == "UNSUPPORTED_EXTENSION")
                            stats["path_validation_failed"] += int(stage == "mapping_validation")
                        elif reason_code == "MAPPING_RULE_NOT_FOUND":
                            counters["unmatched_entries"] += 1
                            unmatched_extensions[_entry_extension(info.filename)] += 1
                            unmatched_prefix_groups[_sanitized_prefix_preview(info.filename)] += 1
                        if len(rejections) < MAX_REJECTION_RECORDS:
                            rejections.append(_manual_rejection(
                                archive_relative,
                                info,
                                reason_code or "MAPPING_REJECTED",
                                reason_message or "entry mapping이 거부됐습니다.",
                                rule=rule,
                                mapping_matched=mapping_matched,
                                rejection_stage=stage,
                            ))
                        continue

                    output_relative = PurePosixPath("extracted", archive_id, mapped_path).as_posix()
                    output_probe = (Path("/") / "isolated" / Path(*PurePosixPath(output_relative).parts)).resolve()
                    if not _is_within(output_probe, (Path("/") / "isolated").resolve()):
                        counters["entries_rejected"] += 1
                        rule_statistics[rule.rule_id]["rejected_entries"] += 1
                        rule_statistics[rule.rule_id]["path_validation_failed"] += 1
                        if len(rejections) < MAX_REJECTION_RECORDS:
                            rejections.append(_manual_rejection(
                                archive_relative,
                                info,
                                "OUTPUT_ESCAPE",
                                "mapping 결과가 출력 root를 벗어납니다.",
                                rule=rule,
                                mapping_matched=True,
                                rejection_stage="output_validation",
                            ))
                        continue
                    if output_relative in output_paths:
                        counters["entries_rejected"] += 1
                        rule_statistics[rule.rule_id]["rejected_entries"] += 1
                        if len(rejections) < MAX_REJECTION_RECORDS:
                            rejections.append(_manual_rejection(
                                archive_relative,
                                info,
                                "DUPLICATE_OUTPUT_PATH",
                                "동일 출력 상대 경로가 중복됩니다.",
                                rule=rule,
                                mapping_matched=True,
                                rejection_stage="output_validation",
                            ))
                        continue
                    output_paths.add(output_relative)
                    original_hash = _sha256_text(info.filename)
                    candidates.append(ManualCandidate(
                        archive_path=archive_path,
                        archive_relative_path=archive_relative,
                        archive_id=archive_id,
                        info=info,
                        entry_relative_path=mapped_path,
                        output_relative_path=output_relative,
                        selection_rank=_manual_rank(
                            entry.dataset_id, archive_relative, original_hash, rule.rule_id, selection_seed
                        ),
                        original_entry_hash=original_hash,
                        rule_id=rule.rule_id,
                        sanitized_source_prefix=rule.sanitized_source_prefix,
                    ))
                    counters["entries_mapped"] += 1
                    rule_statistics[rule.rule_id]["safe_entries"] += 1
        except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
            counters["archives_corrupted"] += 1
            if len(rejections) < MAX_REJECTION_RECORDS:
                rejections.append(_manual_rejection(
                    archive_relative,
                    None,
                    "CORRUPTED_ENTRY",
                    "ZIP 중앙 디렉터리를 안전하게 읽을 수 없습니다.",
                    rule=None,
                    mapping_matched=False,
                    rejection_stage="entry_validation",
                ))

    return (
        candidates,
        rejections,
        dict(counters),
        rule_statistics,
        unmatched_extensions,
        unmatched_prefix_groups,
    )


def _select_mapped_candidates(
    candidates: Iterable[ManualCandidate],
    sample_count: int,
    max_total_bytes: int,
    rejections: list[dict[str, Any]],
    mapping: ManualMapping,
    rule_statistics: dict[str, Counter[str]],
) -> list[ManualCandidate]:
    by_archive: dict[str, list[ManualCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_archive[candidate.archive_relative_path].append(candidate)
    for rows in by_archive.values():
        rows.sort(key=lambda item: (item.selection_rank, item.original_entry_hash))
    ordered: list[ManualCandidate] = []
    first_keys: set[tuple[str, str]] = set()
    for archive_name in sorted(by_archive):
        first = by_archive[archive_name][0]
        ordered.append(first)
        first_keys.add((first.archive_relative_path, first.original_entry_hash))
    ordered.extend(sorted(
        (
            candidate
            for rows in by_archive.values()
            for candidate in rows
            if (candidate.archive_relative_path, candidate.original_entry_hash) not in first_keys
        ),
        key=lambda item: (item.selection_rank, item.archive_relative_path, item.original_entry_hash),
    ))

    selected: list[ManualCandidate] = []
    total = 0
    for candidate in ordered:
        if len(selected) >= sample_count:
            break
        if total + candidate.info.file_size > max_total_bytes:
            rule = next(rule for rule in mapping.rules if rule.rule_id == candidate.rule_id)
            rule_statistics[rule.rule_id]["rejected_entries"] += 1
            rejections.append(_manual_rejection(
                candidate.archive_relative_path,
                candidate.info,
                "TOTAL_LIMIT_EXCEEDED",
                "선택 시 전체 byte 제한을 초과합니다.",
                rule=rule,
                mapping_matched=True,
                rejection_stage="selection",
            ))
            continue
        selected.append(candidate)
        rule_statistics[candidate.rule_id]["selected_entries"] += 1
        total += candidate.info.file_size
    return selected


def _sample_row(candidate: ManualCandidate, extracted: Mapping[str, Any] | None, schema_status: str) -> dict[str, Any]:
    return {
        "archive_relative_path": candidate.archive_relative_path,
        "original_entry_name_hash": candidate.original_entry_hash,
        "mapping_rule_id": candidate.rule_id,
        "sanitized_source_prefix": candidate.sanitized_source_prefix,
        "mapped_relative_path": candidate.entry_relative_path,
        "output_relative_path": candidate.output_relative_path,
        "extension": PurePosixPath(candidate.entry_relative_path).suffix.lower(),
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "crc": candidate.info.CRC,
        "entry_checksum": None if extracted is None else extracted["entry_checksum"],
        "output_checksum": None if extracted is None else extracted["output_checksum"],
        "selection_rank": candidate.selection_rank,
        "selection_reason": "archive_diversity_then_manual_mapping_sha256",
        "schema_status": schema_status,
    }


def _mapping_validation(mapping: ManualMapping) -> dict[str, Any]:
    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "dataset_id": mapping.dataset_id,
        "status": "approved_and_valid",
        "mapping_file_fingerprint": mapping.fingerprint,
        "approval": {
            "status": mapping.approval.status,
            "approved_by": mapping.approval.approved_by,
            "approved_at": mapping.approval.approved_at,
        },
        "rules": [
            {
                "rule_id": rule.rule_id,
                "source_prefix_hash": _canonical_fingerprint({"source_prefix": rule.source_prefix}),
                "sanitized_source_prefix": rule.sanitized_source_prefix,
                "target_prefix": rule.target_prefix,
                "allowed_extensions": sorted(rule.allowed_extensions),
            }
            for rule in mapping.rules
        ],
    }


def sample_dataset_with_manual_mapping(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    *,
    requested_archive: str | None,
    sample_count: int,
    max_file_bytes: int,
    max_total_bytes: int,
    allowed_extensions: Iterable[str],
    dry_run: bool,
    selection_seed: str = DEFAULT_MANUAL_SEED,
) -> dict[str, Any]:
    if mapping.dataset_id != entry.dataset_id:
        raise SamplerError("검증된 mapping dataset_id가 대상 dataset과 일치하지 않습니다.")
    if sample_count <= 0 or max_file_bytes <= 0 or max_total_bytes <= 0:
        raise SamplerError("sample-count와 byte 제한은 0보다 커야 합니다.")
    normalized_extensions = frozenset(_normalize_extension(value) for value in allowed_extensions)

    before = inventory_dataset(entry)
    archives = _iter_archives(entry, requested_archive)
    (
        candidates,
        rejections,
        counters,
        rule_statistics,
        unmatched_extensions,
        unmatched_prefix_groups,
    ) = _scan_mapped_archives(
        entry,
        archives,
        mapping,
        allowed_extensions=normalized_extensions,
        max_file_bytes=max_file_bytes,
        selection_seed=selection_seed,
    )
    selected = _select_mapped_candidates(
        candidates,
        sample_count,
        max_total_bytes,
        rejections,
        mapping,
        rule_statistics,
    )
    rule_statistics_rows = _rule_statistics_rows(mapping, rule_statistics)
    fingerprint_payload = {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "manual_mapping_contract_version": MANUAL_MAPPING_CONTRACT_VERSION,
        "dataset_id": entry.dataset_id,
        "dataset_relative_root": entry.relative_root,
        "mapping_file_fingerprint": mapping.fingerprint,
        "requested_archive": requested_archive,
        "selection_seed": selection_seed,
        "sample_count": sample_count,
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
        "allowed_extensions": sorted(normalized_extensions),
        "dry_run": dry_run,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "selected": [
            [item.archive_relative_path, item.original_entry_hash, item.rule_id, item.info.file_size, item.info.CRC]
            for item in selected
        ],
    }
    run_fingerprint = _canonical_fingerprint(fingerprint_payload)
    prefix = "manual-dry-" if dry_run else "manual-sample-"
    run_id = prefix + run_fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 수동 mapping 실행 결과가 이미 존재하여 덮어쓰지 않습니다.")

    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        extracted_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        if not dry_run:
            for candidate in selected:
                extracted_by_key[(candidate.archive_relative_path, candidate.original_entry_hash)] = _extract_candidate(
                    candidate, staging
                )

        after = inventory_dataset(entry)
        if before["inventory_metadata_digest"] != after["inventory_metadata_digest"]:
            raise SamplerError("수동 표본 처리 중 원본 metadata 변경이 탐지됐습니다.")

        schema_summary = build_schema_summary(
            staging / "extracted", entry.dataset_id, sample_count, max_file_bytes
        ) if not dry_run else {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "status": "not_run_dry_run",
            "extension_counts": {},
            "parse_failure_count": 0,
            "text_field_candidates": [],
            "label_metadata_candidates": [],
            "pii_field_warnings": [],
            "csv_tsv_profiles": [],
        }
        samples = [
            _sample_row(
                candidate,
                extracted_by_key.get((candidate.archive_relative_path, candidate.original_entry_hash)),
                "not_run_dry_run" if dry_run else schema_summary["status"],
            )
            for candidate in selected
        ]
        manifest = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source_root": "configured_external_root",
            "dataset_relative_root": entry.relative_root,
            "output_root": "configured_external_analysis_manual_samples",
            "mapping_file_fingerprint": mapping.fingerprint,
            "approval": {
                "status": mapping.approval.status,
                "approved_by": mapping.approval.approved_by,
                "approved_at": mapping.approval.approved_at,
                "candidate_status": "registered",
                "license_review_status": "pending_terms_review",
                "tokenizer": "pending",
                "pretraining": "pending",
                "sft": "pending",
                "evaluation": "pending",
            },
            "selection_seed": selection_seed,
            "selection_strategy": "archive_diversity_then_manual_mapping_sha256",
            "sample_count_requested": sample_count,
            "sample_count_selected": len(selected),
            "sample_count_extracted": 0 if dry_run else len(samples),
            "total_bytes_extracted": 0 if dry_run else sum(item["uncompressed_size"] for item in samples),
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "allowed_extensions": sorted(normalized_extensions),
            "archives_scanned": counters.get("archives_scanned", 0),
            "archives_corrupted": counters.get("archives_corrupted", 0),
            "entries_scanned": counters.get("entries_scanned", 0),
            "entries_mapped": counters.get("entries_mapped", 0),
            "rule_statistics": rule_statistics_rows,
            "unmatched_entries": counters.get("unmatched_entries", 0),
            "unmatched_by_extension": dict(sorted(unmatched_extensions.items())),
            "unmatched_prefix_groups": dict(sorted(unmatched_prefix_groups.items())),
            "entries_rejected": counters.get("entries_rejected", 0) + max(
                0, len(rejections) - counters.get("entries_rejected", 0)
            ),
            "rejected_entries_truncated": counters.get("entries_rejected", 0) > len(rejections),
            "samples": samples,
            "run_fingerprint": run_fingerprint,
            "dry_run": dry_run,
            "source_inventory_metadata_digest": before["inventory_metadata_digest"],
            "source_mutation_detected": False,
        }
        run_status = "manual_mapping_dry_run_complete" if dry_run else "manual_mapping_sample_extracted"
        if not selected:
            run_status = "manual_mapping_no_candidates"
        run_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "status": run_status,
            "dry_run": dry_run,
            "mapping_file_fingerprint": mapping.fingerprint,
            "sample_count_selected": len(selected),
            "sample_count_extracted": manifest["sample_count_extracted"],
            "entries_rejected": manifest["entries_rejected"],
            "rule_statistics": rule_statistics_rows,
            "unmatched_entries": manifest["unmatched_entries"],
            "unmatched_by_extension": manifest["unmatched_by_extension"],
            "unmatched_prefix_groups": manifest["unmatched_prefix_groups"],
            "source_mutation_detected": False,
            "schema_status": schema_summary["status"],
            "automatic_unsafe_path_normalization": False,
            "explicit_approved_prefix_mapping": True,
        }
        _atomic_json(staging / "mapped-manifest.json", manifest)
        _atomic_json(staging / "mapping-validation.json", _mapping_validation(mapping))
        _atomic_json(staging / "rejected-entries.json", {
            "schema_version": "1.0",
            "rejected_entries": rejections,
            "record_count": len(rejections),
            "records_truncated": manifest["rejected_entries_truncated"],
        })
        _atomic_json(staging / "schema-summary.json", schema_summary)
        _atomic_json(staging / "run-summary.json", run_summary)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return {
        "success": True,
        "dataset_id": entry.dataset_id,
        "run_id": run_id,
        "run_status": run_status,
        "manual_mapping": True,
        "dry_run": dry_run,
        "archives_scanned": counters.get("archives_scanned", 0),
        "entries_scanned": counters.get("entries_scanned", 0),
        "entries_safe": counters.get("entries_mapped", 0),
        "entries_rejected": manifest["entries_rejected"],
        "rule_statistics": rule_statistics_rows,
        "unmatched_entries": manifest["unmatched_entries"],
        "samples_selected": len(selected),
        "samples_extracted": manifest["sample_count_extracted"],
        "source_mutation_detected": False,
        "output_location": "external_analysis_manual_samples_root",
        "artifacts": sorted(path.name for path in final.iterdir() if path.is_file()),
    }
