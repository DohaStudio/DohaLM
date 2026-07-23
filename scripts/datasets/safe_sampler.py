"""ZIP 원본을 변경하지 않는 제한적이고 안전한 데이터셋 표본 추출기."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import tempfile
import zipfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from .analyzer import (
    AnalyzerConfig,
    AnalyzerError,
    DatasetEntry,
    LABEL_FIELD_NAMES,
    PII_FIELD_NAMES,
    TEXT_FIELD_NAMES,
    detect_field_candidates,
    inventory_dataset,
    profile_schema,
)


DEFAULT_EXTENSIONS = (".json", ".jsonl", ".txt", ".csv", ".tsv")
DEFAULT_SEED = "dohalm-safe-sampler-v1"
SAMPLER_CONTRACT_VERSION = "1.2"
MAX_ENTRY_PATH_LENGTH = 240
MAX_REJECTION_RECORDS = 10_000
SUPPORTED_ZIP_COMPRESSION = frozenset(
    value
    for value in (
        zipfile.ZIP_STORED,
        getattr(zipfile, "ZIP_DEFLATED", None),
        getattr(zipfile, "ZIP_BZIP2", None),
        getattr(zipfile, "ZIP_LZMA", None),
    )
    if value is not None
)
SAFETY_REASON_CODES = {
    "ABSOLUTE_ENTRY_PATH",
    "WINDOWS_DRIVE_PATH",
    "UNC_PATH",
    "PATH_TRAVERSAL",
    "OUTPUT_ESCAPE",
    "NUL_IN_ENTRY_NAME",
    "EMPTY_ENTRY_NAME",
    "SYMLINK_ENTRY",
    "HARDLINK_ENTRY",
    "DEVICE_ENTRY",
    "ENTRY_PATH_TOO_LONG",
}


class SamplerError(AnalyzerError):
    """사용자에게 안전하게 보고할 수 있는 표본 추출 오류."""


@dataclass(frozen=True)
class EntryDecision:
    safe_path: str | None
    reason_code: str | None
    reason_message: str | None


@dataclass(frozen=True)
class Candidate:
    archive_path: Path
    archive_relative_path: str
    archive_id: str
    info: zipfile.ZipInfo
    entry_relative_path: str
    output_relative_path: str
    selection_rank: str


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _zip_extra_has_hardlink_marker(extra: bytes) -> bool:
    """PKWARE UNIX extra field의 link payload를 보수적으로 차단한다."""
    offset = 0
    while offset + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, offset)
        offset += 4
        payload = extra[offset : offset + size]
        offset += size
        if header_id == 0x000D and len(payload) > 12:
            return True
    return False


def _entry_file_type(info: zipfile.ZipInfo) -> int:
    return stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)


def validate_entry_path(name: str, output_root: Path, *, max_length: int = MAX_ENTRY_PATH_LENGTH) -> EntryDecision:
    if not name:
        return EntryDecision(None, "EMPTY_ENTRY_NAME", "entry 이름이 비어 있습니다.")
    if "\x00" in name:
        return EntryDecision(None, "NUL_IN_ENTRY_NAME", "entry 이름에 NUL이 포함돼 있습니다.")
    if len(name) > max_length:
        return EntryDecision(None, "ENTRY_PATH_TOO_LONG", "entry 경로가 허용 길이를 초과합니다.")
    if name.startswith(("//", "\\\\")):
        return EntryDecision(None, "UNC_PATH", "UNC 형태 entry 경로는 허용하지 않습니다.")
    if re.match(r"^[A-Za-z]:[\\/]", name) or PureWindowsPath(name).drive:
        return EntryDecision(None, "WINDOWS_DRIVE_PATH", "Windows drive 경로는 허용하지 않습니다.")
    if name.startswith(("/", "\\")):
        return EntryDecision(None, "ABSOLUTE_ENTRY_PATH", "절대 entry 경로는 허용하지 않습니다.")

    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return EntryDecision(None, "ABSOLUTE_ENTRY_PATH", "절대 entry 경로는 허용하지 않습니다.")
    if any(part == ".." for part in path.parts):
        return EntryDecision(None, "PATH_TRAVERSAL", "상위 경로 이동 요소는 허용하지 않습니다.")
    if not path.parts or any(part in {"", "."} for part in path.parts):
        return EntryDecision(None, "EMPTY_ENTRY_NAME", "정규화할 수 없는 entry 경로입니다.")

    safe_path = path.as_posix()
    candidate = (output_root / Path(*path.parts)).resolve()
    if not _is_within(candidate, output_root.resolve()):
        return EntryDecision(None, "OUTPUT_ESCAPE", "정규화 결과가 출력 root를 벗어납니다.")
    return EntryDecision(safe_path, None, None)


def validate_entry(
    info: zipfile.ZipInfo,
    output_root: Path,
    *,
    allowed_extensions: frozenset[str],
    max_file_bytes: int,
) -> EntryDecision:
    path_decision = validate_entry_path(info.filename, output_root)
    if path_decision.reason_code:
        return path_decision
    if info.is_dir():
        return EntryDecision(None, "DIRECTORY_ENTRY", "디렉터리 entry는 표본 후보가 아닙니다.")

    file_type = _entry_file_type(info)
    if file_type == stat.S_IFLNK:
        return EntryDecision(None, "SYMLINK_ENTRY", "symlink entry는 허용하지 않습니다.")
    if file_type in {stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
        return EntryDecision(None, "DEVICE_ENTRY", "device 또는 특수 파일 entry는 허용하지 않습니다.")
    if file_type not in {0, stat.S_IFREG}:
        return EntryDecision(None, "HARDLINK_ENTRY", "일반 파일로 확인할 수 없는 link entry입니다.")
    if file_type == stat.S_IFREG and _zip_extra_has_hardlink_marker(info.extra):
        return EntryDecision(None, "HARDLINK_ENTRY", "link payload가 있는 UNIX entry는 허용하지 않습니다.")
    if info.flag_bits & 0x1:
        return EntryDecision(None, "ENCRYPTED_ENTRY", "암호화 entry는 자동 추출하지 않습니다.")
    if info.file_size <= 0:
        return EntryDecision(None, "EMPTY_FILE", "빈 파일은 표본 후보가 아닙니다.")
    if info.file_size > max_file_bytes:
        return EntryDecision(None, "ENTRY_TOO_LARGE", "entry 크기가 파일 제한을 초과합니다.")

    safe_path = path_decision.safe_path
    assert safe_path is not None
    suffix = PurePosixPath(safe_path).suffix.lower()
    if suffix not in allowed_extensions:
        return EntryDecision(None, "UNSUPPORTED_EXTENSION", "허용되지 않은 확장자입니다.")
    basename = PurePosixPath(safe_path).name
    if basename.startswith((".", "~")) or basename.endswith((".tmp", ".temp", ".part")) or "__MACOSX" in PurePosixPath(safe_path).parts:
        return EntryDecision(None, "TEMPORARY_ENTRY", "숨김 또는 임시 파일은 표본 후보가 아닙니다.")
    return path_decision


def _archive_id(relative_path: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "-", PurePosixPath(relative_path).stem).strip("-._") or "archive"
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"{stem[:48]}-{digest}"


def _entry_extension(name: str) -> str:
    normalized = name.replace("\\", "/")
    return PurePosixPath(normalized).suffix.lower() or "[none]"


def _sanitized_prefix_preview(name: str) -> str:
    normalized = name.replace("\\", "/")
    if normalized.startswith("//"):
        parts = [part for part in normalized.lstrip("/").split("/") if part]
        server_hash = hashlib.sha256((parts[0] if parts else "").encode("utf-8")).hexdigest()[:12]
        return f"unc/server-hash-{server_hash}"
    normalized = re.sub(r"^[A-Za-z]:", "", normalized).lstrip("/")
    parts = [part for part in normalized.split("/") if part not in {"", ".", ".."}]
    if not parts:
        return "root/[empty]"
    if len(parts) == 1 and PurePosixPath(parts[0]).suffix:
        suffix = PurePosixPath(parts[0]).suffix.lower()
        safe_suffix = re.sub(r"[^0-9a-z.]", "", suffix)[:12] or "unknown"
        return f"root/file-extension-{safe_suffix}"
    component = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", parts[0]).strip("-._")
    if not component:
        component = "component-hash-" + hashlib.sha256(parts[0].encode("utf-8")).hexdigest()[:12]
    return "root/" + component[:48]


def _rejection(
    archive_relative_path: str,
    info: zipfile.ZipInfo | None,
    reason_code: str,
    reason_message: str,
    *,
    safe_path: str | None = None,
) -> dict[str, Any]:
    name = info.filename if info is not None else ""
    row: dict[str, Any] = {
        "archive_relative_path": archive_relative_path,
        "entry_name_hash": _sha256_text(name),
        "entry_extension": _entry_extension(name),
        "entry_size": info.file_size if info is not None else 0,
        "reason_code": reason_code,
        "reason_message": reason_message,
    }
    if safe_path is not None and reason_code not in SAFETY_REASON_CODES:
        row["entry_relative_path"] = safe_path
    elif reason_code in SAFETY_REASON_CODES:
        row["sanitized_prefix_preview"] = _sanitized_prefix_preview(name)
    return row


def _selection_rank(dataset_id: str, archive_relative_path: str, entry_relative_path: str, seed: str) -> str:
    value = "\n".join((seed, dataset_id, archive_relative_path, entry_relative_path))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iter_archives(entry: DatasetEntry, requested_archive: str | None) -> list[Path]:
    if requested_archive is not None:
        normalized = requested_archive.replace("\\", "/")
        path = PurePosixPath(normalized)
        if not path.parts or path.is_absolute() or ".." in path.parts or PureWindowsPath(requested_archive).is_absolute():
            raise SamplerError("archive는 dataset root 기준의 안전한 상대 ZIP 경로여야 합니다.")
        candidate = (entry.root / Path(*path.parts)).resolve()
        if not _is_within(candidate, entry.root.resolve()) or not candidate.is_file() or candidate.suffix.lower() != ".zip":
            raise SamplerError("지정한 archive를 dataset root에서 찾을 수 없습니다.")
        return [candidate]
    return sorted(
        (path for path in entry.root.rglob("*") if path.is_file() and path.suffix.lower() == ".zip"),
        key=lambda path: path.relative_to(entry.root).as_posix(),
    )


def _scan_archives(
    entry: DatasetEntry,
    archives: Iterable[Path],
    *,
    allowed_extensions: frozenset[str],
    max_file_bytes: int,
    selection_seed: str,
) -> tuple[list[Candidate], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    candidates: list[Candidate] = []
    rejections: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    counters = Counter()

    for archive_path in archives:
        archive_relative = archive_path.relative_to(entry.root).as_posix()
        archive_id = _archive_id(archive_relative)
        row: dict[str, Any] = {
            "archive_relative_path": archive_relative,
            "archive_id": archive_id,
            "status": "safe_for_sampling",
            "entries_scanned": 0,
            "entries_safe": 0,
            "entries_rejected": 0,
        }
        safety_rejections = 0
        encrypted_found = False
        unsupported_found = False
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                for info in infos:
                    counters["entries_scanned"] += 1
                    row["entries_scanned"] += 1
                    if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
                        counters["entries_rejected"] += 1
                        row["entries_rejected"] += 1
                        unsupported_found = True
                        if len(rejections) < MAX_REJECTION_RECORDS:
                            rejections.append(_rejection(
                                archive_relative,
                                info,
                                "UNSUPPORTED_ARCHIVE",
                                "지원하지 않는 ZIP 압축 방식입니다.",
                            ))
                        continue
                    output_probe = Path("/") / "isolated" / archive_id
                    decision = validate_entry(
                        info,
                        output_probe,
                        allowed_extensions=allowed_extensions,
                        max_file_bytes=max_file_bytes,
                    )
                    if decision.reason_code:
                        counters["entries_rejected"] += 1
                        row["entries_rejected"] += 1
                        safety_rejections += int(decision.reason_code in SAFETY_REASON_CODES)
                        encrypted_found = encrypted_found or decision.reason_code == "ENCRYPTED_ENTRY"
                        if len(rejections) < MAX_REJECTION_RECORDS:
                            rejections.append(_rejection(
                                archive_relative,
                                info,
                                decision.reason_code,
                                decision.reason_message or "entry가 거부됐습니다.",
                                safe_path=decision.safe_path,
                            ))
                        continue

                    safe_path = decision.safe_path
                    assert safe_path is not None
                    output_relative = PurePosixPath("extracted", archive_id, safe_path).as_posix()
                    candidate = Candidate(
                        archive_path=archive_path,
                        archive_relative_path=archive_relative,
                        archive_id=archive_id,
                        info=info,
                        entry_relative_path=safe_path,
                        output_relative_path=output_relative,
                        selection_rank=_selection_rank(entry.dataset_id, archive_relative, safe_path, selection_seed),
                    )
                    candidates.append(candidate)
                    counters["entries_safe"] += 1
                    row["entries_safe"] += 1
        except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
            row["status"] = "corrupted"
            counters["archives_corrupted"] += 1
            if len(rejections) < MAX_REJECTION_RECORDS:
                rejections.append(_rejection(
                    archive_relative, None, "CORRUPTED_ENTRY", "ZIP 중앙 디렉터리를 안전하게 읽을 수 없습니다."
                ))
            archive_rows.append(row)
            continue

        if encrypted_found:
            row["status"] = "encrypted"
            counters["archives_encrypted"] += 1
        elif (safety_rejections or unsupported_found) and row["entries_safe"]:
            row["status"] = "partially_safe"
            counters["archives_partially_safe"] += 1
        elif unsupported_found:
            row["status"] = "unsupported"
            counters["archives_unsupported"] += 1
        elif safety_rejections and not row["entries_safe"]:
            row["status"] = "unsafe"
            counters["archives_unsafe"] += 1
        else:
            row["status"] = "safe_for_sampling"
            counters["archives_safe"] += 1
        archive_rows.append(row)

    return candidates, rejections, archive_rows, dict(counters)


def _select_candidates(
    candidates: Iterable[Candidate],
    sample_count: int,
    max_total_bytes: int,
    rejections: list[dict[str, Any]],
) -> list[Candidate]:
    by_archive: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_archive[candidate.archive_relative_path].append(candidate)
    for values in by_archive.values():
        values.sort(key=lambda item: (item.selection_rank, item.entry_relative_path))

    ordered: list[Candidate] = []
    for archive_name in sorted(by_archive):
        ordered.append(by_archive[archive_name][0])
    initially_selected = {id(item) for item in ordered}
    ordered.extend(sorted(
        (
            item
            for values in by_archive.values()
            for item in values
            if id(item) not in initially_selected
        ),
        key=lambda item: (item.selection_rank, item.archive_relative_path, item.entry_relative_path),
    ))

    selected: list[Candidate] = []
    outputs: set[str] = set()
    total = 0
    for candidate in ordered:
        if len(selected) >= sample_count:
            break
        if candidate.output_relative_path in outputs:
            rejections.append(_rejection(
                candidate.archive_relative_path,
                candidate.info,
                "DUPLICATE_OUTPUT_PATH",
                "동일 출력 상대 경로가 이미 선택됐습니다.",
                safe_path=candidate.entry_relative_path,
            ))
            continue
        if total + candidate.info.file_size > max_total_bytes:
            rejections.append(_rejection(
                candidate.archive_relative_path,
                candidate.info,
                "TOTAL_LIMIT_EXCEEDED",
                "선택 시 전체 byte 제한을 초과합니다.",
                safe_path=candidate.entry_relative_path,
            ))
            continue
        selected.append(candidate)
        outputs.add(candidate.output_relative_path)
        total += candidate.info.file_size
    return selected


def _canonical_fingerprint(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(rendered)


def safe_sample_output_root(config: AnalyzerConfig, requested: str | Path | None, repository_root: Path) -> Path:
    if requested is None:
        output = (config.external_root / "analysis" / "samples").resolve()
    else:
        raw = str(requested)
        if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            output = Path(raw).resolve()
        else:
            output = (config.external_root / Path(raw)).resolve()
    for dataset in config.entries.values():
        root = dataset.root.resolve()
        if output == root or root in output.parents or output in root.parents:
            raise SamplerError("표본 출력 경로는 원본 dataset 경로와 겹칠 수 없습니다.")
    analysis_root = (config.external_root / "analysis").resolve()
    if output != analysis_root and analysis_root not in output.parents:
        raise SamplerError("표본 출력은 configured external root의 analysis 아래여야 합니다.")
    repository_root = repository_root.resolve()
    if output == repository_root or repository_root in output.parents:
        raise SamplerError("표본을 Git 저장소 안에 기록할 수 없습니다.")
    return output


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _extract_candidate(candidate: Candidate, staging: Path) -> dict[str, Any]:
    destination = (staging / Path(*PurePosixPath(candidate.output_relative_path).parts)).resolve()
    if not _is_within(destination, staging.resolve()):
        raise SamplerError("선택된 표본의 출력 경로가 staging root를 벗어납니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise SamplerError("선택된 표본의 출력 경로가 중복됩니다.")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    byte_count = 0
    checksum = hashlib.sha256()
    crc = 0
    try:
        try:
            with os.fdopen(fd, "wb") as output, zipfile.ZipFile(candidate.archive_path) as archive:
                with archive.open(candidate.info, "r") as source:
                    while chunk := source.read(1024 * 1024):
                        byte_count += len(chunk)
                        if byte_count > candidate.info.file_size:
                            raise SamplerError("추출 byte 수가 중앙 디렉터리 크기를 초과했습니다.")
                        output.write(chunk)
                        checksum.update(chunk)
                        crc = zlib.crc32(chunk, crc)
                output.flush()
                os.fsync(output.fileno())
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise SamplerError("선택한 ZIP entry의 무결성 또는 압축 방식을 검증할 수 없습니다.") from exc
        if byte_count != candidate.info.file_size:
            raise SamplerError("추출 byte 수가 중앙 디렉터리 크기와 다릅니다.")
        if (crc & 0xFFFFFFFF) != candidate.info.CRC:
            raise SamplerError("추출 표본의 CRC 검증에 실패했습니다.")
        temporary.replace(destination)
        if destination.is_symlink() or not destination.is_file():
            raise SamplerError("추출 결과가 일반 파일이 아닙니다.")
        output_checksum = _sha256_file(destination)
        entry_checksum = "sha256:" + checksum.hexdigest()
        if output_checksum != entry_checksum:
            raise SamplerError("추출 표본 checksum이 일치하지 않습니다.")
        return {
            "archive_relative_path": candidate.archive_relative_path,
            "entry_relative_path": candidate.entry_relative_path,
            "output_relative_path": candidate.output_relative_path,
            "extension": PurePosixPath(candidate.entry_relative_path).suffix.lower(),
            "uncompressed_size": candidate.info.file_size,
            "compressed_size": candidate.info.compress_size,
            "crc": candidate.info.CRC,
            "entry_checksum": entry_checksum,
            "output_checksum": output_checksum,
            "selection_rank": candidate.selection_rank,
            "selection_reason": "archive_diversity_then_sha256",
            "schema_status": "pending_profile",
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_header(value: str, index: int) -> str:
    stripped = value.strip()
    if 0 < len(stripped) <= 128 and re.fullmatch(r"[0-9A-Za-z_가-힣.\- ]+", stripped):
        return stripped
    return f"column_{index}_hash_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def _primitive_type(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "empty"
    if re.fullmatch(r"[-+]?\d+", stripped):
        return "integer"
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", stripped):
        return "number"
    if stripped.lower() in {"true", "false"}:
        return "boolean"
    return "string"


def profile_delimited(
    path: Path,
    *,
    delimiter: str,
    max_rows: int = 200,
    max_read_bytes: int = 1024 * 1024,
    max_columns: int = 512,
    max_field_length: int = 64 * 1024,
) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(max_read_bytes + 1)
    truncated = len(raw) > max_read_bytes
    raw = raw[:max_read_bytes]
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return {
            "relative_path": path.name,
            "status": "manual_review_required",
            "encoding_status": "strict_utf8_decode_failed",
            "delimiter": delimiter,
            "rows_sampled": 0,
        }

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        first = next(reader)
    except StopIteration:
        return {
            "relative_path": path.name,
            "status": "empty_file",
            "encoding_status": "strict_utf8",
            "delimiter": delimiter,
            "rows_sampled": 0,
        }
    except csv.Error:
        return {
            "relative_path": path.name,
            "status": "parse_failed",
            "encoding_status": "strict_utf8",
            "delimiter": delimiter,
            "rows_sampled": 0,
        }
    if len(first) > max_columns or any(len(value) > max_field_length for value in first):
        return {
            "relative_path": path.name,
            "status": "limit_exceeded",
            "encoding_status": "strict_utf8",
            "delimiter": delimiter,
            "rows_sampled": 0,
        }

    headers = [_safe_header(value, index) for index, value in enumerate(first)]
    types: list[Counter[str]] = [Counter() for _ in headers]
    rows = 0
    parse_failures = 0
    try:
        for row in reader:
            if rows >= max_rows:
                break
            if len(row) > max_columns or any(len(value) > max_field_length for value in row):
                parse_failures += 1
                continue
            rows += 1
            for index, value in enumerate(row[: len(headers)]):
                types[index][_primitive_type(value)] += 1
    except csv.Error:
        parse_failures += 1

    lower_headers = [value.lower() for value in headers]
    return {
        "relative_path": path.name,
        "status": "profiled" if not parse_failures else "profiled_with_limitations",
        "encoding_status": "strict_utf8",
        "delimiter": delimiter,
        "header_candidates": headers,
        "column_count": len(headers),
        "rows_sampled": rows,
        "truncated_by_byte_limit": truncated,
        "parse_failure_count": parse_failures,
        "column_type_candidates": [dict(sorted(value.items())) for value in types],
        "text_field_candidates": [headers[i] for i, value in enumerate(lower_headers) if value in TEXT_FIELD_NAMES],
        "label_field_candidates": [headers[i] for i, value in enumerate(lower_headers) if value in LABEL_FIELD_NAMES],
        "pii_field_name_warnings": [headers[i] for i, value in enumerate(lower_headers) if value in PII_FIELD_NAMES],
    }


def build_schema_summary(extracted_root: Path, dataset_id: str, sample_count: int, max_file_bytes: int) -> dict[str, Any]:
    if not extracted_root.is_dir():
        return {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "status": "no_samples_extracted",
            "extension_counts": {},
            "parse_failure_count": 0,
            "text_field_candidates": [],
            "label_metadata_candidates": [],
            "pii_field_warnings": [],
            "csv_tsv_profiles": [],
        }

    files = sorted(path for path in extracted_root.rglob("*") if path.is_file())
    extension_counts = dict(sorted(Counter(path.suffix.lower() or "[none]" for path in files).items()))
    profile = profile_schema(
        DatasetEntry(dataset_id, "isolated_samples", extracted_root),
        sample_files=max(sample_count, 1),
        max_json_bytes=max_file_bytes,
    )
    detected = detect_field_candidates(profile)
    delimited_profiles = []
    for path in files:
        if path.suffix.lower() in {".csv", ".tsv"}:
            item = profile_delimited(path, delimiter="," if path.suffix.lower() == ".csv" else "\t")
            item["relative_path"] = path.relative_to(extracted_root).as_posix()
            delimited_profiles.append(item)
    parse_failures = sum(item.get("parse_failure", 0) for item in profile.get("files", []))
    parse_failures += sum(item.get("parse_failure_count", 0) for item in delimited_profiles)
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "status": "profiled" if files else "no_samples_extracted",
        "extension_counts": extension_counts,
        "json_jsonl_txt_profile": profile,
        "csv_tsv_profiles": delimited_profiles,
        "parse_failure_count": parse_failures,
        "text_field_candidates": detected["text_field_candidates"],
        "label_metadata_candidates": detected["label_metadata_candidates"],
        "pii_field_warnings": detected["pii_field_warnings"],
    }


def _manual_review_report(
    archive_rows: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
) -> dict[str, Any]:
    unsafe = [item for item in rejections if item["reason_code"] in SAFETY_REASON_CODES]
    extension_counts = Counter(item["entry_extension"] for item in unsafe)
    prefix_counts = Counter()
    for item in unsafe:
        if item["reason_code"] in {"ABSOLUTE_ENTRY_PATH", "WINDOWS_DRIVE_PATH", "UNC_PATH", "PATH_TRAVERSAL"}:
            prefix_counts[item.get("sanitized_prefix_preview", item["reason_code"])] += 1
    common_prefixes = prefix_counts.most_common(20)
    return {
        "schema_version": "1.0",
        "archive_count": len(archive_rows),
        "unsafe_entry_count": len(unsafe),
        "common_path_prefix_classes": dict(common_prefixes),
        "other_prefix_entry_count": sum(prefix_counts.values()) - sum(count for _, count in common_prefixes),
        "sanitized_prefix_examples": [value for value, _ in common_prefixes[:10]],
        "extension_distribution": dict(sorted(extension_counts.items())),
        "manual_extraction_required": bool(unsafe),
        "automatic_normalization_prohibited": True,
        "automatic_normalization_reason": "위험한 선행 구분자나 상위 이동 요소를 제거하면 원본 경로의 안전 판정을 우회하게 됩니다.",
        "recommended_next_action": "원본을 수정하지 말고 별도 승인된 mapping과 격리 절차를 검토하세요.",
    }


def _write_run_artifacts(
    staging: Path,
    manifest: Mapping[str, Any],
    rejections: list[dict[str, Any]],
    schema_summary: Mapping[str, Any],
    run_summary: Mapping[str, Any],
    manual_review: Mapping[str, Any] | None,
) -> None:
    _atomic_json(staging / "sample-manifest.json", manifest)
    _atomic_json(staging / "rejected-entries.json", {
        "schema_version": "1.0",
        "rejected_entries": rejections,
        "record_count": len(rejections),
        "records_truncated": manifest["rejected_entries_truncated"],
    })
    _atomic_json(staging / "schema-summary.json", schema_summary)
    _atomic_json(staging / "run-summary.json", run_summary)
    if manual_review is not None:
        _atomic_json(staging / "manual-review-required.json", manual_review)


def sample_dataset(
    entry: DatasetEntry,
    output_root: Path,
    *,
    requested_archive: str | None,
    sample_count: int,
    max_file_bytes: int,
    max_total_bytes: int,
    allowed_extensions: Iterable[str],
    dry_run: bool,
    selection_seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    if sample_count <= 0 or max_file_bytes <= 0 or max_total_bytes <= 0:
        raise SamplerError("sample-count와 byte 제한은 0보다 커야 합니다.")
    normalized_extensions = frozenset(
        value.lower() if value.startswith(".") else f".{value.lower()}" for value in allowed_extensions
    )
    if not normalized_extensions or not normalized_extensions.issubset(DEFAULT_EXTENSIONS):
        raise SamplerError("allowed-extensions는 지원되는 text 형식만 포함해야 합니다.")

    before = inventory_dataset(entry)
    archives = _iter_archives(entry, requested_archive)
    candidates, rejections, archive_rows, counters = _scan_archives(
        entry,
        archives,
        allowed_extensions=normalized_extensions,
        max_file_bytes=max_file_bytes,
        selection_seed=selection_seed,
    )
    selected = _select_candidates(candidates, sample_count, max_total_bytes, rejections)
    fingerprint_payload = {
        "schema_version": "1.0",
        "sampler_contract_version": SAMPLER_CONTRACT_VERSION,
        "dataset_id": entry.dataset_id,
        "dataset_relative_root": entry.relative_root,
        "requested_archive": requested_archive,
        "selection_seed": selection_seed,
        "sample_count": sample_count,
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
        "allowed_extensions": sorted(normalized_extensions),
        "dry_run": dry_run,
        "source_inventory_metadata_digest": before["inventory_metadata_digest"],
        "selected": [
            [item.archive_relative_path, item.entry_relative_path, item.info.file_size, item.info.CRC]
            for item in selected
        ],
    }
    run_fingerprint = _canonical_fingerprint(fingerprint_payload)
    run_id = ("dry-" if dry_run else "sample-") + run_fingerprint.removeprefix("sha256:")[:16]
    final = output_root / entry.dataset_id / run_id
    staging = final.with_name(f".{run_id}.staging")
    if final.exists() or staging.exists():
        raise SamplerError("동일한 표본 실행 결과가 이미 존재하여 덮어쓰지 않습니다.")

    extracted_samples: list[dict[str, Any]] = []
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        if not dry_run:
            for candidate in selected:
                extracted_samples.append(_extract_candidate(candidate, staging))
        else:
            extracted_samples = [
                {
                    "archive_relative_path": item.archive_relative_path,
                    "entry_relative_path": item.entry_relative_path,
                    "output_relative_path": item.output_relative_path,
                    "extension": PurePosixPath(item.entry_relative_path).suffix.lower(),
                    "uncompressed_size": item.info.file_size,
                    "compressed_size": item.info.compress_size,
                    "crc": item.info.CRC,
                    "entry_checksum": None,
                    "output_checksum": None,
                    "selection_rank": item.selection_rank,
                    "selection_reason": "archive_diversity_then_sha256",
                    "schema_status": "not_run_dry_run",
                }
                for item in selected
            ]

        after = inventory_dataset(entry)
        source_mutation_detected = before["inventory_metadata_digest"] != after["inventory_metadata_digest"]
        if source_mutation_detected:
            raise SamplerError("표본 처리 중 원본 metadata 변경이 탐지됐습니다.")

        schema_summary = build_schema_summary(
            staging / "extracted",
            entry.dataset_id,
            sample_count,
            max_file_bytes,
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
        samples_by_key = {
            (item["archive_relative_path"], item["entry_relative_path"]): item for item in extracted_samples
        }
        if not dry_run:
            for candidate in selected:
                key = (candidate.archive_relative_path, candidate.entry_relative_path)
                samples_by_key[key]["schema_status"] = schema_summary["status"]

        rejected_total = counters.get("entries_rejected", 0) + max(0, len(rejections) - counters.get("entries_rejected", 0))
        manifest = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source_root": "configured_external_root",
            "dataset_relative_root": entry.relative_root,
            "output_root": "configured_external_analysis_samples",
            "selection_seed": selection_seed,
            "selection_strategy": "archive_diversity_then_sha256",
            "sample_count_requested": sample_count,
            "sample_count_extracted": 0 if dry_run else len(extracted_samples),
            "sample_count_selected": len(selected),
            "total_bytes_extracted": 0 if dry_run else sum(item["uncompressed_size"] for item in extracted_samples),
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "allowed_extensions": sorted(normalized_extensions),
            "archives_scanned": len(archive_rows),
            "archives_safe": sum(item["status"] == "safe_for_sampling" for item in archive_rows),
            "archives_partially_safe": sum(item["status"] == "partially_safe" for item in archive_rows),
            "archives_unsafe": sum(item["status"] == "unsafe" for item in archive_rows),
            "archives_corrupted": sum(item["status"] == "corrupted" for item in archive_rows),
            "archives_encrypted": sum(item["status"] == "encrypted" for item in archive_rows),
            "archives_unsupported": sum(item["status"] == "unsupported" for item in archive_rows),
            "entries_scanned": counters.get("entries_scanned", 0),
            "entries_safe": counters.get("entries_safe", 0),
            "entries_rejected": rejected_total,
            "rejected_entries": rejections,
            "rejected_entries_truncated": counters.get("entries_rejected", 0) > len(rejections),
            "samples": list(samples_by_key.values()),
            "run_fingerprint": run_fingerprint,
            "dry_run": dry_run,
            "source_inventory_metadata_digest": before["inventory_metadata_digest"],
            "source_mutation_detected": False,
            "approval": {
                "candidate_status": "registered",
                "license_review_status": "pending_terms_review",
                "download_status": "not_updated_by_sampler",
                "tokenizer": "pending",
                "pretraining": "pending",
                "sft": "pending",
                "evaluation": "pending",
            },
        }
        manual_review = _manual_review_report(archive_rows, rejections) if manifest["entries_safe"] == 0 else None
        run_summary = {
            "schema_version": "1.0",
            "dataset_id": entry.dataset_id,
            "run_id": run_id,
            "status": "manual_review_required" if not selected else ("dry_run_complete" if dry_run else "sample_extracted"),
            "dry_run": dry_run,
            "sample_count_selected": len(selected),
            "sample_count_extracted": manifest["sample_count_extracted"],
            "entries_rejected": manifest["entries_rejected"],
            "source_mutation_detected": False,
            "schema_status": schema_summary["status"],
            "automatic_unsafe_path_normalization": False,
        }
        _write_run_artifacts(staging, manifest, rejections, schema_summary, run_summary, manual_review)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return {
        "success": True,
        "dataset_id": entry.dataset_id,
        "run_id": run_id,
        "run_status": "manual_review_required" if not selected else ("dry_run_complete" if dry_run else "sample_extracted"),
        "dry_run": dry_run,
        "archives_scanned": len(archive_rows),
        "archives_safe": sum(item["status"] == "safe_for_sampling" for item in archive_rows),
        "archives_partially_safe": sum(item["status"] == "partially_safe" for item in archive_rows),
        "archives_unsafe": sum(item["status"] == "unsafe" for item in archive_rows),
        "archives_unsupported": sum(item["status"] == "unsupported" for item in archive_rows),
        "entries_scanned": counters.get("entries_scanned", 0),
        "entries_safe": counters.get("entries_safe", 0),
        "entries_rejected": manifest["entries_rejected"],
        "samples_selected": len(selected),
        "samples_extracted": manifest["sample_count_extracted"],
        "source_mutation_detected": False,
        "output_location": "external_analysis_samples_root",
        "artifacts": sorted(path.name for path in final.iterdir() if path.is_file()),
    }
