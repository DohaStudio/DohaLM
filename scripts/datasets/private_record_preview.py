"""사용자 승인 시에만 redacted 최소 text preview를 외부에 생성한다."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .analyzer import AnalyzerConfig, DatasetEntry, inventory_dataset
from .json_record_stream import RECORD_OK, RecordEvent, scan_json_array_records
from .large_json_inspector import DEFAULT_LARGE_THRESHOLD_BYTES, LargeJsonCandidate, _large_candidates
from .manual_path_mapping import DEFAULT_MANUAL_SEED, ManualMapping
from .private_preview_policy import PrivatePreviewPolicy
from .safe_sampler import SamplerError, _atomic_json, _canonical_fingerprint, _iter_archives, _sha256_file, _sha256_text
from .schema_review_bundle import analyze_review_record
from .stratified_record_sampler import (
    DEFAULT_MAX_READ_BYTES_PER_ENTRY,
    DEFAULT_MAX_RECORD_BYTES,
    DEFAULT_MAX_TOTAL_READ_BYTES,
    record_stratum,
    select_stratified_entries,
)


PRIVATE_PREVIEW_CONTRACT_VERSION = "1.0"
DEFAULT_PREVIEW_SELECTION_SEED = "dohalm-private-record-preview-v1"
TRUNCATION_MARKER = "[TRUNCATED]"

EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)")
RRN_RE = re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>]+")
LONG_IDENTIFIER_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")


def private_review_output_root(
    config: AnalyzerConfig,
    requested: str | Path | None,
    repository_root: Path,
) -> Path:
    allowed_root = (config.external_root / "analysis" / "private-review").resolve()
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
            raise SamplerError("private review 출력은 원본 dataset 경로와 겹칠 수 없습니다.")
    if output != allowed_root and allowed_root not in output.parents:
        raise SamplerError("private review 출력은 external analysis/private-review 아래여야 합니다.")
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        raise SamplerError("preview를 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _valid_ipv4(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        valid = all(0 <= int(part) <= 255 for part in value.split("."))
    except ValueError:
        valid = False
    return "[REDACTED_IP]" if valid else value


def _redact_url(match: re.Match[str]) -> str:
    value = match.group(0)
    parsed = urlsplit(value)
    if not parsed.query:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[REDACTED_IDENTIFIER]", parsed.fragment))


def redact_text(value: str) -> tuple[str, list[str], int]:
    """보수적 표준 라이브러리 pattern으로 PII 후보를 치환한다."""

    redaction_counts: Counter[str] = Counter()

    def substitute(pattern: re.Pattern[str], replacement: str, label: str, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            redaction_counts[label] += 1
            return replacement

        return pattern.sub(replace, text)

    redacted = substitute(RRN_RE, "[REDACTED_RRN]", "rrn", value)
    redacted = substitute(EMAIL_RE, "[REDACTED_EMAIL]", "email", redacted)
    redacted = substitute(PHONE_RE, "[REDACTED_PHONE]", "phone", redacted)
    redacted = substitute(CARD_RE, "[REDACTED_CARD]", "card", redacted)

    def replace_ip(match: re.Match[str]) -> str:
        replaced = _valid_ipv4(match)
        if replaced != match.group(0):
            redaction_counts["ip"] += 1
        return replaced

    redacted = IPV4_RE.sub(replace_ip, redacted)

    def replace_url(match: re.Match[str]) -> str:
        replaced = _redact_url(match)
        if replaced != match.group(0):
            redaction_counts["url_query"] += 1
        return replaced

    redacted = URL_RE.sub(replace_url, redacted)
    redacted = substitute(LONG_IDENTIFIER_RE, "[REDACTED_IDENTIFIER]", "identifier", redacted)
    return redacted, sorted(redaction_counts), sum(redaction_counts.values())


def limit_text(value: str, maximum_characters: int) -> tuple[str, bool]:
    if maximum_characters <= 0:
        raise ValueError("문자 제한은 0보다 커야 합니다.")
    if len(value) <= maximum_characters:
        return value, False
    if maximum_characters < len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:maximum_characters], True
    prefix_length = maximum_characters - len(TRUNCATION_MARKER)
    return value[:prefix_length] + TRUNCATION_MARKER, True


def _preview_rank(
    dataset_id: str,
    archive_hash: str,
    entry_hash: str,
    record_index: int,
    stratum: str,
    schema_signature: str,
    seed: str,
) -> str:
    payload = "\n".join((
        seed, dataset_id, archive_hash, entry_hash, str(record_index), stratum, schema_signature,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inspect_preview_options(
    entry: DatasetEntry,
    candidate: LargeJsonCandidate,
    policy: PrivatePreviewPolicy,
    *,
    max_read_bytes: int,
    selection_seed: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    archive_hash = _sha256_text(candidate.archive_relative_path)
    options: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()

    def on_record(event: RecordEvent) -> None:
        if event.status != RECORD_OK:
            rejection_counts[event.status] += 1
            return
        if not isinstance(event.value, dict):
            return
        text = event.value.get("text")
        if not isinstance(text, str):
            return
        analysis = analyze_review_record(event.value)
        redacted, redaction_types, redaction_count = redact_text(text)
        stored, truncated = limit_text(redacted, policy.scope.max_characters_per_record)
        options.append({
            "archive_hash": archive_hash,
            "entry_hash": candidate.entry_name_hash,
            "record_index": event.record_index,
            "schema_signature": analysis["schema_signature"],
            "field_name": "text",
            "original_character_count": len(text),
            "stored_character_count": len(stored),
            "truncated": truncated,
            "redaction_types": redaction_types,
            "redaction_count": redaction_count,
            "redacted_text": stored,
        })

    try:
        with zipfile.ZipFile(candidate.archive_path) as archive:
            with archive.open(candidate.info, "r") as source:
                scan = scan_json_array_records(
                    source,
                    max_record_bytes=DEFAULT_MAX_RECORD_BYTES,
                    max_read_bytes=max_read_bytes,
                    on_record=on_record,
                )
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise SamplerError("private preview 후보 entry를 제한 범위에서 검사할 수 없습니다.") from exc

    for option in options:
        stratum = record_stratum(option["record_index"], scan.records_seen)
        option["record_stratum"] = stratum
        option["selection_rank"] = _preview_rank(
            entry.dataset_id,
            archive_hash,
            candidate.entry_name_hash,
            option["record_index"],
            stratum,
            option["schema_signature"],
            selection_seed,
        )
    return {
        "archive_hash": archive_hash,
        "entry_hash": candidate.entry_name_hash,
        "bytes_read": scan.bytes_read,
        "records_seen": scan.records_seen,
        "eligible_text_records": len(options),
        "scan_status": scan.status,
        "rejection_status_counts": dict(sorted(rejection_counts.items())),
    }, options


def select_preview_options(options: Iterable[dict[str, Any]], max_records: int) -> list[dict[str, Any]]:
    """Archive·entry 최대 1개를 유지하며 strata·signature 다양성을 우선한다."""

    if max_records <= 0:
        raise ValueError("max_records는 0보다 커야 합니다.")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for option in options:
        grouped.setdefault((option["archive_hash"], option["entry_hash"]), []).append(option)
    selected: list[dict[str, Any]] = []
    used_archives: set[str] = set()
    used_strata: set[str] = set()
    used_signatures: set[str] = set()
    entry_order = sorted(
        grouped,
        key=lambda key: min(row["selection_rank"] for row in grouped[key]),
    )
    for key in entry_order:
        archive_hash, _ = key
        if archive_hash in used_archives:
            continue
        rows = sorted(
            grouped[key],
            key=lambda row: (
                -(row["record_stratum"] not in used_strata),
                -(row["schema_signature"] not in used_signatures),
                row["selection_rank"],
            ),
        )
        chosen = rows[0]
        selected.append(chosen)
        used_archives.add(archive_hash)
        used_strata.add(chosen["record_stratum"])
        used_signatures.add(chosen["schema_signature"])
        if len(selected) >= max_records:
            break
    return selected


def _archive_checksums(candidates: Iterable[LargeJsonCandidate]) -> dict[str, str]:
    unique: dict[str, Path] = {}
    for candidate in candidates:
        unique.setdefault(_sha256_text(candidate.archive_relative_path), candidate.archive_path)
    return {archive_hash: _sha256_file(path) for archive_hash, path in sorted(unique.items())}


def _write_preview(path: Path, preview: dict[str, Any]) -> str:
    schema_id = "schema-" + preview["schema_signature"].removeprefix("sha256:")[:12]
    content = (
        f"preview_id: {preview['preview_id']}\n"
        f"archive_hash: {preview['archive_hash']}\n"
        f"entry_hash: {preview['entry_hash']}\n"
        f"record_index: {preview['record_index']}\n"
        f"schema_signature_id: {schema_id}\n"
        "field: text\n"
        "review_status: manual_review_required\n"
        "---\n"
        f"{preview['redacted_text']}\n"
    )
    path.write_text(content, encoding="utf-8", newline="\n")
    return _sha256_file(path)


def generate_private_previews(
    entry: DatasetEntry,
    output_root: Path,
    mapping: ManualMapping,
    policy: PrivatePreviewPolicy,
    *,
    dry_run: bool,
    selection_seed: str = DEFAULT_PREVIEW_SELECTION_SEED,
) -> dict[str, Any]:
    if mapping.dataset_id != entry.dataset_id or policy.dataset_id != entry.dataset_id:
        raise SamplerError("mapping·preview policy dataset_id가 대상과 일치하지 않습니다.")
    if not dry_run and policy.approval.status != "approved":
        raise SamplerError("승인되지 않은 정책으로 preview를 생성할 수 없습니다.")

    before = inventory_dataset(entry)
    archives = _iter_archives(entry, None)
    candidates = _large_candidates(
        entry, mapping, archives, threshold_bytes=DEFAULT_LARGE_THRESHOLD_BYTES, seed=DEFAULT_MANUAL_SEED,
    )
    selected_entries = select_stratified_entries(
        entry.dataset_id,
        candidates,
        max_archives=policy.scope.max_records,
        max_entries_per_archive=1,
        selection_seed=selection_seed,
    )
    mode = "dry-run" if dry_run else "generation"
    fingerprint = _canonical_fingerprint({
        "contract_version": PRIVATE_PREVIEW_CONTRACT_VERSION,
        "mode": mode,
        "dataset_id": entry.dataset_id,
        "policy_fingerprint": policy.fingerprint,
        "mapping_fingerprint": mapping.fingerprint,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "selection_seed": selection_seed,
        "selected_entries": [
            [_sha256_text(item.archive_relative_path), item.entry_name_hash] for item in selected_entries
        ],
    })
    run_id = f"private-preview-{'dry' if dry_run else 'run'}-" + fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 private preview run이 이미 존재하여 덮어쓰지 않습니다.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()

    try:
        pre_checksums = {} if dry_run else _archive_checksums(selected_entries)
        entry_summaries: list[dict[str, Any]] = []
        options: list[dict[str, Any]] = []
        total_read = 0
        if not dry_run:
            for candidate in selected_entries:
                remaining = DEFAULT_MAX_TOTAL_READ_BYTES - total_read
                if remaining <= 0:
                    break
                summary, rows = _inspect_preview_options(
                    entry,
                    candidate,
                    policy,
                    max_read_bytes=min(DEFAULT_MAX_READ_BYTES_PER_ENTRY, remaining),
                    selection_seed=selection_seed,
                )
                total_read += summary["bytes_read"]
                entry_summaries.append(summary)
                options.extend(rows)
        selected = [] if dry_run else select_preview_options(options, policy.scope.max_records)
        preview_rows = []
        preview_files = []
        for index, preview in enumerate(selected, start=1):
            preview_id = f"preview-{index:03d}"
            preview["preview_id"] = preview_id
            filename = f"{preview_id}.txt"
            checksum = _write_preview(staging / filename, preview)
            preview_files.append(filename)
            preview_rows.append({
                "preview_id": preview_id,
                "archive_hash": preview["archive_hash"],
                "entry_hash": preview["entry_hash"],
                "record_index": preview["record_index"],
                "record_stratum": preview["record_stratum"],
                "schema_signature_id": "schema-" + preview["schema_signature"].removeprefix("sha256:")[:12],
                "field_name": "text",
                "original_character_count": preview["original_character_count"],
                "stored_character_count": preview["stored_character_count"],
                "truncated": preview["truncated"],
                "redaction_types": preview["redaction_types"],
                "redaction_count": preview["redaction_count"],
                "preview_checksum": checksum,
                "review_status": "not_reviewed",
            })

        after = inventory_dataset(entry)
        post_checksums = {} if dry_run else _archive_checksums(selected_entries)
        source_mutation = (
            before["inventory_metadata_digest"] != after["inventory_metadata_digest"]
            or pre_checksums != post_checksums
        )
        if source_mutation:
            raise SamplerError("private preview 처리 중 원본 ZIP 변경이 탐지됐습니다.")

        created_at = datetime.now(UTC)
        expires_at = None
        if not dry_run:
            assert policy.approval.expires_at is not None
            approval_expiration = datetime.fromisoformat(policy.approval.expires_at)
            retention_expiration = created_at + timedelta(days=policy.scope.retention_days)
            expires_at = min(approval_expiration, retention_expiration).isoformat()
        manifest = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at,
            "approval_fingerprint": policy.fingerprint,
            "reviewer": policy.reviewer,
            "selection_seed": selection_seed,
            "max_records": policy.scope.max_records,
            "max_characters_per_record": policy.scope.max_characters_per_record,
            "retention_days": policy.scope.retention_days,
            "preview_count": len(preview_rows),
            "source_mutation_detected": False,
            "previews": preview_rows,
        }
        checklist = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "reviewer_note_warning": "원문 또는 preview 문장을 reviewer_note에 복사하지 마세요.",
            "items": [
                {
                    "preview_id": row["preview_id"],
                    "pii_detected": None,
                    "sensitive_information_detected": None,
                    "coherent_korean_text": None,
                    "corrupted_text": None,
                    "boilerplate_or_template": None,
                    "duplicate_or_repeated": None,
                    "suitable_for_tokenizer": None,
                    "reviewer_note": None,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "decision": "not_reviewed",
                }
                for row in preview_rows
            ],
        }
        expected_files = preview_files + [
            "preview-manifest.json", "review-checklist.json", "deletion-manifest.json", "run-summary.json",
        ]
        deletion = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at,
            "deletion_required": not dry_run,
            "deleted_at": None,
            "deleted_by": None,
            "files_expected": expected_files,
            "files_deleted": [],
            "deletion_verification_status": "not_due_dry_run" if dry_run else "pending_retention_expiration",
        }
        run_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "mode": mode,
            "status": "dry_run_blocked_pending_approval" if dry_run and policy.approval.status != "approved" else (
                "dry_run_approved_plan" if dry_run else "private_preview_generated"
            ),
            "approval_status": policy.approval.status,
            "candidate_entry_count": len(candidates),
            "entries_selected": len(selected_entries),
            "entries_inspected": len(entry_summaries),
            "entry_summaries": entry_summaries,
            "preview_count": len(preview_rows),
            "total_bytes_read": total_read,
            "full_record_saved": False,
            "metadata_values_saved": False,
            "source_values_saved": False,
            "automatic_redaction_complete_guarantee": False,
            "manual_review_required": True,
            "source_mutation_detected": False,
            "selected_archive_checksums": [
                {
                    "archive_hash": archive_hash,
                    "checksum_before": checksum,
                    "checksum_after": post_checksums[archive_hash],
                    "unchanged": checksum == post_checksums[archive_hash],
                }
                for archive_hash, checksum in sorted(pre_checksums.items())
            ],
            "run_fingerprint": fingerprint,
        }
        _atomic_json(staging / "preview-manifest.json", manifest)
        _atomic_json(staging / "review-checklist.json", checklist)
        _atomic_json(staging / "deletion-manifest.json", deletion)
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
        "run_status": run_summary["status"],
        "dry_run": dry_run,
        "approval_status": policy.approval.status,
        "candidate_entry_count": len(candidates),
        "entries_selected": len(selected_entries),
        "entries_inspected": len(entry_summaries),
        "preview_count": len(preview_rows),
        "total_bytes_read": total_read,
        "source_mutation_detected": False,
        "output_location": "external_analysis_private_review_root",
    }
