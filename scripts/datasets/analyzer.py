"""AI Hub 데이터셋의 안전한 구조·schema 분석 기능."""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import statistics
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Iterator, Mapping

from src.config.loader import load_yaml


DATASET_IDS = (
    "AIHUB-71748",
    "AIHUB-653",
    "AIHUB-110",
    "AIHUB-86",
    "AIHUB-71477",
)

TEXT_FIELD_NAMES = {
    "text", "content", "sentence", "utterance", "dialogue", "question", "answer",
    "prompt", "response", "document", "paragraph", "title", "body", "original",
    "corrected", "source_text", "target_text", "text_normalized", "문장", "본문",
    "내용", "발화", "질문", "답변", "원문", "교정문", "대화",
}
LABEL_FIELD_NAMES = {
    "label", "labels", "category", "emotion", "intent", "entity", "entities",
    "annotation", "metadata", "speaker", "role", "turn", "score", "preference",
    "reward", "chosen", "rejected",
}
PII_FIELD_NAMES = {
    "name", "person", "phone", "telephone", "email", "address", "resident_number",
    "account", "id_number", "birth", "age", "gender", "hospital", "diagnosis",
    "counseling", "이름", "성명", "전화번호", "이메일", "주소", "주민번호",
    "생년월일", "병원", "진단", "상담",
}

ARCHIVE_SUFFIXES = {".zip", ".7z", ".gz", ".tar"}
INTEREST_SUFFIXES = {
    ".json", ".jsonl", ".txt", ".csv", ".xml", ".zip", ".7z", ".gz",
    ".tar", ".wav", ".mp3", ".pdf", ".xlsx",
}
SPECIAL_PATH_RE = re.compile(r"[^\w\s./\-가-힣]", re.UNICODE)
TRAIN_RE = re.compile(r"(^|[/_.\s\-])(train|training)([/_.\s\-]|$)", re.IGNORECASE)
VALID_RE = re.compile(r"(^|[/_.\s\-])(valid|validation)([/_.\s\-]|$)", re.IGNORECASE)
SOURCE_RE = re.compile(r"원천|source|raw", re.IGNORECASE)
LABEL_RE = re.compile(r"라벨|label|annotation", re.IGNORECASE)


class AnalyzerError(RuntimeError):
    """안전한 사용자 메시지로 변환할 수 있는 분석 오류."""


@dataclass(frozen=True)
class DatasetEntry:
    dataset_id: str
    relative_root: str
    root: Path


@dataclass(frozen=True)
class AnalyzerConfig:
    external_root: Path
    entries: dict[str, DatasetEntry]


def _is_absolute(raw: str) -> bool:
    return PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute()


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise AnalyzerError("분석 경로가 데이터셋 root 밖을 가리킵니다.") from exc


def load_dataset_config(path: str | Path) -> AnalyzerConfig:
    raw = load_yaml(path)
    if set(raw) != {"datasets"} or not isinstance(raw["datasets"], dict):
        raise AnalyzerError("설정 최상위에는 datasets 매핑만 있어야 합니다.")
    datasets = raw["datasets"]
    if set(datasets) != {"external_root", "entries"}:
        raise AnalyzerError("datasets에는 external_root와 entries만 있어야 합니다.")
    external = datasets["external_root"]
    entries_raw = datasets["entries"]
    if not isinstance(external, str) or not _is_absolute(external):
        raise AnalyzerError("external_root는 로컬 절대 경로여야 합니다.")
    if not isinstance(entries_raw, dict) or not entries_raw:
        raise AnalyzerError("entries는 비어 있지 않은 매핑이어야 합니다.")
    external_root = Path(external).resolve()
    if not external_root.is_dir():
        raise AnalyzerError("설정한 external_root가 존재하지 않습니다.")

    entries: dict[str, DatasetEntry] = {}
    for dataset_id, item in entries_raw.items():
        if dataset_id not in DATASET_IDS or not isinstance(item, dict) or set(item) != {"root"}:
            raise AnalyzerError(f"지원하지 않거나 잘못된 dataset entry입니다: {dataset_id}")
        relative = item["root"]
        if not isinstance(relative, str) or _is_absolute(relative) or ".." in PurePosixPath(relative.replace("\\", "/")).parts:
            raise AnalyzerError(f"dataset root는 안전한 상대 경로여야 합니다: {dataset_id}")
        root = (external_root / Path(relative)).resolve()
        if external_root not in root.parents:
            raise AnalyzerError(f"dataset root가 external_root 밖을 가리킵니다: {dataset_id}")
        if not root.is_dir():
            raise AnalyzerError(f"dataset root가 존재하지 않습니다: {dataset_id}")
        entries[dataset_id] = DatasetEntry(dataset_id, PurePosixPath(relative.replace("\\", "/")).as_posix(), root)
    return AnalyzerConfig(external_root, entries)


