"""Bounded streaming reader for the AIHUB-71748 SFT ZIP components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
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
        if any(all((split, component) in missing for component in ("sftdata", "sftlabel")) for split in ("training", "validation")):
            raise AIHub71748ReaderError("SOURCE_SPLIT_MISSING")
        raise AIHub71748ReaderError("SOURCE_COMPONENT_MISSING")
    if any(len(paths) > 1 for paths in found.values()):
        raise AIHub71748ReaderError("SOURCE_ENTRY_DUPLICATED")
    return tuple(
        SourceArchive(split, component, found[(split, component)][0])
        for split in ("training", "validation")
        for component in ("sftdata", "sftlabel")
    )


def _entry(archive: zipfile.ZipFile, component: str) -> zipfile.ZipInfo:
    files = [item for item in archive.infolist() if not item.is_dir()]
    matches = [
        item for item in files
        if ("/" + item.filename.lstrip("/")).casefold().endswith(f"/{component}.json")
    ]
    if len(matches) != 1:
        raise AIHub71748ReaderError(
            "SOURCE_ENTRY_DUPLICATED" if len(matches) > 1 else "SOURCE_COMPONENT_MISSING"
        )
    if len(files) != 1:
        raise AIHub71748ReaderError("SOURCE_ENTRY_UNEXPECTED")
    return matches[0]


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


def parse_source_record(split: str, component: str, record: dict[str, Any]) -> SourceRecord:
    data_id = _required_string(record, "data_id")
    question = _required_string(record, "question")
    if component == "sftdata":
        question_type = _required_string(record, "question_type")
        category = _required_string(record, "data_category")
        return SourceRecord(
            split, component, data_id, question,
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
        split, component, data_id, question,
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
                        yield parse_source_record(source.split, source.component, record)
                    finally:
                        record.clear()
    except AIHub71748ReaderError:
        raise
    except JoinIntegrityError as exc:
        raise AIHub71748ReaderError(exc.code) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise AIHub71748ReaderError("SOURCE_ARCHIVE_UNSUPPORTED") from None
