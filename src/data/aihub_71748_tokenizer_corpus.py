"""Restricted AIHUB-71748 corpus builder for approved tokenizer development."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
import codecs
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import yaml

from src.data.normalization import normalize_text


DATASET_ID = "AIHUB-71748"
TEXT_FIELD = "data_info[].contents"
APPROVAL_STATUS = "approved_tokenizer_development"
ADAPTER_STATUS = "approved_tokenizer_development_only"
DEFAULT_RECORDS_PER_ARCHIVE = 8_192
DEFAULT_BYTES_PER_ARCHIVE = 20 * 1024 * 1024
DEFAULT_MAX_RECORD_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CorpusBuildConfig:
    records_per_archive: int = DEFAULT_RECORDS_PER_ARCHIVE
    bytes_per_archive: int = DEFAULT_BYTES_PER_ARCHIVE
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES

    def validate(self) -> None:
        if min(self.records_per_archive, self.bytes_per_archive, self.max_record_bytes) <= 0:
            raise ValueError("corpus limits must be positive")


class _QuotaReached(Exception):
    pass


class _DataInfoArrayStream:
    """Expose the root ``data_info`` array as a binary stream without extraction."""

    def __init__(self, source: BinaryIO):
        self.source = source
        self.buffer = bytearray()
        self.found = False
        self.eof = False
        self.depth = 0
        self.in_string = False
        self.escape = False
        self.string_buffer = bytearray()
        self.last_root_key: bytes | None = None
        self.expect_colon = False
        self.expect_array = False

    def _locate(self) -> None:
        while not self.found:
            chunk = self.source.read(64 * 1024)
            if not chunk:
                raise ValueError("root data_info array was not found")
            for index, byte in enumerate(chunk):
                if self.in_string:
                    if self.escape:
                        self.escape = False
                        self.string_buffer.append(byte)
                    elif byte == 0x5C:
                        self.escape = True
                        self.string_buffer.append(byte)
                    elif byte == 0x22:
                        self.in_string = False
                        if self.depth == 1:
                            self.last_root_key = bytes(self.string_buffer)
                            self.expect_colon = self.last_root_key == b"data_info"
                        self.string_buffer.clear()
                    else:
                        self.string_buffer.append(byte)
                    continue
                if byte == 0x22:
                    self.in_string = True
                    self.string_buffer.clear()
                elif byte == 0x7B:
                    self.depth += 1
                elif byte == 0x7D:
                    self.depth -= 1
                elif self.expect_colon:
                    if byte in b" \t\r\n":
                        continue
                    if byte != 0x3A:
                        self.expect_colon = False
                    else:
                        self.expect_colon = False
                        self.expect_array = True
                elif self.expect_array:
                    if byte in b" \t\r\n":
                        continue
                    if byte != 0x5B:
                        raise ValueError("root data_info value is not an array")
                    self.buffer.extend(chunk[index:])
                    self.found = True
                    return

    def read(self, size: int = -1) -> bytes:
        if not self.found:
            self._locate()
        if size < 0:
            return bytes(self.buffer) + self.source.read()
        while len(self.buffer) < size and not self.eof:
            chunk = self.source.read(max(64 * 1024, size - len(self.buffer)))
            if chunk:
                self.buffer.extend(chunk)
            else:
                self.eof = True
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _canonical_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected YAML mapping: {path.name}")
    return value


def resolve_local_paths(local_config: Path) -> tuple[Path, Path]:
    value = _load_yaml(local_config)
    datasets = value.get("datasets")
    if not isinstance(datasets, dict) or not isinstance(datasets.get("entries"), dict):
        raise ValueError("invalid local dataset configuration")
    entry = datasets["entries"].get(DATASET_ID)
    if not isinstance(entry, dict) or not isinstance(entry.get("root"), str):
        raise ValueError(f"missing {DATASET_ID} local mapping")
    external_root = Path(str(datasets.get("external_root"))).resolve()
    dataset_root = (external_root / entry["root"]).resolve()
    if external_root not in dataset_root.parents:
        raise ValueError("dataset root escapes external_root")
    if not dataset_root.is_dir():
        raise ValueError("configured dataset root does not exist")
    return external_root, dataset_root


def _validate_approval(package_manifest: Path) -> dict[str, Any]:
    value = _load_yaml(package_manifest)
    package = value.get("package", {})
    approvals = value.get("approvals", {})
    restrictions = value.get("restrictions", {})
    if package.get("license_status") != "approved_student_noncommercial":
        raise ValueError("student noncommercial license approval is required")
    if approvals.get("tokenizer") != APPROVAL_STATUS:
        raise ValueError("tokenizer development is not approved")
    if approvals.get("adapter_activation") != ADAPTER_STATUS:
        raise ValueError("tokenizer-only adapter activation is not approved")
    for purpose in ("pretraining", "sft", "preference"):
        if approvals.get(purpose) not in {"pending", "not_approved"}:
            raise ValueError(f"unexpected broader approval: {purpose}")
    if restrictions.get("model_training_allowed") is not False:
        raise ValueError("model training must remain blocked")
    return value


def _eligible_archives(dataset_root: Path, checksum_inventory: Path) -> list[dict[str, Any]]:
    inventory = _load_yaml(checksum_inventory)
    rows = inventory.get("files")
    if not isinstance(rows, list):
        raise ValueError("invalid checksum inventory")
    selected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("relative_path"), str):
            raise ValueError("invalid checksum row")
        relative = row["relative_path"]
        parts = Path(relative).parts
        name = str(row.get("file_name", ""))
        if "Training" not in parts or "01.원천데이터" not in parts:
            continue
        if "RLHF" in name or not name.startswith("TS_01."):
            continue
        path = (dataset_root / Path(relative)).resolve()
        if dataset_root not in path.parents or not path.is_file():
            raise ValueError(f"eligible archive missing: {relative}")
        if path.stat().st_size != row.get("size_bytes"):
            raise ValueError(f"archive size mismatch: {relative}")
        selected.append({**row, "path": path})
    if len(selected) != 25:
        raise ValueError(f"expected 25 eligible Training source archives, found {len(selected)}")
    return sorted(selected, key=lambda item: item["relative_path"])


def build_tokenizer_corpus(
    *,
    local_config: Path,
    package_manifest: Path,
    checksum_inventory: Path,
    output_dir: Path,
    config: CorpusBuildConfig,
) -> dict[str, Any]:
    """Build a bounded, source-stratified corpus while keeping source ZIPs immutable."""

    config.validate()
    package = _validate_approval(package_manifest)
    external_root, dataset_root = resolve_local_paths(local_config)
    output = output_dir.resolve()
    if external_root not in output.parents:
        raise ValueError("corpus output must be below configured external_root")
    if output.exists():
        raise ValueError("corpus output already exists")
    archives = _eligible_archives(dataset_root, checksum_inventory)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    if staging.exists():
        raise ValueError("corpus staging path already exists")
    staging.mkdir()
    corpus_path = staging / "corpus.txt"
    source_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    seen_hashes: set[str] = set()
    corpus_hash = hashlib.sha256()
    total_records = total_characters = total_bytes = 0

    try:
        with corpus_path.open("wb") as corpus:
            for archive in archives:
                actual_checksum = _sha256(archive["path"])
                expected_checksum = f"sha256:{archive['sha256']}"
                if actual_checksum != expected_checksum:
                    raise ValueError(f"archive checksum mismatch: {archive['relative_path']}")
                accepted = characters = byte_count = entries_opened = 0
                archive_rejections: Counter[str] = Counter()
                with zipfile.ZipFile(archive["path"]) as zipped:
                    entries = sorted(
                        (item for item in zipped.infolist() if not item.is_dir() and item.filename.lower().endswith(".json")),
                        key=lambda item: item.filename,
                    )
                    for entry in entries:
                        if accepted >= config.records_per_archive or byte_count >= config.bytes_per_archive:
                            break
                        entries_opened += 1
                        with zipped.open(entry) as raw:
                            stream = _DataInfoArrayStream(raw)
                            from scripts.datasets.json_record_stream import RECORD_OK, scan_json_array_records

                            def on_record(event: Any) -> None:
                                nonlocal accepted, characters, byte_count, total_records, total_characters, total_bytes
                                if event.status != RECORD_OK or not isinstance(event.value, dict):
                                    archive_rejections[event.status if event.status != RECORD_OK else "RECORD_NOT_OBJECT"] += 1
                                    return
                                value = event.value.get("contents")
                                if not isinstance(value, str):
                                    archive_rejections["CONTENTS_NOT_STRING"] += 1
                                    return
                                try:
                                    normalized = normalize_text(value)
                                except (UnicodeError, ValueError):
                                    archive_rejections["CONTENTS_INVALID"] += 1
                                    return
                                encoded = normalized.encode("utf-8")
                                digest = hashlib.sha256(encoded).hexdigest()
                                if digest in seen_hashes:
                                    archive_rejections["EXACT_DUPLICATE"] += 1
                                    return
                                payload = encoded + b"\n"
                                if accepted >= config.records_per_archive or byte_count + len(payload) > config.bytes_per_archive:
                                    raise _QuotaReached
                                seen_hashes.add(digest)
                                corpus.write(payload)
                                corpus_hash.update(payload)
                                accepted += 1
                                characters += len(normalized)
                                byte_count += len(payload)
                                total_records += 1
                                total_characters += len(normalized)
                                total_bytes += len(payload)

                            try:
                                scan_json_array_records(
                                    stream,
                                    max_record_bytes=config.max_record_bytes,
                                    max_read_bytes=entry.file_size,
                                    on_record=on_record,
                                )
                            except _QuotaReached:
                                break
                rejection_counts.update(archive_rejections)
                source_rows.append({
                    "archive_relative_path": archive["relative_path"],
                    "archive_size_bytes": archive["size_bytes"],
                    "archive_sha256": expected_checksum,
                    "json_entries_opened": entries_opened,
                    "accepted_records": accepted,
                    "accepted_characters": characters,
                    "corpus_bytes": byte_count,
                    "rejections": dict(sorted(archive_rejections.items())),
                })
            corpus.flush()
            os.fsync(corpus.fileno())

        corpus_checksum = f"sha256:{corpus_hash.hexdigest()}"
        corpus_identity = {
            "dataset_id": DATASET_ID,
            "text_field": TEXT_FIELD,
            "selection": asdict(config),
            "source_inventory_sha256": package["package"]["checksums"]["zip_content_sha256"]["inventory_sha256"],
            "corpus_sha256": corpus_checksum,
            "record_count": total_records,
            "character_count": total_characters,
            "byte_count": total_bytes,
        }
        manifest = {
            "schema_version": "1.0",
            "artifact_kind": "tokenizer_development_corpus",
            "status": APPROVAL_STATUS,
            "created_at": datetime.now(UTC).isoformat(),
            "dataset_id": DATASET_ID,
            "license_status": "approved_student_noncommercial",
            "redistribution": "not_approved",
            "purpose": "operating_16k_tokenizer_development_only",
            "text_field": TEXT_FIELD,
            "included_subset": "Training/01.원천데이터/TS_01.* only",
            "excluded_subsets": ["Validation", "evaluation", "benchmark", "RLHF", "SFT", "instruction", "answer", "label", "role", "metadata"],
            "selection_policy": {**asdict(config), "archive_order": "relative_path_ascending", "record_order": "ZIP entry and data_info array order", "exact_duplicate_policy": "first normalized text hash kept"},
            "normalization": {"unicode": "NFC", "newlines": "LF", "sentencepiece_rule": "identity"},
            "source_manifest_eligible": False,
            "source_manifest_eligibility_note": "Acquisition evidence and provider version remain unresolved; this restricted tokenizer corpus uses the verified ZIP checksum inventory.",
            "archive_count": len(source_rows),
            "record_count": total_records,
            "character_count": total_characters,
            "byte_count": total_bytes,
            "corpus_relative_path": "corpus.txt",
            "corpus_sha256": corpus_checksum,
            "corpus_fingerprint": _canonical_sha256(corpus_identity),
            "source_archives": source_rows,
            "rejections": dict(sorted(rejection_counts.items())),
            "pii_status": "not_cleared_restricted_tokenizer_development_approval",
            "model_training_allowed": False,
        }
        statistics = {
            "schema_version": "1.0",
            "record_count": total_records,
            "character_count": total_characters,
            "byte_count": total_bytes,
            "average_characters_per_record": total_characters / total_records if total_records else 0,
            "average_bytes_per_record": total_bytes / total_records if total_records else 0,
            "archive_count": len(source_rows),
            "rejections": dict(sorted(rejection_counts.items())),
        }
        (staging / "corpus-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        (staging / "corpus-statistics.json").write_text(json.dumps(statistics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(staging, output)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_existing_tokenizer_corpus(
    *,
    local_config: Path,
    package_manifest: Path,
    checksum_inventory: Path,
    corpus_dir: Path,
) -> dict[str, Any]:
    """Revalidate an immutable corpus bundle and every approved source ZIP."""

    package = _validate_approval(package_manifest)
    _, dataset_root = resolve_local_paths(local_config)
    archives = _eligible_archives(dataset_root, checksum_inventory)
    corpus_root = corpus_dir.resolve()
    manifest = json.loads((corpus_root / "corpus-manifest.json").read_text(encoding="utf-8"))
    statistics = json.loads((corpus_root / "corpus-statistics.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(statistics, dict):
        raise ValueError("corpus manifest or statistics is invalid")
    corpus = corpus_root / "corpus.txt"
    if not corpus.is_file() or corpus.stat().st_size != manifest.get("byte_count"):
        raise ValueError("corpus byte count mismatch")
    actual_corpus_sha = _sha256(corpus)
    if actual_corpus_sha != manifest.get("corpus_sha256"):
        raise ValueError("corpus checksum mismatch")
    count_fields = ("record_count", "character_count", "byte_count", "archive_count")
    if any(manifest.get(field) != statistics.get(field) for field in count_fields):
        raise ValueError("corpus manifest and statistics mismatch")
    source_rows = manifest.get("source_archives")
    if not isinstance(source_rows, list) or len(source_rows) != len(archives):
        raise ValueError("corpus source archive count mismatch")
    source_by_path = {row.get("archive_relative_path"): row for row in source_rows if isinstance(row, dict)}
    if sum(int(row.get("accepted_records", 0)) for row in source_rows) != manifest.get("record_count"):
        raise ValueError("corpus source record totals mismatch")
    for archive in archives:
        source = source_by_path.get(archive["relative_path"])
        expected = f"sha256:{archive['sha256']}"
        if source is None or source.get("archive_sha256") != expected:
            raise ValueError(f"corpus source lineage mismatch: {archive['relative_path']}")
        if _sha256(archive["path"]) != expected:
            raise ValueError(f"source ZIP checksum mismatch: {archive['relative_path']}")
    required_exclusions = {"Validation", "evaluation", "benchmark", "RLHF", "SFT", "metadata"}
    if not required_exclusions.issubset(set(manifest.get("excluded_subsets", []))):
        raise ValueError("required corpus exclusions are missing")

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    decoded_character_count = 0
    with corpus.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            decoded_character_count += len(decoder.decode(chunk, final=False))
        decoded_character_count += len(decoder.decode(b"", final=True))
    if decoded_character_count - manifest["record_count"] != manifest["character_count"]:
        raise ValueError("corpus character count mismatch")

    identity = {
        "dataset_id": DATASET_ID,
        "text_field": TEXT_FIELD,
        "selection": {
            "records_per_archive": manifest["selection_policy"]["records_per_archive"],
            "bytes_per_archive": manifest["selection_policy"]["bytes_per_archive"],
            "max_record_bytes": manifest["selection_policy"]["max_record_bytes"],
        },
        "source_inventory_sha256": package["package"]["checksums"]["zip_content_sha256"]["inventory_sha256"],
        "corpus_sha256": actual_corpus_sha,
        "record_count": manifest["record_count"],
        "character_count": manifest["character_count"],
        "byte_count": manifest["byte_count"],
    }
    if _canonical_sha256(identity) != manifest.get("corpus_fingerprint"):
        raise ValueError("corpus fingerprint mismatch")
    return {
        "valid": True,
        "archive_count": len(archives),
        "record_count": manifest["record_count"],
        "character_count": manifest["character_count"],
        "byte_count": manifest["byte_count"],
        "corpus_sha256": actual_corpus_sha,
        "corpus_fingerprint": manifest["corpus_fingerprint"],
        "validation_evaluation_benchmark_used": False,
    }