def _metadata_digest(files: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        stat = path.stat()
        row = f"{_relative_posix(path, root)}\t{stat.st_size}\t{stat.st_mtime_ns}\n"
        digest.update(row.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def inventory_dataset(entry: DatasetEntry) -> dict[str, Any]:
    root = entry.root
    directories = sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda p: _relative_posix(p, root))
    files = sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: _relative_posix(p, root))
    sizes = [path.stat().st_size for path in files]
    relative_files = [_relative_posix(path, root) for path in files]
    top_level = sorted({PurePosixPath(value).parts[0] for value in relative_files})

    extension_rows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for path, relative in zip(files, relative_files, strict=True):
        suffix = path.suffix.lower() or "[none]"
        extension_rows[suffix].append((relative, path.stat().st_size))
    extensions = []
    for suffix in sorted(extension_rows):
        rows = extension_rows[suffix]
        row_sizes = [size for _, size in rows]
        extensions.append({
            "extension": suffix,
            "file_count": len(rows),
            "total_bytes": sum(row_sizes),
            "min_bytes": min(row_sizes),
            "max_bytes": max(row_sizes),
            "representative_paths": [relative for relative, _ in rows[:5]],
        })

    lower_paths = [value.lower() for value in relative_files]
    return {
        "schema_version": "1.0",
        "dataset_id": entry.dataset_id,
        "external_root": "configured_locally",
        "dataset_relative_root": entry.relative_root,
        "directory_count": len(directories),
        "file_count": len(files),
        "total_bytes": sum(sizes),
        "largest_file_bytes": max(sizes, default=0),
        "average_file_bytes": (sum(sizes) / len(sizes)) if sizes else 0.0,
        "top_level_entries": top_level,
        "maximum_path_depth": max((len(PurePosixPath(value).parts) for value in relative_files), default=0),
        "maximum_path_length": max((len(value) for value in relative_files), default=0),
        "contains_korean_path": any(re.search(r"[가-힣]", value) for value in relative_files),
        "contains_space_path": any(" " in value for value in relative_files),
        "contains_special_character_path": any(SPECIAL_PATH_RE.search(value) for value in relative_files),
        "training_candidates": [value for value, lower in zip(relative_files, lower_paths, strict=True) if TRAIN_RE.search(lower)],
        "validation_candidates": [value for value, lower in zip(relative_files, lower_paths, strict=True) if VALID_RE.search(lower)],
        "source_candidates": [value for value in relative_files if SOURCE_RE.search(value)],
        "label_candidates": [value for value in relative_files if LABEL_RE.search(value)],
        "extensions": extensions,
        "inventory_metadata_digest": _metadata_digest(files, root),
    }


