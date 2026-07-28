"""Bounded, aggregate-only leakage inspection for approved AIHUB-71748 SFT fields."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import zip_longest
import math
from pathlib import Path
import re
import time
import tracemalloc
from typing import Any, Callable, Iterable
import zipfile

import yaml

from src.data.aihub_71748_exact_duplicate import ExactDuplicateScanError, _string_field
from src.data.aihub_71748_join import (
    EXPECTED_RECORDS,
    JoinIntegrityError,
    _archive_contract,
    _entry_for,
    _iter_data_info,
)
from src.data.aihub_71748_near_duplicate import normalize_near_duplicate_text
from src.data.safety import guard_safe_output


DATASET_ID = 71748
_MISSING = object()
_SAFE_EXECUTION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,126}$")
_PROMPT_SOURCES = {
    "evaluation_framework": Path("configs/evaluation-prompts.example.yaml"),
    "candidate_model": Path("configs/eos-generation-prompts.example.yaml"),
}
_NEAR_EVIDENCE = {
    "execution_id": "AIHUB-71748-NEAR-DUPLICATE-SCAN-20260729-0002",
    "question": {"groups": 40, "pairs": 45},
    "answer": {"groups": 1, "pairs": 2},
    "qa_pair": {"groups": 0, "pairs": 0},
}


@dataclass(frozen=True)
class LeakagePerformanceContract:
    runtime_budget_seconds: float = 300.0
    memory_budget_bytes: int = 512 * 1024 * 1024

    def validate(self) -> None:
        if (
            not math.isfinite(self.runtime_budget_seconds)
            or self.runtime_budget_seconds <= 0
            or isinstance(self.memory_budget_bytes, bool)
            or self.memory_budget_bytes <= 0
        ):
            raise LeakageScanError("INVALID_PERFORMANCE_CONTRACT")


DEFAULT_PERFORMANCE_CONTRACT = LeakagePerformanceContract()


class LeakageScanError(RuntimeError):
    """Fail-closed error carrying only a fixed non-payload code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _BudgetMonitor:
    def __init__(
        self,
        contract: LeakagePerformanceContract,
        *,
        clock: Callable[[], float],
        cancelled: Callable[[], bool],
        track_memory: bool,
    ) -> None:
        self.contract = contract
        self.clock = clock
        self.cancelled = cancelled
        self.started = clock()
        self.phase = "initialization"
        self.peak_memory_bytes = 0
        self._owns_tracemalloc = track_memory and not tracemalloc.is_tracing()
        if self._owns_tracemalloc:
            tracemalloc.start()

    def check(self, phase: str) -> None:
        self.phase = phase
        if tracemalloc.is_tracing():
            self.peak_memory_bytes = max(
                self.peak_memory_bytes,
                tracemalloc.get_traced_memory()[1],
            )
        if self.cancelled():
            raise LeakageScanError("SCAN_CANCELLED")
        if self.clock() - self.started > self.contract.runtime_budget_seconds:
            raise LeakageScanError("RUNTIME_BUDGET_EXCEEDED")
        if self.peak_memory_bytes > self.contract.memory_budget_bytes:
            raise LeakageScanError("MEMORY_BUDGET_EXCEEDED")

    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock() - self.started)

    def close(self) -> None:
        if self._owns_tracemalloc:
            tracemalloc.stop()


def _raw_by_normalized(values: Counter[Any]) -> dict[Any, Counter[Any]]:
    grouped: dict[Any, Counter[Any]] = defaultdict(Counter)
    for raw, count in values.items():
        if isinstance(raw, tuple):
            normalized: Any = tuple(normalize_near_duplicate_text(item) for item in raw)
        else:
            normalized = normalize_near_duplicate_text(raw)
        grouped[normalized][raw] += count
    return grouped


