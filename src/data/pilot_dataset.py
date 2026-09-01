"""Prepare a PII-filtered, document-split AIHUB-71748 Pilot dataset."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from src.data.aihub_71748_tokenizer_corpus import (
    CorpusBuildConfig,
    _DataInfoArrayStream,
    _eligible_archives,
)
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.normalization import normalize_text
from src.data.sequence_packing import PackingPolicy, pack_sequences
from src.tokenizer import DohaTokenizer


class PilotDatasetError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


PII_PATTERNS = {
    "email": re.compile(r"(?i)(?<![\w.+-])[\w.+-]{1,64}@[\w.-]{1,253}\.[a-z]{2,24}(?![\w.-])"),
    "phone": re.compile(r"(?<!\d)(?:\+?82[- .]?)?0(?:1[016789]|2|[3-6][1-5])[- .]?\d{3,4}[- .]?\d{4}(?!\d)"),
    "resident_registration": re.compile(r"(?<!\d)\d{6}[- ]?[1-8]\d{6}(?!\d)"),
    "account_number": re.compile(r"(?<!\d)\d{2,6}(?:[- ]\d{2,6}){2,5}(?!\d)"),
    "url": re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>]{3,}"),
    "address_candidate": re.compile(r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[^\n]{0,32}(?:로|길|동|읍|면)\s*\d{1,5}"),
    "user_identifier": re.compile(r"(?i)(?:^|\s)(?:@\w{3,32}|(?:user|account|아이디|닉네임)\s*[:=]\s*\S{2,32})"),
    "name_or_institution_candidate": re.compile(r"(?:성명|이름|기관명|학교명|회사명)\s*[:=]\s*\S{2,40}"),
}


@dataclass(frozen=True)
class PilotDatasetConfig:
    seed: int = 17
    train_percent: int = 95
    context_length: int = 256
    source_corpus_fingerprint: str = "sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c"
    source_corpus_sha256: str = "sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00"
    source_record_count: int = 107_226
    tokenizer_fingerprint: str = "sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff"

    def validate(self) -> None:
        if not 1 <= self.train_percent <= 99 or self.context_length != 256:
            raise PilotDatasetError("PILOT_DATASET_CONFIG_INVALID", "95/5 split과 context 256 계약을 위반했습니다.")


class _QuotaReached(Exception):
    pass


def pii_categories(text: str) -> tuple[str, ...]:
    """Return category names only; detected values never leave this function."""
    return tuple(name for name, pattern in PII_PATTERNS.items() if pattern.search(text))


def _split(document_id: str, seed: int, train_percent: int) -> str:
    material = f"pilot-split-v1\0{seed}\0{document_id}".encode("ascii")
    return "train" if int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 100 < train_percent else "evaluation"


def _iter_source_records(
    dataset_root: Path,
    inventory: Path,
    *,
    legacy_continue_after_byte_quota: bool = False,
    audit_stats: dict[str, Counter[str]] | None = None,
) -> Iterator[dict[str, Any]]:
    from scripts.datasets.json_record_stream import RECORD_OK, scan_json_array_records

    seen: set[str] = set()
    limits = CorpusBuildConfig()
    for archive in _eligible_archives(dataset_root, inventory):
        archive_stats = audit_stats.setdefault(archive["relative_path"], Counter()) if audit_stats is not None else Counter()
        accepted = byte_count = 0
        with zipfile.ZipFile(archive["path"]) as zipped:
            entries = sorted(
                (entry for entry in zipped.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".json")),
                key=lambda entry: entry.filename,
            )
            for entry in entries:
                if accepted >= limits.records_per_archive or byte_count >= limits.bytes_per_archive:
                    break
                with zipped.open(entry) as raw:
                    stream = _DataInfoArrayStream(raw)

                    def on_record(event: Any) -> None:
                        nonlocal accepted, byte_count
                        archive_stats["iterator_events"] += 1
                        if event.status != RECORD_OK or not isinstance(event.value, dict):
                            archive_stats["parser_or_type_excluded"] += 1
                            return
                        archive_stats["raw_candidate_count"] += 1
                        value = event.value.get("contents")
                        if not isinstance(value, str):
                            archive_stats["null_or_type_excluded"] += 1
                            return
                        raw_encoded = value.encode("utf-8")
                        try:
                            text = normalize_text(value)
                        except (UnicodeError, ValueError):
                            archive_stats["normalization_or_empty_excluded"] += 1
                            return
                        encoded = text.encode("utf-8")
                        digest = hashlib.sha256(encoded).hexdigest()
                        payload_bytes = len(encoded) + 1
                        if digest in seen:
                            archive_stats["exact_duplicate_excluded"] += 1
                            return
                        if accepted >= limits.records_per_archive or byte_count + payload_bytes > limits.bytes_per_archive:
                            raise _QuotaReached
                        seen.add(digest)
                        accepted += 1
                        byte_count += payload_bytes
                        archive_stats["accepted_count"] += 1
                        source_material = f"{archive['relative_path']}\0{entry.filename}\0{event.record_index}".encode("utf-8")
                        yield_row.append({
                            "document_id": f"sha256:{digest}",
                            "source_id": f"sha256:{hashlib.sha256(source_material).hexdigest()}",
                            "source_archive": archive["relative_path"],
                            "source_entry": entry.filename,
                            "source_entry_sha256": f"sha256:{hashlib.sha256(entry.filename.encode('utf-8')).hexdigest()}",
                            "source_record_index": event.record_index,
                            "data_file": event.value.get("data_file"),
                            "raw_sha256": f"sha256:{hashlib.sha256(raw_encoded).hexdigest()}",
                            "raw_bytes": len(raw_encoded),
                            "raw_characters": len(value),
                            "normalized_bytes": len(encoded),
                            "normalized_characters": len(text),
                            "whitespace_only": not value.strip(),
                            "text": text,
                        })

                    quota_reached = False
                    try:
                        yield_row: list[dict[str, Any]] = []
                        scan_json_array_records(stream, max_record_bytes=limits.max_record_bytes, max_read_bytes=entry.file_size, on_record=on_record)
                    except _QuotaReached:
                        quota_reached = True
                    yield from yield_row
                    if quota_reached and not legacy_continue_after_byte_quota:
                        break
                    if accepted >= limits.records_per_archive or byte_count >= limits.bytes_per_archive:
                        break


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _write_packed(path: Path, rows: list[list[int]], policy: PackingPolicy) -> tuple[int, int, int]:
    sequences = targets = padding = 0
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in pack_sequences(rows, policy):
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            sequences += 1
            targets += sum(value != policy.ignore_index for value in row["labels"][1:])
            padding += row["attention_mask"].count(0)
    return sequences, targets, padding


def finalize_existing_pilot_dataset(output: Path) -> dict[str, Any]:
    """Verify every published checksum before adding the fail-closed marker."""
    output = output.resolve()
    marker = output / "COMPLETE.json"
    if marker.exists():
        raise PilotDatasetError("PILOT_OUTPUT_COMPLETE", "Pilot dataset은 이미 완료 상태입니다.")
    checksum_path = output / "artifact-checksums.json"
    if not checksum_path.is_file():
        raise PilotDatasetError("PILOT_OUTPUT_INCOMPLETE", "artifact checksum 문서가 없습니다.")
    try:
        manifest = json.loads(checksum_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotDatasetError("PILOT_OUTPUT_INCOMPLETE", "artifact checksum 문서가 유효하지 않습니다.") from exc
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise PilotDatasetError("PILOT_OUTPUT_INCOMPLETE", "artifact checksum 목록이 비었습니다.")
    actual_names = {path.name for path in output.iterdir() if path.is_file()}
    if actual_names != set(expected) | {checksum_path.name}:
        raise PilotDatasetError("PILOT_OUTPUT_INCOMPLETE", "게시된 파일 집합이 checksum 목록과 다릅니다.")
    mismatches = [name for name, digest in expected.items() if file_checksum(output / name) != digest]
    if mismatches:
        raise PilotDatasetError("PILOT_OUTPUT_CHECKSUM_MISMATCH", f"checksum 불일치 파일 수: {len(mismatches)}")
    _write_json(marker, {
        "schema_version": "1.0", "status": "complete",
        "artifact_checksums_sha256": file_checksum(checksum_path),
        "verified_file_count": len(expected),
    })
    return {"status": "complete", "verified_file_count": len(expected), "completion_marker_sha256": file_checksum(marker)}


def verify_existing_pilot_dataset(output: Path) -> dict[str, Any]:
    """Recompute published checksums and identity fingerprints without text output."""
    output = output.resolve()
    if not (output / "COMPLETE.json").is_file():
        raise PilotDatasetError("PILOT_OUTPUT_INCOMPLETE", "Pilot dataset 완료 마커가 없습니다.")
    checksum_document = json.loads((output / "artifact-checksums.json").read_text(encoding="utf-8"))
    expected = checksum_document.get("files", {})
    if not isinstance(expected, dict) or any(file_checksum(output / name) != digest for name, digest in expected.items()):
        raise PilotDatasetError("PILOT_OUTPUT_CHECKSUM_MISMATCH", "Pilot artifact checksum이 일치하지 않습니다.")
    dataset = json.loads((output / "dataset-manifest.json").read_text(encoding="utf-8"))
    split = json.loads((output / "split-manifest.json").read_text(encoding="utf-8"))
    pii = json.loads((output / "pii-review.manifest.json").read_text(encoding="utf-8"))
    tokenization = json.loads((output / "tokenization-manifest.json").read_text(encoding="utf-8"))
    lineage = json.loads((output / "source-lineage.manifest.json").read_text(encoding="utf-8"))
    pii_identity = {key: value for key, value in pii.items() if key != "result_fingerprint"}
    if checksum_value(pii_identity) != pii.get("result_fingerprint"):
        raise PilotDatasetError("PILOT_FINGERPRINT_MISMATCH", "PII result fingerprint가 재현되지 않습니다.")
    split_ids: dict[str, list[str]] = {"train": [], "evaluation": []}
    source_ids: dict[str, set[str]] = {"train": set(), "evaluation": set()}
    for name in split_ids:
        with (output / f"{name}-corpus.jsonl").open("r", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                split_ids[name].append(row["document_id"])
                source_ids[name].add(row["source_id"])
    if set(split_ids["train"]) & set(split_ids["evaluation"]) or source_ids["train"] & source_ids["evaluation"]:
        raise PilotDatasetError("PILOT_SPLIT_LEAKAGE", "재검증에서 split 교차 identity가 발견됐습니다.")
    split_identity = {
        "source_corpus_fingerprint": split["source_corpus_fingerprint"],
        "filtered_corpus_fingerprint": split["filtered_corpus_fingerprint"],
        "seed": split["seed"], "algorithm": "sha256-document-id-v1", "train_percent": split["train_percent"],
        "train_document_ids": sorted(split_ids["train"]), "evaluation_document_ids": sorted(split_ids["evaluation"]),
    }
    if checksum_value(split_identity) != split.get("split_fingerprint"):
        raise PilotDatasetError("PILOT_FINGERPRINT_MISMATCH", "split fingerprint가 재현되지 않습니다.")
    for name in ("train", "evaluation"):
        if tokenization.get("artifacts", {}).get(name) != file_checksum(output / f"{name}.jsonl"):
            raise PilotDatasetError("PILOT_OUTPUT_CHECKSUM_MISMATCH", "tokenization artifact checksum이 일치하지 않습니다.")
    dataset_identity = {
        "split_fingerprint": split["split_fingerprint"], "pii_result_fingerprint": pii["result_fingerprint"],
        "tokenizer_fingerprint": dataset["tokenizer_fingerprint"],
        "train_sha256": file_checksum(output / "train.jsonl"), "evaluation_sha256": file_checksum(output / "evaluation.jsonl"),
    }
    if checksum_value(dataset_identity) != dataset.get("dataset_fingerprint") or lineage.get("status") != "verified":
        raise PilotDatasetError("PILOT_FINGERPRINT_MISMATCH", "dataset 또는 source lineage fingerprint가 재현되지 않습니다.")
    return {
        "status": "verified", "dataset_fingerprint": dataset["dataset_fingerprint"],
        "split_fingerprint": split["split_fingerprint"], "pii_fingerprint": pii["result_fingerprint"],
        "source_corpus_sha256": lineage["source_corpus_sha256"], "source_record_count": lineage["source_record_count"],
        "artifact_file_count": len(expected), "cross_split_document_count": 0, "cross_split_source_id_count": 0,
    }


def audit_aihub_71748_source_lineage(
    *, dataset_root: Path, checksum_inventory: Path, historical_manifest: Path, output: Path
) -> dict[str, Any]:
    """Compare the canonical Gate 3 selector with the superseded Pilot bug."""
    output = output.resolve()
    if output.exists():
        raise PilotDatasetError("PILOT_OUTPUT_EXISTS", "기존 lineage audit을 덮어쓸 수 없습니다.")
    historical = json.loads(historical_manifest.read_text(encoding="utf-8"))

    def collect(*, legacy: bool) -> tuple[dict[str, dict[str, Any]], Counter[str], str, dict[str, Counter[str]]]:
        records: dict[str, dict[str, Any]] = {}
        archive_counts: Counter[str] = Counter()
        audit_stats: dict[str, Counter[str]] = {}
        digest = hashlib.sha256()
        for row in _iter_source_records(
            dataset_root, checksum_inventory, legacy_continue_after_byte_quota=legacy, audit_stats=audit_stats
        ):
            payload = row["text"].encode("utf-8") + b"\n"
            digest.update(payload)
            archive_counts[row["source_archive"]] += 1
            records[row["source_id"]] = {
                key: row[key]
                for key in (
                    "source_id", "source_archive", "source_entry_sha256", "source_record_index",
                    "raw_sha256", "raw_bytes", "raw_characters", "document_id", "normalized_bytes",
                    "normalized_characters", "whitespace_only",
                )
            }
        return records, archive_counts, f"sha256:{digest.hexdigest()}", audit_stats

    canonical, canonical_counts, canonical_sha, canonical_stats = collect(legacy=False)
    legacy, legacy_counts, legacy_sha, legacy_stats = collect(legacy=True)
    historical_rows = {row["archive_relative_path"]: row for row in historical["source_archives"]}
    archive_rows: list[dict[str, Any]] = []
    for archive in sorted(historical_rows):
        source = historical_rows[archive]
        rejections = source.get("rejections", {})
        archive_rows.append({
            "archive_relative_path": archive,
            "historical_raw_candidate_count": int(source["accepted_records"]) + sum(int(value) for value in rejections.values()),
            "canonical_raw_candidate_count": canonical_stats[archive]["raw_candidate_count"],
            "legacy_raw_candidate_count": legacy_stats[archive]["raw_candidate_count"],
            "historical_accepted_count": source["accepted_records"],
            "canonical_accepted_count": canonical_counts[archive],
            "legacy_accepted_count": legacy_counts[archive],
            "canonical_exact_duplicates_removed": canonical_stats[archive]["exact_duplicate_excluded"],
            "legacy_exact_duplicates_removed": legacy_stats[archive]["exact_duplicate_excluded"],
            "canonical_null_or_type_exclusions": canonical_stats[archive]["null_or_type_excluded"],
            "legacy_null_or_type_exclusions": legacy_stats[archive]["null_or_type_excluded"],
            "canonical_normalization_or_empty_exclusions": canonical_stats[archive]["normalization_or_empty_excluded"],
            "legacy_normalization_or_empty_exclusions": legacy_stats[archive]["normalization_or_empty_excluded"],
            "canonical_parser_or_type_exclusions": canonical_stats[archive]["parser_or_type_excluded"],
            "legacy_parser_or_type_exclusions": legacy_stats[archive]["parser_or_type_excluded"],
            "final_count_difference": legacy_counts[archive] - canonical_counts[archive],
            "archive_digest": checksum_value({
                "archive": archive,
                "canonical_source_ids": sorted(key for key, row in canonical.items() if row["source_archive"] == archive),
            }),
        })
    legacy_only_ids = sorted(set(legacy) - set(canonical))
    canonical_only_ids = sorted(set(canonical) - set(legacy))
    differences = [
        {**legacy[record_id], "classification": "pilot_only", "reason_code": "BYTE_QUOTA_EXCEPTION_DID_NOT_STOP_ARCHIVE"}
        for record_id in legacy_only_ids
    ]
    if canonical_only_ids or len(differences) != 48:
        raise PilotDatasetError("SOURCE_LINEAGE_NOT_VERIFIED", "canonical/legacy record 차이를 완전히 분류하지 못했습니다.")
    if len(canonical) != historical.get("record_count") or canonical_sha != historical.get("corpus_sha256"):
        raise PilotDatasetError("SOURCE_LINEAGE_NOT_VERIFIED", "canonical replay가 historical corpus identity와 일치하지 않습니다.")
    if any(row["historical_accepted_count"] != row["canonical_accepted_count"] for row in archive_rows):
        raise PilotDatasetError("SOURCE_LINEAGE_NOT_VERIFIED", "archive별 canonical count가 historical manifest와 일치하지 않습니다.")
    config = {
        "contract_version": "aihub-71748-training-selection-v1",
        "archive_order": "relative_path_ascending",
        "entry_order": "json_filename_ascending",
        "quota_exception_policy": "stop_current_archive",
        "normalization": "NFC_LF_trailing_horizontal_whitespace_removed",
        "deduplication": "global_first_normalized_utf8_sha256_kept",
    }
    manifest = {
        "schema_version": "1.0", "status": "verified", "result": "A_historical_tokenizer_corpus_matches_contract",
        "historical_record_count": len(canonical), "legacy_pilot_record_count": len(legacy), "difference_count": len(differences),
        "classification_counts": {"pilot_only": len(differences)}, "unknown_count": 0,
        "historical_corpus_sha256": canonical_sha, "legacy_replay_sha256": legacy_sha,
        "historical_corpus_fingerprint": historical["corpus_fingerprint"],
        "selection_contract": config, "selection_contract_fingerprint": checksum_value(config),
        "archive_count": len(archive_rows), "differing_archive_count": sum(row["final_count_difference"] != 0 for row in archive_rows),
        "archive_counts": archive_rows, "difference_records_stored_separately": True,
        "actual_text_values_stored": False,
    }
    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        _write_json(staging / "source-lineage.manifest.json", manifest)
        _write_json(staging / "difference-records.manifest.json", {
            "schema_version": "1.0", "record_count": len(differences), "records": differences,
            "classification_counts": {"pilot_only": len(differences)}, "actual_text_values_stored": False,
        })
        checksums = {path.name: file_checksum(path) for path in sorted(staging.iterdir())}
        _write_json(staging / "artifact-checksums.json", {"files": checksums, "fingerprint": checksum_value(checksums)})
        output.mkdir()
        for artifact in sorted(staging.iterdir()):
            os.replace(artifact, output / artifact.name)
        _write_json(output / "COMPLETE.json", {"status": "complete", "artifact_checksums_sha256": file_checksum(output / "artifact-checksums.json")})
        staging.rmdir()
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if output.exists():
            shutil.rmtree(output)
        raise
    return manifest


def prepare_aihub_71748_pilot_dataset(
    *,
    dataset_root: Path,
    checksum_inventory: Path,
    tokenizer_bundle: Path,
    source_corpus_manifest: Path,
    output: Path,
    config: PilotDatasetConfig,
) -> dict[str, Any]:
    config.validate()
    output = output.resolve()
    if output.exists():
        raise PilotDatasetError("PILOT_OUTPUT_EXISTS", "기존 Pilot dataset을 덮어쓸 수 없습니다.")
    tokenizer = DohaTokenizer(tokenizer_bundle / "tokenizer.model")
    if tokenizer.vocab_size != 16_000:
        raise PilotDatasetError("PILOT_TOKENIZER_MISMATCH", "운영 tokenizer vocabulary가 일치하지 않습니다.")
    tokenizer_manifest = json.loads((tokenizer_bundle / "tokenizer-manifest.json").read_text(encoding="utf-8"))
    if tokenizer_manifest.get("tokenizer_fingerprint") != config.tokenizer_fingerprint:
        raise PilotDatasetError("PILOT_TOKENIZER_MISMATCH", "운영 tokenizer fingerprint가 일치하지 않습니다.")

    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        raise PilotDatasetError("PILOT_STAGING_EXISTS", "Pilot staging 경로가 이미 존재합니다.")
    staging.mkdir()
    pii_counts: Counter[str] = Counter()
    counts = Counter()
    split_ids = {"train": set(), "evaluation": set()}
    source_ids = {"train": set(), "evaluation": set()}
    token_rows: dict[str, list[list[int]]] = {"train": [], "evaluation": []}
    stats = {name: Counter() for name in token_rows}
    corpus_digest = hashlib.sha256()
    source_digest = hashlib.sha256()
    source_counts = Counter()
    source_archive_stats: dict[str, Counter[str]] = {}
    try:
        corpus_handles = {
            name: (staging / f"{name}-corpus.jsonl").open("x", encoding="utf-8", newline="\n")
            for name in token_rows
        }
        try:
            for row in _iter_source_records(dataset_root, checksum_inventory, audit_stats=source_archive_stats):
                counts["scanned_records"] += 1
                encoded_text = row["text"].encode("utf-8")
                source_digest.update(encoded_text + b"\n")
                source_counts["records"] += 1
                source_counts["characters"] += len(row["text"])
                source_counts["bytes"] += len(encoded_text) + 1
                counts["scanned_characters"] += len(row["text"])
                counts["scanned_bytes"] += len(encoded_text)
                categories = pii_categories(row["text"])
                if categories:
                    counts["detected_records"] += 1
                    counts["excluded_records"] += 1
                    for category in categories:
                        pii_counts[category] += 1
                    continue
                split = _split(row["document_id"], config.seed, config.train_percent)
                split_ids[split].add(row["document_id"])
                source_ids[split].add(row["source_id"])
                tokenized = tokenizer.encode(row["text"], add_bos=True, add_eos=True).ids
                if not tokenized or any(token < 0 or token >= 16_000 for token in tokenized) or tokenizer.unk_id in tokenized:
                    raise PilotDatasetError("PILOT_TOKENIZATION_INVALID", "empty·UNK·범위 초과 token이 탐지됐습니다.")
                token_rows[split].append(tokenized)
                stats[split]["records"] += 1
                stats[split]["characters"] += len(row["text"])
                stats[split]["bytes"] += len(encoded_text)
                stats[split]["tokens"] += len(tokenized)
                public_row = {"document_id": row["document_id"], "source_id": row["source_id"], "text": row["text"]}
                corpus_handles[split].write(json.dumps(public_row, ensure_ascii=False, sort_keys=True) + "\n")
                corpus_digest.update(len(encoded_text).to_bytes(8, "big"))
                corpus_digest.update(encoded_text)
        finally:
            for handle in corpus_handles.values():
                handle.close()
        if not stats["train"]["records"] or not stats["evaluation"]["records"]:
            raise PilotDatasetError("PILOT_SPLIT_EMPTY", "train/evaluation split이 비었습니다.")
        actual_source_sha = f"sha256:{source_digest.hexdigest()}"
        historical = json.loads(source_corpus_manifest.read_text(encoding="utf-8"))
        if (
            source_counts["records"] != config.source_record_count
            or actual_source_sha != config.source_corpus_sha256
            or historical.get("record_count") != source_counts["records"]
            or historical.get("corpus_sha256") != actual_source_sha
            or historical.get("corpus_fingerprint") != config.source_corpus_fingerprint
        ):
            raise PilotDatasetError("SOURCE_LINEAGE_NOT_VERIFIED", "canonical source replay가 승인 corpus identity와 일치하지 않습니다.")
        historical_counts = {row["archive_relative_path"]: row["accepted_records"] for row in historical["source_archives"]}
        if any(source_archive_stats[path]["accepted_count"] != count for path, count in historical_counts.items()):
            raise PilotDatasetError("SOURCE_LINEAGE_NOT_VERIFIED", "archive별 source count가 승인 corpus와 일치하지 않습니다.")
        cross_documents = split_ids["train"] & split_ids["evaluation"]
        cross_sources = source_ids["train"] & source_ids["evaluation"]
        if cross_documents or cross_sources:
            raise PilotDatasetError("PILOT_SPLIT_LEAKAGE", "document/source identity가 split을 교차합니다.")

        policy = PackingPolicy(context_length=config.context_length, mode="continuous", append_eos=False, remainder="pad")
        packing_results: dict[str, dict[str, int]] = {}
        for split in ("train", "evaluation"):
            sequences, targets, padding = _write_packed(staging / f"{split}.jsonl", token_rows[split], policy)
            packing_results[split] = {"sequences": sequences, "target_tokens": targets, "padding_tokens": padding}

        pii_config = {"pattern_version": "pilot-pii-regex-v1", "categories": sorted(PII_PATTERNS), "action": "exclude_matching_record"}
        pii_manifest = {
            "schema_version": "1.0", "status": "clear_after_automatic_exclusion", "values_stored": False,
            "scanned_records": counts["scanned_records"], "scanned_characters": counts["scanned_characters"],
            "scanned_bytes": counts["scanned_bytes"], "detected_records": counts["detected_records"],
            "excluded_records": counts["excluded_records"], "human_review_required_records": 0,
            "detection_counts": dict(sorted(pii_counts.items())), "fail_closed": True,
            "config_fingerprint": checksum_value(pii_config),
        }
        pii_manifest["result_fingerprint"] = checksum_value(pii_manifest)
        source_fingerprint = f"sha256:{corpus_digest.hexdigest()}"
        split_identity = {
            "source_corpus_fingerprint": config.source_corpus_fingerprint, "filtered_corpus_fingerprint": source_fingerprint,
            "seed": config.seed, "algorithm": "sha256-document-id-v1", "train_percent": config.train_percent,
            "train_document_ids": sorted(split_ids["train"]), "evaluation_document_ids": sorted(split_ids["evaluation"]),
        }
        split_fingerprint = checksum_value(split_identity)
        split_manifest = {
            "schema_version": "1.0", "source_split": "AIHUB-71748 Training only", "original_validation_used": False,
            "seed": config.seed, "train_percent": config.train_percent, "internal_evaluation_percent": 100 - config.train_percent,
            "document_unit": True, "exact_duplicate_cross_split": 0, "source_id_cross_split": 0,
            "source_corpus_fingerprint": config.source_corpus_fingerprint, "filtered_corpus_fingerprint": source_fingerprint,
            "tokenizer_fingerprint": config.tokenizer_fingerprint, "split_fingerprint": split_fingerprint,
            "statistics": {name: dict(stats[name]) for name in stats},
            "evaluation_exclusion": "internal evaluation is never supplied to the training dataloader",
        }
        tokenization_manifest = {
            "schema_version": "1.0", "tokenizer_fingerprint": config.tokenizer_fingerprint, "vocab_size": 16_000,
            "special_token_ids": list(range(8)), "unknown_tokens": 0, "out_of_range_ids": 0, "empty_sequences": 0,
            "bos_id": 2, "eos_id": 3, "split_mixing": False,
            "artifacts": {name: file_checksum(staging / f"{name}.jsonl") for name in token_rows},
        }
        packing_manifest = {
            "schema_version": "1.0", "policy": policy.to_dict(), "split_mixing": False, "results": packing_results,
            "utilization": {name: result["target_tokens"] / max(1, result["sequences"] * config.context_length) for name, result in packing_results.items()},
        }
        dataset_identity = {
            "split_fingerprint": split_fingerprint, "pii_result_fingerprint": pii_manifest["result_fingerprint"],
            "tokenizer_fingerprint": config.tokenizer_fingerprint,
            "train_sha256": file_checksum(staging / "train.jsonl"), "evaluation_sha256": file_checksum(staging / "evaluation.jsonl"),
        }
        dataset_fingerprint = checksum_value(dataset_identity)
        dataset_manifest = {
            "schema_version": "1.0", "status": "approved_pilot_pretraining", "dataset_id": "AIHUB-71748",
            "dataset_version": output.name, "purpose": "pilot_pretraining_max_100_steps_candidate",
            "license_status": "approved_student_noncommercial", "commercial_use": "not_approved", "redistribution": "not_approved",
            "text_field": "data_info[].contents", "metadata_used": False, "source_split": "Training",
            "excluded": ["AIHUB Validation", "evaluation/benchmark", "SFT", "RLHF", "preference", "metadata"],
            "dataset_fingerprint": dataset_fingerprint, "split_fingerprint": split_fingerprint,
            "source_lineage_verified": True,
            "pii_result_fingerprint": pii_manifest["result_fingerprint"], "tokenizer_fingerprint": config.tokenizer_fingerprint,
            "statistics": {name: dict(stats[name]) for name in stats},
            "artifact_checksums": {path.name: file_checksum(path) for path in sorted(staging.iterdir()) if path.is_file()},
            "full_pretraining_allowed": False, "pilot_100_step_execution_allowed": False, "smoke_max_optimizer_steps": 5,
        }
        selection_contract = {
            "version": "aihub-71748-training-selection-v1", "archive_filter": "Training/01.원천데이터/TS_01.* excluding RLHF",
            "archive_order": "relative_path_ascending", "json_entry_order": "filename_ascending",
            "root_array": "data_info", "text_field": "contents", "string_only": True,
            "null_empty_whitespace": "reject", "normalization": "NFC + CRLF/CR to LF + trailing horizontal whitespace per line",
            "leading_whitespace": "preserve", "trailing_newline": "collapse_to_one", "duplicate": "global normalized UTF-8 SHA-256 first kept",
            "duplicate_timing": "after normalization before quota", "quota_exception": "stop current archive",
            "serialization": "normalized UTF-8 bytes plus one LF", "record_identity": "archive+entry+array-index SHA-256",
            "error_handling": "non-object/non-string/normalization/parser errors excluded with aggregate reason",
        }
        source_lineage_manifest = {
            "schema_version": "1.0", "status": "verified", "selection_contract": selection_contract,
            "selection_contract_fingerprint": checksum_value(selection_contract), "source_record_count": source_counts["records"],
            "source_character_count": source_counts["characters"], "source_byte_count": source_counts["bytes"],
            "source_corpus_sha256": actual_source_sha, "source_corpus_fingerprint": config.source_corpus_fingerprint,
            "source_archive_count": len(source_archive_stats),
            "archive_counts": [
                {"archive_relative_path": path, **dict(sorted(values.items()))}
                for path, values in sorted(source_archive_stats.items())
            ],
            "source_zip_checksum_inventory": checksum_inventory.name, "actual_text_values_stored": False,
        }
        for name, value in (("pii-review.manifest.json", pii_manifest), ("split-manifest.json", split_manifest),
                            ("tokenization-manifest.json", tokenization_manifest), ("packing-manifest.json", packing_manifest),
                            ("dataset-manifest.json", dataset_manifest), ("source-lineage.manifest.json", source_lineage_manifest),
                            ("fingerprints.json", {"dataset": dataset_fingerprint, "split": split_fingerprint, "pii": pii_manifest["result_fingerprint"]})):
            _write_json(staging / name, value)
        integrity = {path.name: file_checksum(path) for path in sorted(staging.iterdir()) if path.is_file()}
        _write_json(staging / "artifact-checksums.json", {"schema_version": "1.0", "files": integrity, "fingerprint": checksum_value(integrity)})
        # Windows can deny an otherwise same-volume directory rename while a
        # scanner briefly holds the directory. Publish closed files one by one
        # and write the completion marker last; readers must require it.
        output.mkdir()
        try:
            for artifact in sorted(staging.iterdir(), key=lambda path: path.name):
                os.replace(artifact, output / artifact.name)
            _write_json(output / "COMPLETE.json", {
                "schema_version": "1.0",
                "artifact_checksums_sha256": file_checksum(output / "artifact-checksums.json"),
                "status": "complete",
            })
            staging.rmdir()
        except Exception:
            if output.exists():
                shutil.rmtree(output)
            raise
        return {
            "status": "prepared", "dataset_fingerprint": dataset_fingerprint, "split_fingerprint": split_fingerprint,
            "pii_fingerprint": pii_manifest["result_fingerprint"], "pii": pii_manifest,
            "source_lineage_verified": True, "source_record_count": source_counts["records"],
            "statistics": {name: dict(stats[name]) for name in stats}, "packing": packing_results,
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
