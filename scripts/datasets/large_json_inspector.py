"""대용량 ZIP JSON entry의 제한된 prefix byte만 streaming 검사한다."""

from __future__ import annotations

import codecs
import copy
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from .analyzer import AnalyzerConfig, DatasetEntry, inventory_dataset
from .manual_path_mapping import (
    DEFAULT_MANUAL_SEED,
    ManualMapping,
    MappingRule,
    _manual_rank,
    _map_entry_path,
    _matching_rule,
)
from .safe_sampler import (
    SUPPORTED_ZIP_COMPRESSION,
    SamplerError,
    _atomic_json,
    _canonical_fingerprint,
    _iter_archives,
    _sha256_text,
    validate_entry,
)


DEFAULT_LARGE_THRESHOLD_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 5
DEFAULT_MAX_READ_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_READ_BYTES = 10 * 1024 * 1024
INSPECTION_CONTRACT_VERSION = "1.0"
READ_CHUNK_BYTES = 64 * 1024
MAX_SCHEMA_KEYS = 128
ALLOWED_SCHEMA_KEYS = frozenset({
    "text", "content", "instruction", "response", "role", "label", "metadata",
})


@dataclass(frozen=True)
class LargeJsonCandidate:
    archive_path: Path
    archive_relative_path: str
    info: zipfile.ZipInfo
    rule: MappingRule
    entry_name_hash: str
    selection_rank: str


