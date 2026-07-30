"""Bounded streaming reader for the AIHUB-71748 SFT ZIP components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Iterator
import unicodedata
import zipfile

from src.data.aihub_71748_join import JoinIntegrityError, _iter_data_info


class AIHub71748ReaderError(RuntimeError):
    """Reader failure carrying only a fixed error code."""


@dataclass(frozen=True)
class SourceArchive:
    split: str
    component: str
    path: Path


@dataclass(frozen=True)
class SourceRecord:
    split: str
    component: str
    data_id: str
    question: str
    question_count: int | None = None
    question_type: str | None = None
    data_category: str | None = None
    answer_contents: str | None = None
    answer_count: int | None = None


_TARGETS = {
    ("training", "sftdata"): lambda name: name.startswith("ts_02."),
    ("training", "sftlabel"): lambda name: name.startswith("tl_02."),
    ("validation", "sftdata"): lambda name: name.startswith("vs_02."),
    ("validation", "sftlabel"): lambda name: name == "vl.zip",
}

_MAX_ARCHIVE_ENTRIES = 1_024
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024**3
_MAX_COMPONENT_BYTES = 64 * 1024**2
_MAX_COMPONENT_COMPRESSION_RATIO = 100.0
_MAX_ENTRY_NAME_LENGTH = 4_096
_SUPPORTED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


def discover_sft_sources(package_root: str | Path) -> tuple[SourceArchive, ...]:
    root = Path(package_root)
    if not root.is_dir():
        raise AIHub71748ReaderError("DATASET_ROOT_NOT_FOUND")
    found: dict[tuple[str, str], list[Path]] = {key: [] for key in _TARGETS}
    for path in root.rglob("*.zip"):
        name = path.name.casefold()
        for target, predicate in _TARGETS.items():
            if predicate(name):
                found[target].append(path)
    if any(not found[(split, component)] for split, component in _TARGETS):
        missing = [key for key, paths in found.items() if not paths]
        if any(
            all((split, component) in missing for component in ("sftdata", "sftlabel"))
            for split in ("training", "validation")
        ):
            raise AIHub71748ReaderError("SOURCE_SPLIT_MISSING")
        raise AIHub71748ReaderError("SOURCE_COMPONENT_MISSING")
    if any(len(paths) > 1 for paths in found.values()):
        raise AIHub71748ReaderError("SOURCE_ENTRY_DUPLICATED")
    return tuple(
        SourceArchive(split, component, found[(split, component)][0])
        for split in ("training", "validation")
        for component in ("sftdata", "sftlabel")
    )


def _normalized_entry_name(item: zipfile.ZipInfo) -> str:
    """Return a safe archive-relative name without extracting the entry."""

    name = item.filename
    if not name or len(name) > _MAX_ENTRY_NAME_LENGTH or "\x00" in name or "\\" in name:
        raise AIHub71748ReaderError("SOURCE_ENTRY_PATH_UNSAFE")
    # The provider package uses one leading slash as an archive-root marker.
    # It is removed only for matching; entries are opened by their exact ZipInfo.
    if name.startswith("//"):
        raise AIHub71748ReaderError("SOURCE_ENTRY_PATH_UNSAFE")
    relative = unicodedata.normalize("NFC", name[1:] if name.startswith("/") else name)
    if len(relative) >= 2 and relative[1] == ":":
        raise AIHub71748ReaderError("SOURCE_ENTRY_PATH_UNSAFE")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise AIHub71748ReaderError("SOURCE_ENTRY_PATH_UNSAFE")
    parts = PurePosixPath(relative).parts
    if not relative or PurePosixPath(relative).is_absolute():
        raise AIHub71748ReaderError("SOURCE_ENTRY_PATH_UNSAFE")
    return "/".join(parts)


def _validated_entries(
    archive: zipfile.ZipFile,
) -> tuple[tuple[zipfile.ZipInfo, str], ...]:
    entries = archive.infolist()
    if len(entries) > _MAX_ARCHIVE_ENTRIES:
        raise AIHub71748ReaderError("SOURCE_ARCHIVE_RESOURCE_LIMIT")
    if sum(item.file_size for item in entries) > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise AIHub71748ReaderError("SOURCE_ARCHIVE_RESOURCE_LIMIT")

    validated: list[tuple[zipfile.ZipInfo, str]] = []
    normalized_names: set[str] = set()
    for item in entries:
        normalized = _normalized_entry_name(item)
        key = normalized.casefold()
        if key in normalized_names:
            raise AIHub71748ReaderError("SOURCE_ENTRY_NAME_DUPLICATED")
        normalized_names.add(key)
        if item.flag_bits & 0x1:
            raise AIHub71748ReaderError("SOURCE_ENTRY_ENCRYPTED")
        unix_mode = item.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if file_type and not item.is_dir() and file_type != stat.S_IFREG:
            raise AIHub71748ReaderError("SOURCE_ENTRY_TYPE_UNSUPPORTED")
        if not item.is_dir() and item.compress_type not in _SUPPORTED_COMPRESSION:
            raise AIHub71748ReaderError("SOURCE_ARCHIVE_UNSUPPORTED")
        if item.file_size and not item.compress_size:
            raise AIHub71748ReaderError("SOURCE_ARCHIVE_RESOURCE_LIMIT")
        if (
            item.compress_size
            and item.file_size / item.compress_size > _MAX_COMPONENT_COMPRESSION_RATIO
        ):
            raise AIHub71748ReaderError("SOURCE_ARCHIVE_RESOURCE_LIMIT")
        validated.append((item, normalized))
    return tuple(validated)


def _entry(archive: zipfile.ZipFile, component: str) -> zipfile.ZipInfo:
    files = [
        (item, name) for item, name in _validated_entries(archive) if not item.is_dir()
    ]
    matches = [
        item
        for item, name in files
        if PurePosixPath(name).name.casefold() == f"{component}.json"
    ]
    if len(matches) != 1:
        raise AIHub71748ReaderError(
            "SOURCE_COMPONENT_JSON_AMBIGUOUS"
            if len(matches) > 1
            else "SOURCE_COMPONENT_JSON_MISSING"
        )
    selected = matches[0]
    if selected.file_size > _MAX_COMPONENT_BYTES:
        raise AIHub71748ReaderError("SOURCE_COMPONENT_RESOURCE_LIMIT")
    if selected.file_size and not selected.compress_size:
        raise AIHub71748ReaderError("SOURCE_COMPONENT_RESOURCE_LIMIT")
    if (
        selected.compress_size
        and selected.file_size / selected.compress_size
        > _MAX_COMPONENT_COMPRESSION_RATIO
    ):
        raise AIHub71748ReaderError("SOURCE_COMPONENT_RESOURCE_LIMIT")
    return selected


def _required_string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AIHub71748ReaderError("INPUT_SCHEMA_MISMATCH")
    return value


def _required_count(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AIHub71748ReaderError("INPUT_SCHEMA_MISMATCH")
    return value


def _required_category(record: dict[str, Any]) -> str:
    value = record.get("data_category")
    if not isinstance(value, dict):
        raise AIHub71748ReaderError("INPUT_SCHEMA_MISMATCH")
    return _required_string(value, "middle")


def parse_source_record(
    split: str, component: str, record: dict[str, Any]
) -> SourceRecord:
    data_id = _required_string(record, "data_id")
    question = _required_string(record, "question")
    if component == "sftdata":
        question_type = _required_string(record, "question_type")
        category = _required_category(record)
        return SourceRecord(
            split,
            component,
            data_id,
            question,
            question_count=_required_count(record, "question_count"),
            question_type=question_type,
            data_category=category,
        )
    if component != "sftlabel":
        raise AIHub71748ReaderError("SOURCE_COMPONENT_MISSING")
    answer = record.get("answer")
    if not isinstance(answer, dict):
        raise AIHub71748ReaderError("INPUT_SCHEMA_MISMATCH")
    return SourceRecord(
        split,
        component,
        data_id,
        question,
        answer_contents=_required_string(answer, "contents"),
        answer_count=_required_count(answer, "answer_count"),
    )


def iter_source_records(source: SourceArchive) -> Iterator[SourceRecord]:
    """Stream one JSON member without extraction or payload logging."""

    try:
        with zipfile.ZipFile(source.path) as archive:
            with archive.open(_entry(archive, source.component), "r") as stream:
                for record in _iter_data_info(stream):
                    try:
                        yield parse_source_record(
                            source.split, source.component, record
                        )
                    finally:
                        record.clear()
    except AIHub71748ReaderError:
        raise
    except JoinIntegrityError as exc:
        raise AIHub71748ReaderError(exc.code) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise AIHub71748ReaderError("SOURCE_ARCHIVE_UNSUPPORTED") from None