def _cross_split_summary(
    training: Counter[Any],
    validation: Counter[Any],
    near: dict[str, int],
) -> dict[str, Any]:
    exact_values = training.keys() & validation.keys()
    exact_pairs = sum(training[value] * validation[value] for value in exact_values)
    train_normalized = _raw_by_normalized(training)
    validation_normalized = _raw_by_normalized(validation)
    normalized_groups = 0
    normalized_pairs = 0
    for normalized in train_normalized.keys() & validation_normalized.keys():
        train_variants = train_normalized[normalized]
        validation_variants = validation_normalized[normalized]
        total_pairs = sum(train_variants.values()) * sum(validation_variants.values())
        raw_pairs = sum(
            train_variants[value] * validation_variants[value]
            for value in train_variants.keys() & validation_variants.keys()
        )
        if total_pairs > raw_pairs:
            normalized_groups += 1
            normalized_pairs += total_pairs - raw_pairs
    return {
        "exact": {"groups": len(exact_values), "pairs": exact_pairs},
        "normalized": {"groups": normalized_groups, "pairs": normalized_pairs},
        "near": {
            "groups": near["groups"],
            "pairs": near["pairs"],
            "source": "approved_near_duplicate_run_0002",
            "reexecuted": False,
        },
    }


def _load_prompt_set(repository_root: Path, relative_path: Path) -> list[str]:
    path = (repository_root / relative_path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError:
        raise LeakageScanError("PROMPT_SOURCE_OUTSIDE_REPOSITORY") from None
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise LeakageScanError("PROMPT_SOURCE_READ_FAILED") from None
    if not isinstance(document, dict):
        raise LeakageScanError("PROMPT_SOURCE_SCHEMA_MISMATCH")
    if document.get("source") != "synthetic" or document.get("pii_free") is not True:
        raise LeakageScanError("PROMPT_SOURCE_NOT_APPROVED")
    prompts = document.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise LeakageScanError("PROMPT_SOURCE_SCHEMA_MISMATCH")
    values: list[str] = []
    for prompt in prompts:
        if not isinstance(prompt, dict) or not isinstance(prompt.get("text"), str):
            raise LeakageScanError("PROMPT_SOURCE_SCHEMA_MISMATCH")
        values.append(prompt["text"])
    if len(set(values)) != len(values):
        raise LeakageScanError("DUPLICATE_PROMPT_VALUE")
    return values


def _prompt_leakage_summary(
    prompts: list[str],
    questions: Counter[str],
    answers: Counter[str],
) -> dict[str, Any]:
    question_normalized = _raw_by_normalized(questions)
    answer_normalized = _raw_by_normalized(answers)
    exact_question = 0
    exact_answer = 0
    normalized_question = 0
    normalized_answer = 0
    for prompt in prompts:
        exact_question += questions[prompt]
        exact_answer += answers[prompt]
        normalized = normalize_near_duplicate_text(prompt)
        normalized_question += max(
            0,
            sum(question_normalized.get(normalized, {}).values()) - questions[prompt],
        )
        normalized_answer += max(
            0,
            sum(answer_normalized.get(normalized, {}).values()) - answers[prompt],
        )
    total = exact_question + exact_answer + normalized_question + normalized_answer
    return {
        "prompts_scanned": len(prompts),
        "exact_question_candidates": exact_question,
        "exact_answer_candidates": exact_answer,
        "normalized_question_candidates": normalized_question,
        "normalized_answer_candidates": normalized_answer,
        "candidates": total,
        "near_comparison": "not_run_near_scan_reexecution_prohibited",
    }


def summarize_leakage(
    records: dict[str, Iterable[tuple[str, str, str]]],
    prompt_sets: dict[str, Iterable[str]],
    *,
    execution_id: str = "SYNTHETIC",
    contract: LeakagePerformanceContract = DEFAULT_PERFORMANCE_CONTRACT,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
    _monitor: _BudgetMonitor | None = None,
) -> dict[str, Any]:
    """Summarize already-approved records and repository prompts without values."""

    contract.validate()
    if not isinstance(execution_id, str) or not _SAFE_EXECUTION_ID.fullmatch(execution_id):
        raise LeakageScanError("INVALID_EXECUTION_ID")
    monitor = _monitor or _BudgetMonitor(
        contract,
        clock=clock,
        cancelled=cancelled,
        track_memory=False,
    )
    split_values = {
        split: {"question": Counter(), "answer": Counter(), "qa_pair": Counter()}
        for split in ("training", "validation")
    }
    source_values: list[str] = []
    for split in ("training", "validation"):
        for ordinal, record in enumerate(records.get(split, ())):
            if not isinstance(record, (tuple, list)) or len(record) != 3:
                raise LeakageScanError("INVALID_RECORD_SHAPE")
            data_question, label_question, answer = record
            if not all(isinstance(value, str) for value in record):
                raise LeakageScanError("FIELD_TYPE_MISMATCH")
            if data_question != label_question:
                raise LeakageScanError("QUESTION_COMPONENT_MISMATCH")
            split_values[split]["question"][data_question] += 1
            split_values[split]["answer"][answer] += 1
            split_values[split]["qa_pair"][(data_question, answer)] += 1
            source_values.extend((data_question, label_question, answer))
            if ordinal % 128 == 0:
                monitor.check("records_loaded")

    all_questions = split_values["training"]["question"] + split_values["validation"]["question"]
    all_answers = split_values["training"]["answer"] + split_values["validation"]["answer"]
    safe_prompt_sets: dict[str, list[str]] = {}
    for name in _PROMPT_SOURCES:
        values = list(prompt_sets.get(name, ()))
        if not values or any(not isinstance(value, str) for value in values):
            raise LeakageScanError("PROMPT_SOURCE_SCHEMA_MISMATCH")
        safe_prompt_sets[name] = values
        source_values.extend(values)
    benchmark_values = list(prompt_sets.get("benchmark", ()))
    if any(not isinstance(value, str) for value in benchmark_values):
        raise LeakageScanError("PROMPT_SOURCE_SCHEMA_MISMATCH")
    safe_prompt_sets["benchmark"] = benchmark_values
    source_values.extend(benchmark_values)
    if set(prompt_sets) - (set(_PROMPT_SOURCES) | {"benchmark"}):
        raise LeakageScanError("UNKNOWN_PROMPT_SOURCE")
    monitor.check("prompt_sources_loaded")

    train_validation = {
        field: _cross_split_summary(
            split_values["training"][field],
            split_values["validation"][field],
            _NEAR_EVIDENCE[field],
        )
        for field in ("question", "answer", "qa_pair")
    }
    evaluation = _prompt_leakage_summary(
        safe_prompt_sets["evaluation_framework"], all_questions, all_answers
    )
    candidate = _prompt_leakage_summary(
        safe_prompt_sets["candidate_model"], all_questions, all_answers
    )
    if safe_prompt_sets["benchmark"]:
        benchmark = {
            **_prompt_leakage_summary(
                safe_prompt_sets["benchmark"], all_questions, all_answers
            ),
            "sources": 1,
            "status": "synthetic_test_only",
            "external_download": False,
        }
    else:
        benchmark = {
            "sources": 0,
            "prompts_scanned": 0,
            "candidates": 0,
            "status": "not_available_local",
            "external_download": False,
        }
    type_candidates = [
        sum(train_validation[field][kind]["pairs"] for kind in ("exact", "normalized", "near"))
        for field in ("question", "answer", "qa_pair")
    ] + [evaluation["candidates"], candidate["candidates"], benchmark["candidates"]]
    monitor.check("aggregate_result")
    result = {
        "dataset_id": DATASET_ID,
        "execution_id": execution_id,
        "components": ["sftdata", "sftlabel"],
        "splits": ["training", "validation"],
        "field_paths": ["sftdata_question", "sftlabel_question", "sftlabel_answer_contents"],
        "record_counts": {
            "training": sum(split_values["training"]["question"].values()),
            "validation": sum(split_values["validation"]["question"].values()),
        },
        "train_validation": train_validation,
        "evaluation_framework": evaluation,
        "candidate_model": candidate,
        "benchmark": benchmark,
        "risk": {
            "none": sum(value == 0 for value in type_candidates),
            "informational": 0,
            "review_candidate": sum(type_candidates),
            "blocked_candidate": 0,
            "policy": "REVIEW_REQUIRED",
            "threshold_status": "not_approved",
        },
        "near_evidence": {
            "execution_id": _NEAR_EVIDENCE["execution_id"],
            "reused": True,
            "scan_reexecuted": False,
        },
        "performance": {
            "elapsed_seconds": monitor.elapsed_seconds(),
            "peak_memory_bytes": monitor.peak_memory_bytes,
            "runtime_budget_seconds": contract.runtime_budget_seconds,
            "memory_budget_bytes": contract.memory_budget_bytes,
            "final_phase": monitor.phase,
        },
        "safety": {
            "raw_output": False,
            "substring_output": False,
            "preview_output": False,
            "data_id_output": False,
            "hash_output": False,
            "benchmark_raw_output": False,
            "stdout_leak": False,
            "stderr_leak": False,
            "exception_leak": False,
            "temporary_files": False,
            "worker_processes": False,
            "dataset_write": False,
            "external_internet": False,
        },
        "status": "completed",
        "execution_allowed": False,
    }
    guarded = guard_safe_output(result, source_values)
    source_values.clear()
    if guarded is not None:
        raise LeakageScanError(guarded["error_code"])
    return result


def _scan_once(
    package_root: Path,
    repository_root: Path,
    *,
    execution_id: str,
    contract: LeakagePerformanceContract,
    clock: Callable[[], float],
    cancelled: Callable[[], bool],
) -> dict[str, Any]:
    monitor = _BudgetMonitor(
        contract,
        clock=clock,
        cancelled=cancelled,
        track_memory=True,
    )
    records: dict[str, list[tuple[str, str, str]]] = {"training": [], "validation": []}
    try:
        monitor.check("prompt_contract")
        prompt_sets = {
            name: _load_prompt_set(repository_root, path)
            for name, path in _PROMPT_SOURCES.items()
        }
        monitor.check("archive_contract")
        archives = _archive_contract(package_root)
        monitor.check("archive_contract")
        for split in ("training", "validation"):
            with zipfile.ZipFile(archives[(split, "sftdata")]) as data_archive, zipfile.ZipFile(
                archives[(split, "sftlabel")]
            ) as label_archive:
                with data_archive.open(_entry_for(data_archive, "sftdata"), "r") as data_source, label_archive.open(
                    _entry_for(label_archive, "sftlabel"), "r"
                ) as label_source:
                    for ordinal, (data_record, label_record) in enumerate(
                        zip_longest(
                            _iter_data_info(data_source),
                            _iter_data_info(label_source),
                            fillvalue=_MISSING,
                        )
                    ):
                        if data_record is _MISSING or label_record is _MISSING:
                            raise LeakageScanError("COMPONENT_RECORD_COUNT_MISMATCH")
                        data_question = _string_field(data_record, "sftdata", ("question",))
                        label_question = _string_field(label_record, "sftlabel", ("question",))
                        answer = _string_field(label_record, "sftlabel", ("answer", "contents"))
                        records[split].append((data_question, label_question, answer))
                        data_record.clear()
                        label_record.clear()
                        if ordinal % 128 == 0:
                            monitor.check("archive_stream_read")
            if len(records[split]) != EXPECTED_RECORDS[split]:
                raise LeakageScanError("RECORD_COUNT_DRIFT")
        result = summarize_leakage(
            records,
            prompt_sets,
            execution_id=execution_id,
            contract=contract,
            clock=clock,
            cancelled=cancelled,
            _monitor=monitor,
        )
        monitor.check("completed")
        result["performance"]["elapsed_seconds"] = monitor.elapsed_seconds()
        result["performance"]["peak_memory_bytes"] = monitor.peak_memory_bytes
        result["performance"]["final_phase"] = monitor.phase
        return result
    except LeakageScanError:
        raise
    except (JoinIntegrityError, ExactDuplicateScanError) as exc:
        raise LeakageScanError(exc.code) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, OverflowError):
        raise LeakageScanError("SCAN_INPUT_READ_FAILED") from None
    finally:
        records.clear()
        monitor.close()


def scan_aihub_71748_leakage(
    package_root: str | Path,
    repository_root: str | Path,
    *,
    execution_id: str,
    contract: LeakagePerformanceContract = DEFAULT_PERFORMANCE_CONTRACT,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Run one separately approved real scan without retry or resume."""

    package = Path(package_root)
    repository = Path(repository_root)
    if not package.is_dir():
        return {
            "status": "blocked",
            "error_code": "PACKAGE_ROOT_MISSING",
            "full_scan_count": 0,
            "execution_allowed": False,
        }
    if not repository.is_dir():
        return {
            "status": "blocked",
            "error_code": "REPOSITORY_ROOT_MISSING",
            "full_scan_count": 0,
            "execution_allowed": False,
        }
    try:
        result = _scan_once(
            package,
            repository,
            execution_id=execution_id,
            contract=contract,
            clock=clock,
            cancelled=cancelled,
        )
        result["full_scan_count"] = 1
        return result
    except LeakageScanError as exc:
        return {
            "status": "blocked",
            "error_code": exc.code,
            "full_scan_count": 1,
            "execution_allowed": False,
        }