def large_json_output_root(config: AnalyzerConfig, requested: str | Path | None, repository_root: Path) -> Path:
    allowed_root = (config.external_root / "analysis" / "large-json-inspection").resolve()
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
            raise SamplerError("대용량 JSON 검사 출력은 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("대용량 JSON 검사 출력은 external analysis/large-json-inspection 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("대용량 JSON 검사 결과를 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _large_candidates(
    entry: DatasetEntry,
    mapping: ManualMapping,
    archives: Iterable[Path],
    *,
    threshold_bytes: int,
    seed: str,
) -> list[LargeJsonCandidate]:
    candidates: list[LargeJsonCandidate] = []
    for archive_path in archives:
        archive_relative = archive_path.relative_to(entry.root).as_posix()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    rule = _matching_rule(info.filename, mapping)
                    if rule is None or ".json" not in rule.allowed_extensions:
                        continue
                    if info.compress_type not in SUPPORTED_ZIP_COMPRESSION or info.file_size <= threshold_bytes:
                        continue
                    mapped_info = copy.copy(info)
                    mapped_info.filename = _map_entry_path(info.filename, rule)
                    decision = validate_entry(
                        mapped_info,
                        Path("/") / "isolated-large-json",
                        allowed_extensions=frozenset({".json"}),
                        max_file_bytes=info.file_size,
                    )
                    if decision.reason_code:
                        continue
                    entry_hash = _sha256_text(info.filename)
                    candidates.append(LargeJsonCandidate(
                        archive_path=archive_path,
                        archive_relative_path=archive_relative,
                        info=info,
                        rule=rule,
                        entry_name_hash=entry_hash,
                        selection_rank=_manual_rank(entry.dataset_id, archive_relative, entry_hash, rule.rule_id, seed),
                    ))
        except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
            continue
    return sorted(candidates, key=lambda item: (item.selection_rank, item.entry_name_hash))


def _schema_key_row(raw_key: str) -> dict[str, Any]:
    normalized = raw_key if raw_key in ALLOWED_SCHEMA_KEYS else None
    return {
        "key_name_hash": _sha256_text(raw_key),
        "sanitized_name": normalized,
    }


def _lex_json_prefix(text: str, *, truncated: bool, utf8_status: str) -> dict[str, Any]:
    index = 0
    while index < len(text) and text[index].isspace():
        index += 1
    first = text[index] if index < len(text) else None
    root_type = {
        "{": "object",
        "[": "array",
        '"': "string",
        "t": "boolean",
        "f": "boolean",
        "n": "null",
    }.get(first, "number" if first is not None and first in "-0123456789" else "unknown")
    first_token = {"{": "object_start", "[": "array_start", '"': "string_start"}.get(first, root_type)

    depth = 0
    in_string = False
    escape = False
    string_chars: list[str] = []
    string_depth = 0
    top_keys: dict[str, dict[str, Any]] = {}
    array_keys: dict[str, dict[str, Any]] = {}
    root_completed_at: int | None = None
    completed_values = 0
    newline_after_completion = False
    jsonl_candidate = False

    for position, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
                if len(string_chars) < 1024:
                    string_chars.append("\\" + char)
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
                cursor = position + 1
                while cursor < len(text) and text[cursor].isspace():
                    cursor += 1
                if cursor < len(text) and text[cursor] == ":":
                    raw_key = "".join(string_chars)
                    row = _schema_key_row(raw_key)
                    if root_type == "object" and string_depth == 1:
                        top_keys.setdefault(row["key_name_hash"], row)
                    elif root_type == "array" and string_depth == 2:
                        array_keys.setdefault(row["key_name_hash"], row)
                string_chars = []
                continue
            if len(string_chars) < 1024:
                string_chars.append(char)
            continue

        if char == '"':
            in_string = True
            string_depth = depth
            string_chars = []
            continue
        if char in "{[":
            if depth == 0 and completed_values:
                jsonl_candidate = jsonl_candidate or newline_after_completion
                newline_after_completion = False
            depth += 1
            continue
        if char in "}]":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    completed_values += 1
                    root_completed_at = position
            continue
        if completed_values and depth == 0 and char in "\r\n":
            newline_after_completion = True

    trailing = "" if root_completed_at is None else text[root_completed_at + 1 :]
    if utf8_status != "strict_utf8":
        completeness = "invalid_utf8"
    elif root_completed_at is not None and not trailing.strip():
        completeness = "complete"
    elif truncated:
        completeness = "truncated"
    else:
        completeness = "incomplete"
    return {
        "json_root_type_candidate": root_type,
        "first_structure_token": first_token,
        "top_level_key_candidates": list(top_keys.values())[:MAX_SCHEMA_KEYS],
        "array_item_top_level_key_candidates": list(array_keys.values())[:MAX_SCHEMA_KEYS],
        "json_lines_candidate": jsonl_candidate,
        "parse_completeness": completeness,
        "truncated": truncated,
        "lexical_depth_at_limit": depth,
        "unterminated_string_at_limit": in_string,
    }


def inspect_stream_prefix(source: Any, *, max_read_bytes: int) -> dict[str, Any]:
    if max_read_bytes <= 0:
        raise SamplerError("max-read-bytes는 0보다 커야 합니다.")
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    decoded: list[str] = []
    bytes_read = 0
    bom = False
    utf8_status = "strict_utf8"
    reached_eof = False
    first_chunk = True
    while bytes_read < max_read_bytes:
        request = min(READ_CHUNK_BYTES, max_read_bytes - bytes_read)
        chunk = source.read(request)
        if not chunk:
            reached_eof = True
            break
        bytes_read += len(chunk)
        if first_chunk:
            bom = chunk.startswith(codecs.BOM_UTF8)
            if bom:
                chunk = chunk[len(codecs.BOM_UTF8) :]
            first_chunk = False
        try:
            decoded.append(decoder.decode(chunk, final=False))
        except UnicodeDecodeError:
            utf8_status = "invalid_utf8"
            break
    if utf8_status == "strict_utf8" and reached_eof:
        try:
            decoded.append(decoder.decode(b"", final=True))
        except UnicodeDecodeError:
            utf8_status = "invalid_utf8"
    text = "".join(decoded)
    lexical = _lex_json_prefix(text, truncated=not reached_eof, utf8_status=utf8_status)
    return {
        "bytes_read": bytes_read,
        "utf8_decode_status": utf8_status,
        "utf8_bom": bom,
        **lexical,
    }


def _inspect_candidate(candidate: LargeJsonCandidate, max_read_bytes: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(candidate.archive_path) as archive:
            with archive.open(candidate.info, "r") as source:
                structure = inspect_stream_prefix(source, max_read_bytes=max_read_bytes)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise SamplerError("대용량 JSON entry를 제한 범위에서 검사할 수 없습니다.") from exc
    status = "large_entry_stream_inspected"
    if structure["utf8_decode_status"] != "strict_utf8" or structure["json_root_type_candidate"] == "unknown":
        status = "large_entry_manual_review_required"
    return {
        "status": status,
        "archive_relative_path_hash": _sha256_text(candidate.archive_relative_path),
        "entry_name_hash": candidate.entry_name_hash,
        "mapping_rule_id": candidate.rule.rule_id,
        "source_prefix_hash": candidate.rule.source_prefix_hash,
        "sanitized_source_prefix": candidate.rule.sanitized_source_prefix,
        "extension": ".json",
        "uncompressed_size": candidate.info.file_size,
        "compressed_size": candidate.info.compress_size,
        "selection_rank": candidate.selection_rank,
        **structure,
    }


def inspect_large_json_entries(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    *,
    requested_archive: str | None,
    max_entries: int,
    max_read_bytes: int,
    max_total_read_bytes: int,
    dry_run: bool,
    selection_seed: str = DEFAULT_MANUAL_SEED,
) -> dict[str, Any]:
    if not dry_run:
        raise SamplerError("대용량 JSON 검사는 --dry-run 읽기 전용 모드만 지원합니다.")
    if max_entries <= 0 or max_read_bytes <= 0 or max_total_read_bytes <= 0:
        raise SamplerError("entry 수와 read byte 제한은 0보다 커야 합니다.")
    if mapping.dataset_id != entry.dataset_id:
        raise SamplerError("mapping dataset_id가 검사 대상과 일치하지 않습니다.")
    before = inventory_dataset(entry)
    archives = _iter_archives(entry, requested_archive)
    candidates = _large_candidates(
        entry,
        mapping,
        archives,
        threshold_bytes=DEFAULT_LARGE_THRESHOLD_BYTES,
        seed=selection_seed,
    )
    selected = candidates[:max_entries]
    fingerprint = _canonical_fingerprint({
        "contract_version": INSPECTION_CONTRACT_VERSION,
        "dataset_id": entry.dataset_id,
        "mapping_file_fingerprint": mapping.fingerprint,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "max_entries": max_entries,
        "max_read_bytes": max_read_bytes,
        "max_total_read_bytes": max_total_read_bytes,
        "selected": [[item.entry_name_hash, item.selection_rank] for item in selected],
    })
    run_id = "large-json-dry-" + fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 대용량 JSON 검사 결과가 이미 존재하여 덮어쓰지 않습니다.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        inspections: list[dict[str, Any]] = []
        total_read = 0
        for candidate in selected:
            remaining = max_total_read_bytes - total_read
            if remaining <= 0:
                break
            inspection = _inspect_candidate(candidate, min(max_read_bytes, remaining))
            inspections.append(inspection)
            total_read += inspection["bytes_read"]
        after = inventory_dataset(entry)
        if before["inventory_metadata_digest"] != after["inventory_metadata_digest"]:
            raise SamplerError("대용량 JSON 검사 중 원본 metadata 변경이 탐지됐습니다.")
        report = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "status": "large_entry_stream_inspected" if inspections else "large_entry_manual_review_required",
            "dry_run": True,
            "source_root": "configured_external_root",
            "output_root": "configured_external_analysis_large_json_inspection",
            "mapping_file_fingerprint": mapping.fingerprint,
            "large_entry_threshold_bytes": DEFAULT_LARGE_THRESHOLD_BYTES,
            "candidate_status": "large_entry_inspection_candidate",
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "inspected_count": len(inspections),
            "max_entries": max_entries,
            "max_read_bytes_per_entry": max_read_bytes,
            "max_total_read_bytes": max_total_read_bytes,
            "total_bytes_read": total_read,
            "full_entry_extraction_performed": False,
            "source_mutation_detected": False,
            "inspections": inspections,
            "run_fingerprint": fingerprint,
        }
        summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "status": report["status"],
            "candidate_count": len(candidates),
            "inspected_count": len(inspections),
            "total_bytes_read": total_read,
            "full_entry_extraction_performed": False,
            "source_mutation_detected": False,
        }
        _atomic_json(staging / "large-json-inspection.json", report)
        _atomic_json(staging / "run-summary.json", summary)
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
        "candidate_count": len(candidates),
        "inspected_count": len(inspections),
        "total_bytes_read": total_read,
        "source_mutation_detected": False,
        "output_location": "external_analysis_large_json_inspection_root",
    }
