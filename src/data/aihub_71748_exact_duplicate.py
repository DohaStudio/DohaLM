"""Read-only exact duplicate aggregation for approved AIHUB-71748 SFT fields."""

from __future__ import annotations

import zipfile
from collections import Counter, defaultdict
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable

from src.data.aihub_71748_join import (
    EXPECTED_RECORDS,
    JoinIntegrityError,
    _archive_contract,
    _entry_for,
    _iter_data_info,
)
from src.data.safety import guard_safe_output


DATASET_ID = 71748
ALLOWED_FIELD_PATHS = frozenset({
    ("sftdata", "question"),
    ("sftlabel", "question"),
    ("sftlabel", "answer", "contents"),
})
_MISSING = object()


class ExactDuplicateScanError(RuntimeError):
    """Fail-closed error carrying only a fixed non-payload code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _string_field(record: dict[str, Any], component: str, path: tuple[str, ...]) -> str:
    if (component, *path) not in ALLOWED_FIELD_PATHS:
        raise ExactDuplicateScanError("FIELD_NOT_ALLOWED")
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ExactDuplicateScanError("FIELD_MISSING")
        value = value[key]
    if value is None:
        raise ExactDuplicateScanError("FIELD_NULL")
    if not isinstance(value, str):
        raise ExactDuplicateScanError("FIELD_TYPE_MISMATCH")
    return value


def _duplicate_summary(values: Counter[Any]) -> dict[str, int]:
    duplicate_counts = [count for count in values.values() if count > 1]
    return {
        "scanned": sum(values.values()),
        "unique": len(values),
        "duplicate_groups": len(duplicate_counts),
        "duplicate_records": sum(count - 1 for count in duplicate_counts),
        "records_in_duplicate_groups": sum(duplicate_counts),
    }


def _build_result(
    split_values: dict[str, dict[str, Counter[Any]]],
    *,
    component_scanned: dict[str, int],
    component_matches: dict[str, int],
) -> dict[str, Any]:
    question = split_values["training"]["question"] + split_values["validation"]["question"]
    answer = split_values["training"]["answer"] + split_values["validation"]["answer"]
    pair = split_values["training"]["pair"] + split_values["validation"]["pair"]

    question_answers: dict[str, set[str]] = defaultdict(set)
    answer_questions: dict[str, set[str]] = defaultdict(set)
    for split in ("training", "validation"):
        for question_value, answer_value in split_values[split]["pair"]:
            question_answers[question_value].add(answer_value)
            answer_questions[answer_value].add(question_value)

    split_overlap = {
        "training_validation_question": len(
            set(split_values["training"]["question"]) & set(split_values["validation"]["question"])
        ),
        "training_validation_answer": len(
            set(split_values["training"]["answer"]) & set(split_values["validation"]["answer"])
        ),
        "training_validation_pair": len(
            set(split_values["training"]["pair"]) & set(split_values["validation"]["pair"])
        ),
    }
    consistency_scanned = sum(component_scanned.values())
    consistency_matches = sum(component_matches.values())
    result = {
        "dataset": DATASET_ID,
        "comparison": "exact_raw_process_local",
        "question": _duplicate_summary(question),
        "answer": _duplicate_summary(answer),
        "qa_pair": _duplicate_summary(pair),
        "same_question_different_answer": {
            "groups": sum(len(values) > 1 for values in question_answers.values()),
        },
        "different_question_same_answer": {
            "groups": sum(len(values) > 1 for values in answer_questions.values()),
        },
        "split_overlap": split_overlap,
        "splits": {
            split: {
                "question": _duplicate_summary(split_values[split]["question"]),
                "answer": _duplicate_summary(split_values[split]["answer"]),
                "qa_pair": _duplicate_summary(split_values[split]["pair"]),
            }
            for split in ("training", "validation")
        },
        "component_consistency": {
            "sftdata_vs_sftlabel_question": consistency_matches,
            "scanned": consistency_scanned,
            "mismatched": consistency_scanned - consistency_matches,
            "match_rate": 1.0 if consistency_scanned == 0 else consistency_matches / consistency_scanned,
            "by_split": {
                split: {
                    "scanned": component_scanned[split],
                    "matched": component_matches[split],
                    "mismatched": component_scanned[split] - component_matches[split],
                }
                for split in ("training", "validation")
            },
        },
        "hash": {"used": False, "stored": False},
        "safety": {
            "raw_output": False,
            "stdout_leak": False,
            "stderr_leak": False,
            "exception_leak": False,
            "data_id_output": False,
            "hash_output": False,
        },
        "status": "completed",
        "execution_allowed": False,
    }
    guarded = guard_safe_output(result, ())
    if guarded is not None:
        raise ExactDuplicateScanError(guarded["error_code"])
    return result


def summarize_exact_duplicates(
    records: dict[str, Iterable[tuple[str, str, str]]],
) -> dict[str, Any]:
    """Summarize synthetic or already bounded records without returning values."""

    split_values = {
        split: {"question": Counter(), "answer": Counter(), "pair": Counter()}
        for split in ("training", "validation")
    }
    component_scanned = {"training": 0, "validation": 0}
    component_matches = {"training": 0, "validation": 0}
    for split in ("training", "validation"):
        for data_question, label_question, answer in records.get(split, ()):
            if not all(isinstance(value, str) for value in (data_question, label_question, answer)):
                raise ExactDuplicateScanError("FIELD_TYPE_MISMATCH")
            split_values[split]["question"][label_question] += 1
            split_values[split]["answer"][answer] += 1
            split_values[split]["pair"][(label_question, answer)] += 1
            component_scanned[split] += 1
            component_matches[split] += data_question == label_question
    return _build_result(
        split_values,
        component_scanned=component_scanned,
        component_matches=component_matches,
    )


def _scan_once(package_root: Path) -> dict[str, Any]:
    archives = _archive_contract(package_root)
    split_values = {
        split: {"question": Counter(), "answer": Counter(), "pair": Counter()}
        for split in ("training", "validation")
    }
    component_scanned = {"training": 0, "validation": 0}
    component_matches = {"training": 0, "validation": 0}
    try:
        for split in ("training", "validation"):
            with zipfile.ZipFile(archives[(split, "sftdata")]) as data_archive, zipfile.ZipFile(
                archives[(split, "sftlabel")]
            ) as label_archive:
                with data_archive.open(_entry_for(data_archive, "sftdata"), "r") as data_source, label_archive.open(
                    _entry_for(label_archive, "sftlabel"), "r"
                ) as label_source:
                    data_records = _iter_data_info(data_source)
                    label_records = _iter_data_info(label_source)
                    for data_record, label_record in zip_longest(data_records, label_records, fillvalue=_MISSING):
                        if data_record is _MISSING or label_record is _MISSING:
                            raise ExactDuplicateScanError("COMPONENT_RECORD_COUNT_MISMATCH")
                        data_question = _string_field(data_record, "sftdata", ("question",))
                        label_question = _string_field(label_record, "sftlabel", ("question",))
                        answer = _string_field(label_record, "sftlabel", ("answer", "contents"))
                        split_values[split]["question"][label_question] += 1
                        split_values[split]["answer"][answer] += 1
                        split_values[split]["pair"][(label_question, answer)] += 1
                        component_scanned[split] += 1
                        component_matches[split] += data_question == label_question
                        data_record.clear()
                        label_record.clear()
            if component_scanned[split] != EXPECTED_RECORDS[split]:
                raise ExactDuplicateScanError("RECORD_COUNT_DRIFT")
    except ExactDuplicateScanError:
        raise
    except JoinIntegrityError as exc:
        raise ExactDuplicateScanError(exc.code) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ExactDuplicateScanError("ARCHIVE_READ_FAILED") from None
    return _build_result(
        split_values,
        component_scanned=component_scanned,
        component_matches=component_matches,
    )


def scan_aihub_71748_exact_duplicates(package_root: str | Path) -> dict[str, Any]:
    """Run exactly one approved full scan without retry or resume."""

    root = Path(package_root)
    if not root.is_dir():
        return {
            "status": "blocked",
            "error_code": "PACKAGE_ROOT_MISSING",
            "full_scan_count": 0,
            "execution_allowed": False,
        }
    try:
        result = _scan_once(root)
        result["full_scan_count"] = 1
        return result
    except ExactDuplicateScanError as exc:
        return {
            "status": "blocked",
            "error_code": exc.code,
            "full_scan_count": 1,
            "execution_allowed": False,
        }