def _archive_extension(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    return suffix or "[none]"


def _safe_archive_entry_name(name: str) -> tuple[str, bool]:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    unsafe = (
        PureWindowsPath(name).is_absolute()
        or path.is_absolute()
        or ".." in path.parts
    )
    if unsafe:
        return "[unsafe-archive-entry-path]", True
    return path.as_posix(), False


def inspect_archives(entry: DatasetEntry) -> dict[str, Any]:
    archives = []
    unsupported = []
    for path in sorted((item for item in entry.root.rglob("*") if item.is_file()), key=lambda p: _relative_posix(p, entry.root)):
        suffix = path.suffix.lower()
        if suffix not in ARCHIVE_SUFFIXES and not re.search(r"\.(z\d{2}|zip\.\d{3})$", path.name.lower()):
            continue
        relative = _relative_posix(path, entry.root)
        split_suspected = bool(re.search(r"\.(z\d{2}|zip\.\d{3})$", path.name.lower()))
        if suffix != ".zip":
            unsupported.append({
                "archive_relative_path": relative,
                "archive_bytes": path.stat().st_size,
                "status": "unsupported_archive",
                "split_archive_suspected": split_suspected,
            })
            continue
        row: dict[str, Any] = {
            "archive_relative_path": relative,
            "archive_bytes": path.stat().st_size,
            "status": "ok",
            "split_archive_suspected": split_suspected,
        }
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                files = [info for info in infos if not info.is_dir()]
                extensions = Counter(_archive_extension(info.filename) for info in files)
                safe_names = [_safe_archive_entry_name(info.filename) for info in infos if info.filename]
                safe_file_names = [_safe_archive_entry_name(info.filename) for info in files]
                top_level = sorted({PurePosixPath(name).parts[0] for name, _ in safe_names})
                row.update({
                    "entry_count": len(infos),
                    "file_entry_count": len(files),
                    "uncompressed_bytes": sum(info.file_size for info in files),
                    "compressed_bytes": sum(info.compress_size for info in files),
                    "entry_extensions": dict(sorted(extensions.items())),
                    "top_level_entries": top_level[:50],
                    "unsafe_entry_path_count": sum(unsafe for _, unsafe in safe_names),
                    "encrypted": any(bool(info.flag_bits & 0x1) for info in infos),
                    "training_entry_count": sum(bool(TRAIN_RE.search(info.filename)) for info in infos),
                    "validation_entry_count": sum(bool(VALID_RE.search(info.filename)) for info in infos),
                    "source_entry_count": sum(bool(SOURCE_RE.search(info.filename)) for info in infos),
                    "label_entry_count": sum(bool(LABEL_RE.search(info.filename)) for info in infos),
                    "representative_entry_paths": sorted({name for name, _ in safe_file_names})[:20],
                })
        except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            row.update({"status": "archive_read_failed", "error_type": type(exc).__name__})
        archives.append(row)
    return {
        "schema_version": "1.0",
        "dataset_id": entry.dataset_id,
        "archives": archives,
        "unsupported_archives": unsupported,
    }


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
    return type(value).__name__


def _script_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for char in text:
        if "가" <= char <= "힣" or "ㄱ" <= char <= "ㅣ":
            counts["korean"] += 1
        elif char.isascii() and char.isalpha():
            counts["latin"] += 1
        elif char.isdigit():
            counts["digit"] += 1
        elif char.isspace():
            counts["whitespace"] += 1
        else:
            counts["other"] += 1
    return counts


def _field_name(path: str) -> str:
    segment = path.rsplit(".", 1)[-1]
    return re.sub(r"\[\]$", "", segment).lower()


class SchemaAccumulator:
    def __init__(self) -> None:
        self.root_types: Counter[str] = Counter()
        self.fields: dict[str, dict[str, Any]] = {}
        self.schema_signatures: Counter[str] = Counter()
        self.object_count = 0
        self.array_lengths: dict[str, list[int]] = defaultdict(list)

    def add(self, value: Any) -> None:
        self.root_types[_value_type(value)] += 1
        signature = self._walk(value, "$")
        self.schema_signatures[signature] += 1

    def _walk(self, value: Any, path: str) -> str:
        kind = _value_type(value)
        if isinstance(value, dict):
            self.object_count += 1
            children = []
            for key in sorted(value, key=str):
                child_path = f"{path}.{key}"
                children.append(f"{key}:{self._walk(value[key], child_path)}")
            return "{" + ",".join(children) + "}"
        if isinstance(value, list):
            self.array_lengths[path].append(len(value))
            child_signatures = sorted({self._walk(item, f"{path}[]") for item in value[:100]})
            return "[" + "|".join(child_signatures) + "]"
        row = self.fields.setdefault(path, {
            "path": path, "occurrences": 0, "types": Counter(), "null_count": 0,
            "string_count": 0, "string_lengths": [], "korean_string_count": 0,
            "newline_string_count": 0, "script_counts": Counter(), "value_hash_examples": [],
        })
        row["occurrences"] += 1
        row["types"][kind] += 1
        if value is None:
            row["null_count"] += 1
        elif isinstance(value, str):
            row["string_count"] += 1
            row["string_lengths"].append(len(value))
            scripts = _script_counts(value)
            row["script_counts"].update(scripts)
            if scripts["korean"]:
                row["korean_string_count"] += 1
            if "\n" in value or "\r" in value:
                row["newline_string_count"] += 1
            if len(row["value_hash_examples"]) < 3:
                row["value_hash_examples"].append("sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest())
        return kind

    def to_dict(self) -> dict[str, Any]:
        fields = []
        for path in sorted(self.fields):
            row = self.fields[path]
            lengths = row["string_lengths"]
            occurrences = row["occurrences"]
            string_count = row["string_count"]
            fields.append({
                "path": path,
                "occurrences": occurrences,
                "types": dict(sorted(row["types"].items())),
                "null_ratio": row["null_count"] / occurrences if occurrences else 0.0,
                "string_ratio": string_count / occurrences if occurrences else 0.0,
                "average_string_length": statistics.fmean(lengths) if lengths else 0.0,
                "maximum_string_length": max(lengths, default=0),
                "korean_string_ratio": row["korean_string_count"] / string_count if string_count else 0.0,
                "newline_string_ratio": row["newline_string_count"] / string_count if string_count else 0.0,
                "script_counts": dict(sorted(row["script_counts"].items())),
                "value_hash_examples": row["value_hash_examples"],
            })
        arrays = []
        for path, values in sorted(self.array_lengths.items()):
            arrays.append({
                "path": path, "samples": len(values), "minimum": min(values),
                "maximum": max(values), "average": statistics.fmean(values),
            })
        return {
            "root_types": dict(sorted(self.root_types.items())),
            "object_count": self.object_count,
            "array_lengths": arrays,
            "fields": fields,
            "schema_signatures": [
                {"signature_sha256": "sha256:" + hashlib.sha256(signature.encode("utf-8")).hexdigest(), "count": count}
                for signature, count in sorted(self.schema_signatures.items())
            ],
        }


def _iter_json_records(path: Path, max_bytes: int, max_records: int) -> tuple[Iterator[Any], dict[str, Any]]:
    metadata = {"parse_success": 0, "parse_failure": 0, "empty_lines": 0, "bytes_read": 0, "skipped_reason": None}
    if path.stat().st_size > max_bytes:
        metadata["skipped_reason"] = "file_exceeds_max_json_bytes"
        return iter(()), metadata
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        metadata["parse_failure"] = 1
        return iter(()), metadata
    metadata["bytes_read"] = path.stat().st_size
    if isinstance(value, list):
        records = value[:max_records]
    else:
        records = [value]
    metadata["parse_success"] = len(records)
    return iter(records), metadata


def _iter_jsonl_records(path: Path, max_bytes: int, max_records: int, max_line_bytes: int) -> tuple[Iterator[Any], dict[str, Any]]:
    metadata = {"parse_success": 0, "parse_failure": 0, "empty_lines": 0, "bytes_read": 0, "line_too_long": 0, "skipped_reason": None}
    records: list[Any] = []
    try:
        with path.open("rb") as handle:
            while len(records) < max_records and metadata["bytes_read"] < max_bytes:
                line = handle.readline(max_line_bytes + 1)
                if not line:
                    break
                metadata["bytes_read"] += len(line)
                if len(line) > max_line_bytes:
                    metadata["line_too_long"] += 1
                    continue
                if not line.strip():
                    metadata["empty_lines"] += 1
                    continue
                try:
                    value = json.loads(line.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    metadata["parse_failure"] += 1
                    continue
                records.append(value)
                metadata["parse_success"] += 1
    except OSError:
        metadata["skipped_reason"] = "file_read_failed"
    return iter(records), metadata


def profile_txt(path: Path) -> dict[str, Any]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    byte_count = 0
    char_count = 0
    line_count = 0
    current_line = 0
    max_line = 0
    scripts: Counter[str] = Counter()
    controls = 0
    nul = False
    decode_error = False
    bom = False
    try:
        with path.open("rb") as handle:
            first = True
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                if first:
                    bom = chunk.startswith(codecs.BOM_UTF8)
                    first = False
                byte_count += len(chunk)
                try:
                    text = decoder.decode(chunk)
                except UnicodeDecodeError:
                    decode_error = True
                    break
                for char in text:
                    char_count += 1
                    scripts.update(_script_counts(char))
                    nul = nul or char == "\x00"
                    controls += int(ord(char) < 32 and char not in "\t\r\n")
                    if char == "\n":
                        line_count += 1
                        max_line = max(max_line, current_line)
                        current_line = 0
                    elif char != "\r":
                        current_line += 1
            if not decode_error:
                tail = decoder.decode(b"", final=True)
                char_count += len(tail)
                scripts.update(_script_counts(tail))
                current_line += len(tail.replace("\r", ""))
    except OSError:
        return {"status": "file_read_failed"}
    if decode_error:
        return {
            "status": "manual_review_required",
            "strict_utf8_decode": False,
            "encoding_note": "strict UTF-8 decode failed; encoding requires manual review",
            "byte_count": path.stat().st_size,
            "bom": bom,
        }
    if byte_count > 0:
        line_count += 1
        max_line = max(max_line, current_line)
    return {
        "status": "profiled",
        "strict_utf8_decode": True,
        "bom": bom,
        "line_count": line_count,
        "character_count": char_count,
        "byte_count": byte_count,
        "average_line_length": char_count / line_count if line_count else 0.0,
        "maximum_line_length": max_line,
        "script_counts": dict(sorted(scripts.items())),
        "control_character_count": controls,
        "contains_nul": nul,
    }


def profile_schema(entry: DatasetEntry, *, sample_files: int, max_json_bytes: int, max_records: int = 200, max_line_bytes: int = 1024 * 1024) -> dict[str, Any]:
    candidates = sorted(
        (path for path in entry.root.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".txt"}),
        key=lambda p: _relative_posix(p, entry.root),
    )[:sample_files]
    accumulator = SchemaAccumulator()
    files = []
    txt_profiles = []
    for path in candidates:
        relative = _relative_posix(path, entry.root)
        suffix = path.suffix.lower()
        if suffix == ".txt":
            txt_profiles.append({"relative_path": relative, **profile_txt(path)})
            continue
        if suffix == ".json":
            records, metadata = _iter_json_records(path, max_json_bytes, max_records)
        else:
            records, metadata = _iter_jsonl_records(path, max_json_bytes, max_records, max_line_bytes)
        for value in records:
            accumulator.add(value)
        files.append({"relative_path": relative, "format": suffix[1:], **metadata})
    result = accumulator.to_dict()
    if not candidates:
        profile_status = "no_direct_sample_files"
    elif any(item.get("parse_failure", 0) or item.get("skipped_reason") for item in files) or any(
        item.get("status") != "profiled" for item in txt_profiles
    ):
        profile_status = "profiled_with_limitations"
    else:
        profile_status = "profiled"
    result.update({
        "schema_version": "1.0",
        "dataset_id": entry.dataset_id,
        "status": profile_status,
        "sample_strategy": "relative_path_sorted",
        "sample_file_limit": sample_files,
        "max_json_bytes": max_json_bytes,
        "files": files,
        "txt_files": txt_profiles,
        "archive_content_sampled": False,
    })
    return result


def detect_field_candidates(schema: Mapping[str, Any]) -> dict[str, Any]:
    text = []
    labels = []
    pii = []
    for field in schema.get("fields", []):
        name = _field_name(field["path"])
        if name in TEXT_FIELD_NAMES:
            score = field["string_ratio"] * 0.4 + min(field["average_string_length"] / 100.0, 1.0) * 0.3 + field["korean_string_ratio"] * 0.3
            if field["string_ratio"] < 0.5:
                status = "not_recommended"
            elif score >= 0.75:
                status = "likely_candidate"
            elif score >= 0.4:
                status = "candidate"
            else:
                status = "manual_review_required"
            text.append({
                "path": field["path"], "status": status, "string_ratio": field["string_ratio"],
                "average_string_length": field["average_string_length"],
                "korean_string_ratio": field["korean_string_ratio"], "null_ratio": field["null_ratio"],
            })
        if name in LABEL_FIELD_NAMES:
            labels.append({"path": field["path"], "classification": "label_or_metadata", "tokenizer_warning": "exclude_from_text_corpus"})
        if name in PII_FIELD_NAMES:
            pii.append({"path": field["path"], "status": "pii_field_name_detected", "action": "manual_review_required"})
    return {
        "text_field_candidates": sorted(text, key=lambda item: item["path"]),
        "label_metadata_candidates": sorted(labels, key=lambda item: item["path"]),
        "pii_field_warnings": sorted(pii, key=lambda item: item["path"]),
    }


def _purpose_hints(dataset_id: str, inventory: Mapping[str, Any], archive: Mapping[str, Any]) -> dict[str, Any]:
    names = []
    for item in archive["archives"]:
        names.extend(item.get("top_level_entries", []))
        names.extend(item.get("representative_entry_paths", []))
    joined = "\n".join(names).lower()
    common = {
        "automatic_decision": False,
        "approval_effect": "none",
        "training_structure_detected": bool(inventory["training_candidates"]) or any(item.get("training_entry_count", 0) for item in archive["archives"]),
        "validation_structure_detected": bool(inventory["validation_candidates"]) or any(item.get("validation_entry_count", 0) for item in archive["archives"]),
        "source_structure_detected": bool(inventory["source_candidates"]) or any(item.get("source_entry_count", 0) for item in archive["archives"]),
        "label_structure_detected": bool(inventory["label_candidates"]) or any(item.get("label_entry_count", 0) for item in archive["archives"]),
    }
    patterns = {
        "AIHUB-71748": ["general", "sft", "reward", "ppo", "preference", "evaluation"],
        "AIHUB-653": ["원천", "라벨", "training", "validation", "도서"],
        "AIHUB-110": ["법령", "판례", "특허", "논문", "개체명", "ner"],
        "AIHUB-86": ["training_221115_add", "validation_221115_add", "원천", "라벨", "음성", "감정"],
        "AIHUB-71477": ["원문", "오류", "교정", "과교정", "정상", "평가", "training", "validation"],
    }
    common["name_hints"] = {name: (name.lower() in joined) for name in patterns[dataset_id]}
    common["manual_review_required"] = True
    return common


def analyze_dataset(entry: DatasetEntry, *, sample_files: int, max_json_bytes: int, inventory_only: bool) -> dict[str, Any]:
    before = inventory_dataset(entry)
    archives = inspect_archives(entry)
    schema = {
        "schema_version": "1.0", "dataset_id": entry.dataset_id,
        "status": "not_run_inventory_only", "fields": [], "txt_files": [],
        "archive_content_sampled": False,
    } if inventory_only else profile_schema(entry, sample_files=sample_files, max_json_bytes=max_json_bytes)
    fields = detect_field_candidates(schema)
    after = inventory_dataset(entry)
    if before["inventory_metadata_digest"] != after["inventory_metadata_digest"]:
        raise AnalyzerError(f"분석 중 원본 metadata가 변경되었습니다: {entry.dataset_id}")
    return {
        "schema_version": "1.0",
        "dataset_id": entry.dataset_id,
        "analysis_mode": "inventory_only" if inventory_only else "quick_profile",
        "external_root": "configured_locally",
        "dataset_relative_root": entry.relative_root,
        "source_mutation_detected": False,
        "inventory": before,
        "archive_inventory": archives,
        "schema_profile": schema,
        "field_candidates": fields,
        "purpose_hints": _purpose_hints(entry.dataset_id, before, archives),
        "approval": {
            "candidate_status": "registered",
            "license_review_status": "pending_terms_review",
            "download_status": "not_updated_by_analyzer",
            "tokenizer": "pending",
            "pretraining": "pending",
            "sft": "pending",
            "evaluation": "pending",
        },
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _format_bytes(value: int | float) -> str:
    number = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.2f} {unit}"
        number /= 1024
    return f"{number:.2f} TiB"


def render_markdown(report: Mapping[str, Any]) -> str:
    dataset_id = report["dataset_id"]
    inventory = report["inventory"]
    archives = report["archive_inventory"]["archives"]
    schema = report["schema_profile"]
    fields = report["field_candidates"]
    ext_rows = "\n".join(
        f"| `{item['extension']}` | {item['file_count']} | {_format_bytes(item['total_bytes'])} |"
        for item in inventory["extensions"]
    ) or "| — | 0 | 0 B |"
    archive_ok = sum(item["status"] == "ok" for item in archives)
    archive_failed = sum(item["status"] != "ok" for item in archives)
    text_rows = "\n".join(
        f"| `{item['path']}` | `{item['status']}` | {item['average_string_length']:.2f} | {item['korean_string_ratio']:.4f} |"
        for item in fields["text_field_candidates"]
    ) or "| — | `manual_review_required` | — | — |"
    label_rows = "\n".join(
        f"| `{item['path']}` | `{item['classification']}` | `{item['tokenizer_warning']}` |"
        for item in fields["label_metadata_candidates"]
    ) or "| — | 미탐지 | 수동 검토 필요 |"
    pii_rows = "\n".join(
        f"| `{item['path']}` | `{item['status']}` | `{item['action']}` |"
        for item in fields["pii_field_warnings"]
    ) or "| — | 미탐지 | 이름 미탐지는 PII 부재를 의미하지 않음 |"
    schema_status = schema.get("status", "unknown")
    return f"""# {dataset_id} 구조 분석

## 문서 상태

- 문서 상태: `review`
- 마지막 분석일: 2026-07-23
- 분석 모드: `{report['analysis_mode']}`
- [확정] 자동 구조 분석은 데이터 사용 승인이 아니다.

## 분석 기준

- [확정] 외부 원본은 읽기 전용으로 취급했다.
- [확정] ZIP은 중앙 디렉터리만 조회하고 압축을 해제하거나 entry 내용을 읽지 않았다.
- [확정] 원문 문자열은 이 문서에 기록하지 않았다.

## 데이터셋 개요

- Dataset ID: `{dataset_id}`
- 자동 용도 판정: 수행하지 않음

## 외부 상대 경로

- `external_root: configured_locally`
- `dataset_relative_root: {report['dataset_relative_root']}`

## 분석 시점

- 2026-07-23

## 파일·용량 요약

| 폴더 수 | 파일 수 | 총 용량 | 최대 파일 | 평균 파일 |
|---:|---:|---:|---:|---:|
| {inventory['directory_count']} | {inventory['file_count']} | {_format_bytes(inventory['total_bytes'])} | {_format_bytes(inventory['largest_file_bytes'])} | {_format_bytes(inventory['average_file_bytes'])} |

## 최상위 디렉터리

{', '.join(f'`{value}`' for value in inventory['top_level_entries']) or '없음'}

## 경로 구조

- 최대 깊이: {inventory['maximum_path_depth']}
- 최대 상대경로 길이: {inventory['maximum_path_length']}
- 한글/공백/특수문자 경로: {inventory['contains_korean_path']} / {inventory['contains_space_path']} / {inventory['contains_special_character_path']}

## 확장자 분포

| 확장자 | 파일 수 | 총 용량 |
|---|---:|---:|
{ext_rows}

## 압축파일 현황

- 정상 조회: {archive_ok}
- 실패 또는 미지원: {archive_failed + len(report['archive_inventory']['unsupported_archives'])}
- entry 내용 조회·압축 해제: 0건

## Training·Validation 구조

- Training 후보 탐지: `{report['purpose_hints']['training_structure_detected']}`
- Validation 후보 탐지: `{report['purpose_hints']['validation_structure_detected']}`
- [검증 필요] 경로명만으로 실제 용도를 확정하지 않는다.

## 원천·라벨 구조

- 원천 후보 탐지: `{report['purpose_hints']['source_structure_detected']}`
- 라벨 후보 탐지: `{report['purpose_hints']['label_structure_detected']}`

## JSON schema signature

- 상태: `{schema_status}`
- schema signature 수: {len(schema.get('schema_signatures', []))}
- [검증 필요] ZIP 내부 내용은 읽지 않았으므로 압축 내부 JSON schema는 미확인이다.

## JSONL 구조

- 직접 접근 가능한 JSONL 표본 수: {sum(item.get('format') == 'jsonl' for item in schema.get('files', []))}

## TXT 구조

- 직접 접근 가능한 TXT 표본 수: {len(schema.get('txt_files', []))}

## Text field 후보

| field path | 상태 | 평균 길이 | 한글 문자열 비율 |
|---|---|---:|---:|
{text_rows}

## Label·metadata field 후보

| field path | 분류 | Tokenizer 경고 |
|---|---|---|
{label_rows}

## PII 가능 field 경고

| field path | 상태 | 조치 |
|---|---|---|
{pii_rows}

## Tokenizer 적합성

- 상태: `manual_review_required`
- [검증 필요] text field, 라이선스, PII와 평가 제외 조건을 수동 확인해야 한다.

## Pretraining 적합성

- 상태: `manual_review_required`
- [검증 필요] 원천·오류·라벨·평가 subset을 분리해야 한다.

## SFT·Preference 적합성

- 상태: `manual_review_required`
- [검증 필요] 대화 role, preference pair와 label schema를 수동 확인해야 한다.

## Evaluation 제외 후보

- 상태: `manual_review_required`
- [검증 필요] Validation, 평가, 교정 정답과 공개 QA subset을 학습에서 분리해야 한다.

## 수동 검토 필요 항목

- ZIP별 공식 용도·subset mapping
- JSON/TXT schema와 실제 text field
- 개인정보·민감정보와 원천 권리
- tokenizer·pretraining·SFT·evaluation 목적별 승인

## 현재 승인 상태

- `candidate_status: registered`
- `license_review_status: pending_terms_review`
- `download_status: not_updated_by_analyzer`
- `approval.tokenizer/pretraining/sft/evaluation: pending`

## 다음 작업

1. 공식 약관·다운로드 계보와 로컬 package 출처를 사용자 검토한다.
2. ZIP 내용을 자동 분석하지 않고 승인된 수동 표본 검토 절차를 별도로 결정한다.
3. 승인 상태 변경 없이 text·label·평가 subset mapping을 작성한다.
"""


def write_reports(report: Mapping[str, Any], output_root: Path) -> list[Path]:
    dataset_dir = output_root / report["dataset_id"]
    artifacts = {
        "inventory.json": report["inventory"],
        "archive-inventory.json": report["archive_inventory"],
        "schema-profile.json": report["schema_profile"],
        "text-field-candidates.json": report["field_candidates"],
        "dataset-analysis.json": report,
    }
    written = []
    for name, value in artifacts.items():
        path = dataset_dir / name
        _atomic_json(path, value)
        written.append(path)
    markdown = dataset_dir / "dataset-analysis.md"
    markdown.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    written.append(markdown)
    return written


def safe_output_root(config: AnalyzerConfig, requested: str | Path | None, repository_root: Path) -> Path:
    if requested is None:
        output = (config.external_root / "analysis").resolve()
    else:
        raw = str(requested)
        output = Path(raw).resolve() if _is_absolute(raw) else (config.external_root / Path(raw)).resolve()
    for entry in config.entries.values():
        if output == entry.root or entry.root in output.parents or output in entry.root.parents:
            raise AnalyzerError("분석 출력 경로는 원본 dataset 경로와 겹칠 수 없습니다.")
    repository_root = repository_root.resolve()
    if output == repository_root or repository_root in output.parents:
        raise AnalyzerError("로컬 분석 산출물은 Git 저장소 밖에 기록해야 합니다.")
    return output
