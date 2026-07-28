"""Read-only, value-safe join-integrity inspection for AIHUB-71748 SFT data."""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from src.data.safety import guard_safe_output


DATASET_ID = 71748
EXPECTED_RECORDS = {"training": 10_580, "validation": 1_322}
MAX_RECORD_CHARACTERS = 8 * 1024 * 1024
READ_CHUNK_CHARACTERS = 64 * 1024


class JoinIntegrityError(RuntimeError):
    """Fail-closed error carrying only a fixed non-payload code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _CharacterReader:
    def __init__(self, source: io.TextIOBase) -> None:
        self.source = source
        self.buffer = ""
        self.position = 0

    def _fill(self) -> bool:
        if self.position < len(self.buffer):
            return True
        self.buffer = self.source.read(READ_CHUNK_CHARACTERS)
        self.position = 0
        return bool(self.buffer)

    def peek(self) -> str:
        return self.buffer[self.position] if self._fill() else ""

    def take(self) -> str:
        value = self.peek()
        if value:
            self.position += 1
        return value

    def whitespace(self) -> None:
        while self.peek() and self.peek().isspace():
            self.take()


def _expect(reader: _CharacterReader, expected: str) -> None:
    reader.whitespace()
    if reader.take() != expected:
        raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")


def _read_string(reader: _CharacterReader) -> str:
    reader.whitespace()
    if reader.take() != '"':
        raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
    raw = ['"']
    escaped = False
    while True:
        character = reader.take()
        if not character:
            raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
        raw.append(character)
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            break
    try:
        value = json.loads("".join(raw))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE") from None
    if not isinstance(value, str):
        raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
    return value


def _read_raw_value(reader: _CharacterReader, *, retain: bool) -> str | None:
    reader.whitespace()
    first = reader.take()
    if not first:
        raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
    raw: list[str] = [first] if retain else []
    size = 1

    def append(character: str) -> None:
        nonlocal size
        size += 1
        if size > MAX_RECORD_CHARACTERS:
            raise JoinIntegrityError("RECORD_SIZE_LIMIT_EXCEEDED")
        if retain:
            raw.append(character)

    if first in "[{":
        stack = [first]
        in_string = False
        escaped = False
        while stack:
            character = reader.take()
            if not character:
                raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
            append(character)
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "[{":
                stack.append(character)
            elif character in "]}":
                opener = stack.pop()
                if (opener, character) not in {("[", "]"), ("{", "}")}:
                    raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
    elif first == '"':
        escaped = False
        while True:
            character = reader.take()
            if not character:
                raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
            append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                break
    else:
        while reader.peek() and reader.peek() not in ",]}" and not reader.peek().isspace():
            append(reader.take())
    return "".join(raw) if retain else None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JoinIntegrityError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _iter_array_records(reader: _CharacterReader) -> Iterator[dict[str, Any]]:
    _expect(reader, "[")
    reader.whitespace()
    if reader.peek() == "]":
        reader.take()
        return
    while True:
        raw = _read_raw_value(reader, retain=True)
        try:
            record = json.loads(raw or "", object_pairs_hook=_reject_duplicate_keys)
        except JoinIntegrityError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise JoinIntegrityError("MALFORMED_JSON_RECORD") from None
        if not isinstance(record, dict):
            raise JoinIntegrityError("RECORD_NOT_OBJECT")
        yield record
        reader.whitespace()
        delimiter = reader.take()
        if delimiter == "]":
            return
        if delimiter != ",":
            raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")


def _iter_data_info(source: BinaryIO) -> Iterator[dict[str, Any]]:
    text = io.TextIOWrapper(source, encoding="utf-8-sig", errors="strict", newline=None)
    reader = _CharacterReader(text)
    try:
        _expect(reader, "{")
        found = False
        reader.whitespace()
        while reader.peek() != "}":
            key = _read_string(reader)
            _expect(reader, ":")
            if key == "data_info":
                if found:
                    raise JoinIntegrityError("DUPLICATE_DATA_INFO")
                found = True
                yield from _iter_array_records(reader)
            else:
                _read_raw_value(reader, retain=False)
            reader.whitespace()
            delimiter = reader.take()
            if delimiter == "}":
                break
            if delimiter != ",":
                raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
            reader.whitespace()
        if not found:
            raise JoinIntegrityError("DATA_INFO_MISSING")
        reader.whitespace()
        if reader.take():
            raise JoinIntegrityError("MALFORMED_JSON_STRUCTURE")
    except UnicodeDecodeError:
        raise JoinIntegrityError("INVALID_UTF8") from None


def _split_from_path(path: Path) -> str:
    matches = {part.casefold() for part in path.parts if part.casefold() in {"training", "validation"}}
    if not matches:
        raise JoinIntegrityError("SPLIT_UNRESOLVED")
    if len(matches) != 1:
        raise JoinIntegrityError("SPLIT_AMBIGUOUS")
    return next(iter(matches))


def _archive_contract(package_root: Path) -> dict[tuple[str, str], Path]:
    candidates: dict[tuple[str, str], list[Path]] = {
        ("training", "sftdata"): [],
        ("training", "sftlabel"): [],
        ("validation", "sftdata"): [],
        ("validation", "sftlabel"): [],
    }
    for path in package_root.rglob("*.zip"):
        name = path.name.casefold()
        target: tuple[str, str] | None = None
        if name.startswith("ts_02."):
            target = ("training", "sftdata")
        elif name.startswith("tl_02."):
            target = ("training", "sftlabel")
        elif name.startswith("vs_02."):
            target = ("validation", "sftdata")
        elif name == "vl.zip":
            target = ("validation", "sftlabel")
        if target is None:
            continue
        if _split_from_path(path) != target[0]:
            raise JoinIntegrityError("ARCHIVE_TARGET_MISMATCH")
        candidates[target].append(path)
    if any(len(paths) != 1 for paths in candidates.values()):
        raise JoinIntegrityError("ARCHIVE_CONTRACT_MISMATCH")
    return {key: paths[0] for key, paths in candidates.items()}


def _entry_for(archive: zipfile.ZipFile, component: str) -> zipfile.ZipInfo:
    suffix = f"/{component}.json"
    matches = [item for item in archive.infolist() if ("/" + item.filename.lstrip("/")).casefold().endswith(suffix)]
    if len(matches) != 1:
        raise JoinIntegrityError("ENTRY_TARGET_MISMATCH")
    return matches[0]


def _read_ids(path: Path, component: str) -> tuple[Counter[str], dict[str, int]]:
    counts: Counter[str] = Counter()
    metrics = {"records": 0, "null": 0, "empty": 0, "whitespace": 0, "minimum_length": 0, "maximum_length": 0}
    try:
        with zipfile.ZipFile(path) as archive:
            info = _entry_for(archive, component)
            with archive.open(info, "r") as source:
                for record in _iter_data_info(source):
                    metrics["records"] += 1
                    if "data_id" not in record:
                        raise JoinIntegrityError("DATA_ID_MISSING")
                    value = record["data_id"]
                    if value is None:
                        metrics["null"] += 1
                        raise JoinIntegrityError("DATA_ID_NULL")
                    if not isinstance(value, str):
                        raise JoinIntegrityError("DATA_ID_TYPE_MISMATCH")
                    length = len(value)
                    if length == 0:
                        metrics["empty"] += 1
                        raise JoinIntegrityError("DATA_ID_EMPTY")
                    if value.isspace():
                        metrics["whitespace"] += 1
                        raise JoinIntegrityError("DATA_ID_WHITESPACE_ONLY")
                    metrics["minimum_length"] = length if metrics["minimum_length"] == 0 else min(metrics["minimum_length"], length)
                    metrics["maximum_length"] = max(metrics["maximum_length"], length)
                    counts[value] += 1
                    record.clear()
    except JoinIntegrityError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise JoinIntegrityError("ARCHIVE_READ_FAILED") from None
    return counts, metrics


def _component_summary(counts: Counter[str], metrics: dict[str, int]) -> dict[str, Any]:
    duplicate_keys = sum(1 for count in counts.values() if count > 1)
    duplicate_records = sum(count for count in counts.values() if count > 1)
    return {
        **metrics,
        "unique": len(counts),
        "duplicate_keys": duplicate_keys,
        "duplicate_records": duplicate_records,
        "type": "string",
    }


def _relationship(data: Counter[str], label: Counter[str]) -> str:
    duplicate_data = any(count > 1 for count in data.values())
    duplicate_label = any(count > 1 for count in label.values())
    if duplicate_data and duplicate_label:
        return "many_to_many"
    if duplicate_data:
        return "many_to_one"
    if duplicate_label:
        return "one_to_many"
    if set(data) != set(label):
        return "incomplete"
    return "one_to_one"


def _scan_once(package_root: Path) -> dict[str, Any]:
    archives = _archive_contract(package_root)
    all_ids: list[str] = []
    split_counts: dict[str, dict[str, Counter[str]]] = {}
    splits: dict[str, Any] = {}
    for split in ("training", "validation"):
        data, data_metrics = _read_ids(archives[(split, "sftdata")], "sftdata")
        label, label_metrics = _read_ids(archives[(split, "sftlabel")], "sftlabel")
        all_ids.extend(data)
        all_ids.extend(label)
        split_counts[split] = {"data": data, "label": label}
        data_keys, label_keys = set(data), set(label)
        matched = data_keys & label_keys
        denominator = max(len(data_keys), len(label_keys))
        splits[split] = {
            "sftdata": _component_summary(data, data_metrics),
            "sftlabel": _component_summary(label, label_metrics),
            "matched_ids": len(matched),
            "orphan_data_ids": len(data_keys - label_keys),
            "orphan_label_ids": len(label_keys - data_keys),
            "ambiguous_ids": len({key for key, count in data.items() if count > 1} | {key for key, count in label.items() if count > 1}),
            "one_to_one_ratio": 1.0 if denominator == 0 else len(matched) / denominator,
            "relationship": _relationship(data, label),
        }
    train, validation = split_counts["training"], split_counts["validation"]
    train_joined = set(train["data"]) & set(train["label"])
    validation_joined = set(validation["data"]) & set(validation["label"])
    data_to_other_label = set(train["data"]) & set(validation["label"])
    validation_to_train_label = set(validation["data"]) & set(train["label"])
    result = {
        "dataset_id": DATASET_ID,
        "components": ["sftdata", "sftlabel"],
        "splits": splits,
        "cross_split": {
            "data_overlap": len(set(train["data"]) & set(validation["data"])),
            "label_overlap": len(set(train["label"]) & set(validation["label"])),
            "joined_overlap": len(train_joined & validation_joined),
            "training_data_validation_label": len(data_to_other_label),
            "validation_data_training_label": len(validation_to_train_label),
            "cross_component_mismatch": len(data_to_other_label | validation_to_train_label),
        },
        "hash": {"used": False, "collision_count": 0, "equality": "raw_process_local"},
        "safety": {
            "raw_id_output": False,
            "raw_payload_output": False,
            "stdout_leak": False,
            "stderr_leak": False,
            "exception_leak": False,
        },
    }
    guarded = guard_safe_output(result, all_ids)
    if guarded is not None:
        raise JoinIntegrityError(guarded["error_code"])
    expected_ok = all(
        splits[split][component]["records"] == EXPECTED_RECORDS[split]
        for split in EXPECTED_RECORDS
        for component in ("sftdata", "sftlabel")
    )
    contract_ok = expected_ok and all(
        splits[split]["relationship"] == "one_to_one"
        and splits[split]["orphan_data_ids"] == 0
        and splits[split]["orphan_label_ids"] == 0
        and splits[split]["sftdata"]["duplicate_keys"] == 0
        and splits[split]["sftlabel"]["duplicate_keys"] == 0
        for split in EXPECTED_RECORDS
    ) and all(value == 0 for value in result["cross_split"].values())
    result["status"] = "passed" if contract_ok else "blocked"
    result["error_code"] = None if contract_ok else ("JOIN_CONTRACT_FAILED" if expected_ok else "RECORD_COUNT_DRIFT")
    return result


def validate_determinism(first: dict[str, Any], second: dict[str, Any]) -> None:
    if first != second:
        raise JoinIntegrityError("NON_DETERMINISTIC_SCAN")


def scan_aihub_71748_join(package_root: str | Path) -> dict[str, Any]:
    """Run exactly two full scans and return only aggregate, leak-guarded results."""

    root = Path(package_root)
    if not root.is_dir():
        return {"status": "blocked", "error_code": "PACKAGE_ROOT_MISSING", "execution_allowed": False}
    try:
        first = _scan_once(root)
        second = _scan_once(root)
        validate_determinism(first, second)
        result = {
            **first,
            "determinism": {"runs": 2, "aggregate_match": True},
            "full_scan_count": 2,
            "execution_allowed": False,
        }
        guarded = guard_safe_output(result, [])
        if guarded is not None:
            raise JoinIntegrityError(guarded["error_code"])
        return result
    except JoinIntegrityError as exc:
        return {
            "status": "blocked",
            "error_code": exc.code,
            "full_scan_count": 0,
            "execution_allowed": False,
        }
