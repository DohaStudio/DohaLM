"""Bounded, aggregate-only near duplicate analysis for AIHUB-71748 SFT fields."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
from itertools import combinations, zip_longest
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Iterable
import unicodedata
import zipfile

from src.data.aihub_71748_exact_duplicate import _string_field
from src.data.aihub_71748_join import (
    EXPECTED_RECORDS,
    JoinIntegrityError,
    _archive_contract,
    _entry_for,
    _iter_data_info,
)
from src.data.near_duplicate_policy import (
    BLOCKED_CANDIDATE_THRESHOLD,
    REVIEW_CANDIDATE_THRESHOLD,
)
from src.data.safety import guard_safe_output


DATASET_ID = 71748
CHAR_NGRAM_SIZES = (3, 4)
TOKEN_NGRAM_SIZES = (1, 2)
SIMHASH_BITS = 64
MINHASH_PERMUTATIONS = 16
_UINT64_MASK = (1 << 64) - 1
_MISSING = object()
_SAFE_EXECUTION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,126}$")


@dataclass(frozen=True)
class NearDuplicatePerformanceContract:
    """Fail-closed operational bounds; all numeric values remain proposals."""

    length_ratio_min: float = 0.70
    short_text_characters: int = 24
    short_text_max_delta: int = 4
    shared_character_ngram_min: float = 0.30
    shared_token_ngram_min: float = 0.40
    simhash_distance_max: int = 12
    minhash_jaccard_min: float = 0.50
    maximum_per_record: int = 256
    maximum_total_pairs: int = 250_000
    maximum_expensive_comparisons: int = 100_000
    runtime_budget_seconds: float = 300.0
    memory_budget_bytes: int = 512 * 1024 * 1024

    def validate(self) -> None:
        ratios = (
            self.length_ratio_min,
            self.shared_character_ngram_min,
            self.shared_token_ngram_min,
            self.minhash_jaccard_min,
        )
        if any(not 0.0 <= value <= 1.0 for value in ratios):
            raise NearDuplicateScanError("INVALID_PERFORMANCE_CONTRACT")
        integer_limits = (
            self.short_text_characters,
            self.short_text_max_delta,
            self.simhash_distance_max,
            self.maximum_per_record,
            self.maximum_total_pairs,
            self.maximum_expensive_comparisons,
            self.memory_budget_bytes,
        )
        if any(isinstance(value, bool) or value <= 0 for value in integer_limits):
            raise NearDuplicateScanError("INVALID_PERFORMANCE_CONTRACT")
        if not math.isfinite(self.runtime_budget_seconds) or self.runtime_budget_seconds <= 0:
            raise NearDuplicateScanError("INVALID_PERFORMANCE_CONTRACT")


DEFAULT_PERFORMANCE_CONTRACT = NearDuplicatePerformanceContract()


class NearDuplicateScanError(RuntimeError):
    """Fail-closed error carrying only a fixed non-payload code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Fingerprint:
    normalized: str
    character_ngrams: frozenset[int]
    token_ngrams: frozenset[int]
    simhash: int
    minhash: tuple[int, ...]


@dataclass(frozen=True)
class _ValueGroup:
    fingerprint: _Fingerprint
    record_ordinals: tuple[int, ...]


class _RuntimeMonitor:
    def __init__(
        self,
        contract: NearDuplicatePerformanceContract,
        *,
        clock: Callable[[], float],
        cancelled: Callable[[], bool],
    ) -> None:
        self.contract = contract
        self.clock = clock
        self.cancelled = cancelled
        self.started = clock()
        self.phase = "initialization"
        self.peak_memory_estimate_bytes = 0

    def check(self, phase: str, memory_estimate_bytes: int = 0) -> None:
        self.phase = phase
        self.peak_memory_estimate_bytes = max(
            self.peak_memory_estimate_bytes,
            memory_estimate_bytes,
        )
        if self.cancelled():
            raise NearDuplicateScanError("SCAN_CANCELLED")
        if self.clock() - self.started > self.contract.runtime_budget_seconds:
            raise NearDuplicateScanError("RUNTIME_BUDGET_EXCEEDED")
        if self.peak_memory_estimate_bytes > self.contract.memory_budget_bytes:
            raise NearDuplicateScanError("MEMORY_BUDGET_EXCEEDED")

    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock() - self.started)


class _CandidateAccumulator:
    """Deduplicate canonical group-pair keys before refinement."""

    def __init__(
        self,
        groups: list[_ValueGroup],
        contract: NearDuplicatePerformanceContract,
        monitor: _RuntimeMonitor,
        base_memory_estimate: int,
        total_pair_budget: int,
    ) -> None:
        self.groups = groups
        self.contract = contract
        self.monitor = monitor
        self.base_memory_estimate = base_memory_estimate
        self.total_pair_budget = total_pair_budget
        self.raw_candidate_pairs = 0
        self.duplicate_candidate_pairs_removed = 0
        self.record_pair_count = 0
        self.per_record = [0] * sum(len(group.record_ordinals) for group in groups)
        self.group_pairs: set[tuple[int, int]] = set()

    def offer(self, first: int, second: int) -> None:
        if first == second:
            return
        key = (first, second) if first < second else (second, first)
        pair_weight = len(self.groups[key[0]].record_ordinals) * len(
            self.groups[key[1]].record_ordinals
        )
        self.raw_candidate_pairs += pair_weight
        if key in self.group_pairs:
            self.duplicate_candidate_pairs_removed += pair_weight
            return

        projected_total = self.record_pair_count + pair_weight
        if projected_total > self.total_pair_budget:
            raise NearDuplicateScanError("CANDIDATE_PAIR_LIMIT_EXCEEDED")
        for ordinal in self.groups[key[0]].record_ordinals:
            if self.per_record[ordinal] + len(self.groups[key[1]].record_ordinals) > self.contract.maximum_per_record:
                raise NearDuplicateScanError("PER_RECORD_CANDIDATE_LIMIT_EXCEEDED")
        for ordinal in self.groups[key[1]].record_ordinals:
            if self.per_record[ordinal] + len(self.groups[key[0]].record_ordinals) > self.contract.maximum_per_record:
                raise NearDuplicateScanError("PER_RECORD_CANDIDATE_LIMIT_EXCEEDED")

        self.group_pairs.add(key)
        self.record_pair_count = projected_total
        for ordinal in self.groups[key[0]].record_ordinals:
            self.per_record[ordinal] += len(self.groups[key[1]].record_ordinals)
        for ordinal in self.groups[key[1]].record_ordinals:
            self.per_record[ordinal] += len(self.groups[key[0]].record_ordinals)
        estimate = self.base_memory_estimate + len(self.group_pairs) * 96 + len(self.per_record) * 8
        self.monitor.check("candidate_deduplication", estimate)


def normalize_near_duplicate_text(value: str) -> str:
    if not isinstance(value, str):
        raise NearDuplicateScanError("FIELD_TYPE_MISMATCH")
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(normalized.split())


def _hash64(value: str, seed: int = 0) -> int:
    payload = seed.to_bytes(4, "big") + value.encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _hashed_ngrams(parts: list[str], sizes: tuple[int, ...], prefix: str) -> frozenset[int]:
    result: set[int] = set()
    for size in sizes:
        if not parts:
            continue
        if len(parts) < size:
            result.add(_hash64(f"{prefix}{size}:" + "\u0001".join(parts)))
            continue
        for index in range(len(parts) - size + 1):
            result.add(
                _hash64(f"{prefix}{size}:" + "\u0001".join(parts[index : index + size]))
            )
    return frozenset(result)


def _simhash(features: frozenset[int]) -> int:
    if not features:
        return 0
    weights = [0] * SIMHASH_BITS
    for value in features:
        for bit in range(SIMHASH_BITS):
            weights[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def _minhash(features: frozenset[int]) -> tuple[int, ...]:
    if not features:
        return tuple([_UINT64_MASK] * MINHASH_PERMUTATIONS)
    values = [_UINT64_MASK] * MINHASH_PERMUTATIONS
    for value in features:
        second = ((value >> 1) | 1) & _UINT64_MASK
        for index in range(MINHASH_PERMUTATIONS):
            candidate = (value + index * second) & _UINT64_MASK
            if candidate < values[index]:
                values[index] = candidate
    return tuple(values)


def _fingerprint_normalized(normalized: str) -> _Fingerprint:
    characters = _hashed_ngrams(list(normalized), CHAR_NGRAM_SIZES, "c")
    tokens = _hashed_ngrams(normalized.split(), TOKEN_NGRAM_SIZES, "t")
    combined = frozenset(characters | tokens)
    return _Fingerprint(
        normalized=normalized,
        character_ngrams=characters,
        token_ngrams=tokens,
        simhash=_simhash(combined),
        minhash=_minhash(combined),
    )


def _fingerprint(value: str) -> _Fingerprint:
    return _fingerprint_normalized(normalize_near_duplicate_text(value))


def _jaccard(first: frozenset[int], second: frozenset[int]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _length_filter(first: str, second: str, contract: NearDuplicatePerformanceContract) -> bool:
    maximum = max(len(first), len(second))
    minimum = min(len(first), len(second))
    if maximum == 0:
        return False
    if maximum <= contract.short_text_characters:
        return maximum - minimum <= contract.short_text_max_delta
    return minimum / maximum >= contract.length_ratio_min


def _cheap_similarity(
    first: _Fingerprint,
    second: _Fingerprint,
    contract: NearDuplicatePerformanceContract,
) -> tuple[bool, float]:
    character = _jaccard(first.character_ngrams, second.character_ngrams)
    token = _jaccard(first.token_ngrams, second.token_ngrams)
    simhash_distance = (first.simhash ^ second.simhash).bit_count()
    minhash = sum(a == b for a, b in zip(first.minhash, second.minhash)) / MINHASH_PERMUTATIONS
    passed = (
        character >= contract.shared_character_ngram_min
        or token >= contract.shared_token_ngram_min
        or simhash_distance <= contract.simhash_distance_max
        or minhash >= contract.minhash_jaccard_min
    )
    lexical = 0.45 * character + 0.25 * token + 0.15 * (1.0 - simhash_distance / SIMHASH_BITS) + 0.15 * minhash
    return passed, lexical


def _refine_similarity(first: _Fingerprint, second: _Fingerprint, lexical: float) -> float:
    sequence = SequenceMatcher(None, first.normalized, second.normalized).quick_ratio()
    return max(lexical, sequence)


def _similarity(
    first: _Fingerprint,
    second: _Fingerprint,
    contract: NearDuplicatePerformanceContract = DEFAULT_PERFORMANCE_CONTRACT,
) -> float:
    """Synthetic diagnostic helper following the same bounded refinement path."""

    if first.normalized == second.normalized:
        return 1.0
    if not _length_filter(first.normalized, second.normalized, contract):
        return 0.0
    passed, lexical = _cheap_similarity(first, second, contract)
    return _refine_similarity(first, second, lexical) if passed else lexical


def _build_groups(
    values: list[str],
    monitor: _RuntimeMonitor,
) -> tuple[list[_ValueGroup], dict[str, int], int]:
    normalized_to_ordinals: dict[str, list[int]] = defaultdict(list)
    raw_by_normalized: dict[str, Counter[str]] = defaultdict(Counter)
    for ordinal, value in enumerate(values):
        normalized = normalize_near_duplicate_text(value)
        normalized_to_ordinals[normalized].append(ordinal)
        raw_by_normalized[normalized][value] += 1
        if ordinal % 128 == 0:
            monitor.check("normalization")

    groups: list[_ValueGroup] = []
    raw_exact = 0
    normalized_exact = 0
    raw_exact_groups = 0
    normalized_exact_groups = 0
    memory_estimate = 0
    for normalized in sorted(normalized_to_ordinals):
        ordinals = normalized_to_ordinals[normalized]
        raw_counts = raw_by_normalized[normalized]
        total_pairs = len(ordinals) * (len(ordinals) - 1) // 2
        raw_pairs = sum(count * (count - 1) // 2 for count in raw_counts.values())
        raw_exact += raw_pairs
        normalized_exact += total_pairs - raw_pairs
        raw_exact_groups += sum(count > 1 for count in raw_counts.values())
        normalized_exact_groups += int(len(ordinals) > 1 and len(raw_counts) > 1)
        fingerprint = _fingerprint_normalized(normalized)
        groups.append(_ValueGroup(fingerprint, tuple(ordinals)))
        memory_estimate += (
            sys.getsizeof(normalized)
            + (len(fingerprint.character_ngrams) + len(fingerprint.token_ngrams)) * 36
            + len(fingerprint.minhash) * 8
            + len(ordinals) * 8
        )
        if len(groups) % 128 == 0:
            monitor.check("cheap_signature", memory_estimate)
    monitor.check("cheap_signature", memory_estimate)
    return groups, {
        "raw_exact_excluded_groups": raw_exact_groups,
        "raw_exact_excluded_pairs": raw_exact,
        "normalized_exact_excluded_groups": normalized_exact_groups,
        "normalized_exact_excluded_pairs": normalized_exact,
    }, memory_estimate


def _lsh_candidates(
    groups: list[_ValueGroup],
    accumulator: _CandidateAccumulator,
) -> None:
    simhash_buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    minhash_buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for ordinal, group in enumerate(groups):
        fingerprint = group.fingerprint
        if not fingerprint.normalized:
            continue
        for band in range(4):
            simhash_buckets[(band, (fingerprint.simhash >> (band * 16)) & 0xFFFF)].append(ordinal)
        for band in range(4):
            start = band * 4
            minhash_buckets[(band, *fingerprint.minhash[start : start + 4])].append(ordinal)

    bucket_count = 0
    for buckets in (simhash_buckets, minhash_buckets):
        for indices in buckets.values():
            bucket_count += 1
            for first, second in combinations(indices, 2):
                accumulator.offer(first, second)
            if bucket_count % 128 == 0:
                accumulator.monitor.check("lsh_candidate_generation")


def _histogram(scores: Iterable[float]) -> dict[str, int]:
    result = {
        "review_0_90_to_0_93": 0,
        "review_0_93_to_0_97": 0,
        "blocked_0_97_to_1_00": 0,
    }
    for score in scores:
        if score >= BLOCKED_CANDIDATE_THRESHOLD:
            result["blocked_0_97_to_1_00"] += 1
        elif score >= 0.93:
            result["review_0_93_to_0_97"] += 1
        else:
            result["review_0_90_to_0_93"] += 1
    return result


def _connected_groups(pairs: Iterable[tuple[int, int]]) -> tuple[int, int]:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for first, second in pairs:
        adjacency[first].add(second)
        adjacency[second].add(first)
    visited: set[int] = set()
    group_count = 0
    for start in adjacency:
        if start in visited:
            continue
        group_count += 1
        stack = [start]
        visited.add(start)
        while stack:
            for neighbor in adjacency[stack.pop()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
    return group_count, len(visited)


def _analyze_field(
    values: list[str],
    contract: NearDuplicatePerformanceContract,
    monitor: _RuntimeMonitor,
    *,
    candidate_pair_budget: int,
    expensive_comparison_budget: int,
) -> tuple[dict[str, Any], dict[tuple[int, int], float], dict[str, int]]:
    groups, exclusion, base_memory = _build_groups(values, monitor)
    accumulator = _CandidateAccumulator(
        groups,
        contract,
        monitor,
        base_memory,
        candidate_pair_budget,
    )
    _lsh_candidates(groups, accumulator)

    accepted: dict[tuple[int, int], float] = {}
    length_rejected = 0
    cheap_rejected = 0
    cheap_passed = 0
    expensive = 0
    for group_pair in sorted(accumulator.group_pairs):
        first = groups[group_pair[0]].fingerprint
        second = groups[group_pair[1]].fingerprint
        if not _length_filter(first.normalized, second.normalized, contract):
            length_rejected += 1
            continue
        passed, lexical = _cheap_similarity(first, second, contract)
        if not passed:
            cheap_rejected += 1
            continue
        cheap_passed += 1
        if expensive >= expensive_comparison_budget:
            raise NearDuplicateScanError("EXPENSIVE_COMPARISON_LIMIT_EXCEEDED")
        expensive += 1
        score = _refine_similarity(first, second, lexical)
        if score >= REVIEW_CANDIDATE_THRESHOLD:
            for first_record in groups[group_pair[0]].record_ordinals:
                for second_record in groups[group_pair[1]].record_ordinals:
                    accepted[(first_record, second_record)] = score
        if expensive % 128 == 0:
            monitor.check(
                "expensive_similarity_refinement",
                base_memory + len(accumulator.group_pairs) * 96 + len(accepted) * 80,
            )
    monitor.check(
        "aggregate_result",
        base_memory + len(accumulator.group_pairs) * 96 + len(accepted) * 80,
    )
    candidate_groups, candidate_records = _connected_groups(accepted)
    summary = {
        "scanned": len(values),
        "candidate_groups": candidate_groups,
        "candidate_records": candidate_records,
        "candidate_pairs": len(accepted),
        "blocked_candidate_pairs": sum(
            score >= BLOCKED_CANDIDATE_THRESHOLD for score in accepted.values()
        ),
        **exclusion,
    }
    metrics = {
        "raw_candidate_pairs": accumulator.raw_candidate_pairs,
        "deduplicated_candidate_pairs": accumulator.record_pair_count,
        "duplicate_candidate_pairs_removed": accumulator.duplicate_candidate_pairs_removed,
        "deduplicated_group_pairs": len(accumulator.group_pairs),
        "length_filter_rejected": length_rejected,
        "cheap_filter_passed": cheap_passed,
        "cheap_similarity_rejected": cheap_rejected,
        "expensive_comparisons": expensive,
    }
    return summary, accepted, metrics


def _score_summary(scores: dict[tuple[int, int], float]) -> dict[str, Any]:
    groups, records = _connected_groups(scores)
    return {
        "candidate_groups": groups,
        "candidate_records": records,
        "candidate_pairs": len(scores),
        "blocked_candidate_pairs": sum(
            score >= BLOCKED_CANDIDATE_THRESHOLD for score in scores.values()
        ),
    }


def _cross_split_scores(
    scores: dict[tuple[int, int], float], splits: list[str]
) -> dict[tuple[int, int], float]:
    return {
        pair: score for pair, score in scores.items() if splits[pair[0]] != splits[pair[1]]
    }


def _pair_exact_exclusions(
    questions: list[str], answers: list[str]
) -> dict[str, int]:
    raw_counts: Counter[tuple[str, str]] = Counter(zip(questions, answers))
    normalized_raw_counts: dict[tuple[str, str], Counter[tuple[str, str]]] = defaultdict(Counter)
    for question, answer in zip(questions, answers):
        normalized_raw_counts[
            (normalize_near_duplicate_text(question), normalize_near_duplicate_text(answer))
        ][(question, answer)] += 1

    raw_pairs = sum(count * (count - 1) // 2 for count in raw_counts.values())
    normalized_pairs = 0
    normalized_groups = 0
    for variants in normalized_raw_counts.values():
        total = sum(variants.values())
        total_pairs = total * (total - 1) // 2
        variant_raw_pairs = sum(count * (count - 1) // 2 for count in variants.values())
        normalized_pairs += total_pairs - variant_raw_pairs
        normalized_groups += int(total > 1 and len(variants) > 1)
    return {
        "raw_exact_excluded_groups": sum(count > 1 for count in raw_counts.values()),
        "raw_exact_excluded_pairs": raw_pairs,
        "normalized_exact_excluded_groups": normalized_groups,
        "normalized_exact_excluded_pairs": normalized_pairs,
    }


def _pair_summary(
    question_scores: dict[tuple[int, int], float],
    answer_scores: dict[tuple[int, int], float],
    splits: list[str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[tuple[int, int], float], dict[str, dict[tuple[int, int], float]]]:
    pair_scores = {
        pair: min(question_scores[pair], answer_scores[pair])
        for pair in question_scores.keys() & answer_scores.keys()
    }
    cross_scores = {
        "question": _cross_split_scores(question_scores, splits),
        "answer": _cross_split_scores(answer_scores, splits),
        "qa_pair": _cross_split_scores(pair_scores, splits),
    }
    pair_summary = _score_summary(pair_scores)
    cross_summary = {name: _score_summary(scores) for name, scores in cross_scores.items()}
    return pair_summary, cross_summary, pair_scores, cross_scores


def summarize_near_duplicates(
    records: dict[str, Iterable[tuple[str, str]]],
    *,
    execution_id: str = "SYNTHETIC",
    contract: NearDuplicatePerformanceContract = DEFAULT_PERFORMANCE_CONTRACT,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
    _monitor: _RuntimeMonitor | None = None,
) -> dict[str, Any]:
    """Analyze bounded synthetic or already-approved records without returning values."""

    contract.validate()
    if not isinstance(execution_id, str) or not _SAFE_EXECUTION_ID.fullmatch(execution_id):
        raise NearDuplicateScanError("INVALID_EXECUTION_ID")
    monitor = _monitor or _RuntimeMonitor(contract, clock=clock, cancelled=cancelled)
    splits: list[str] = []
    questions: list[str] = []
    answers: list[str] = []
    source_values: list[str] = []
    for split in ("training", "validation"):
        for record in records.get(split, ()):
            if not isinstance(record, (tuple, list)) or len(record) != 2:
                raise NearDuplicateScanError("INVALID_RECORD_SHAPE")
            question, answer = record
            if not isinstance(question, str) or not isinstance(answer, str):
                raise NearDuplicateScanError("FIELD_TYPE_MISMATCH")
            splits.append(split)
            questions.append(question)
            answers.append(answer)
            source_values.extend((question, answer))
    monitor.check("records_loaded")

    question_summary, question_scores, question_metrics = _analyze_field(
        questions,
        contract,
        monitor,
        candidate_pair_budget=contract.maximum_total_pairs,
        expensive_comparison_budget=contract.maximum_expensive_comparisons,
    )
    remaining_candidate_pairs = (
        contract.maximum_total_pairs - question_metrics["deduplicated_candidate_pairs"]
    )
    remaining_expensive_comparisons = (
        contract.maximum_expensive_comparisons - question_metrics["expensive_comparisons"]
    )
    answer_summary, answer_scores, answer_metrics = _analyze_field(
        answers,
        contract,
        monitor,
        candidate_pair_budget=remaining_candidate_pairs,
        expensive_comparison_budget=remaining_expensive_comparisons,
    )
    pair_summary, cross_summary, pair_scores, cross_scores = _pair_summary(
        question_scores, answer_scores, splits
    )
    pair_summary = {
        "scanned": len(questions),
        **_pair_exact_exclusions(questions, answers),
        **pair_summary,
    }
    monitor.check("completed")

    result = {
        "dataset_id": DATASET_ID,
        "execution_id": execution_id,
        "comparison": "bounded_lexical_near_duplicate_v2",
        "question_source": {
            "canonical_component": "sftdata",
            "sftlabel_question": "skipped_verified_exact_copy",
        },
        "normalization": {
            "unicode": "NFC",
            "trim": True,
            "whitespace_collapse": True,
            "newline_normalization": True,
            "meaning_change": False,
            "morphology": False,
            "llm": False,
        },
        "similarity_methods": {
            "character_ngrams": [3, 4],
            "token_ngrams": [1, 2],
            "simhash_bits": SIMHASH_BITS,
            "minhash_permutations": MINHASH_PERMUTATIONS,
            "sequence_quick_ratio": True,
        },
        "threshold": {
            "review_candidate": REVIEW_CANDIDATE_THRESHOLD,
            "blocked_candidate": BLOCKED_CANDIDATE_THRESHOLD,
            "status": "not_approved",
        },
        "question": question_summary,
        "answer": answer_summary,
        "qa_pair": pair_summary,
        "cross_split": cross_summary,
        "similarity": {
            "histogram": {
                "question": _histogram(question_scores.values()),
                "answer": _histogram(answer_scores.values()),
                "qa_pair": _histogram(pair_scores.values()),
                "cross_split_question": _histogram(cross_scores["question"].values()),
                "cross_split_answer": _histogram(cross_scores["answer"].values()),
                "cross_split_qa_pair": _histogram(cross_scores["qa_pair"].values()),
            }
        },
        "performance": {
            "candidate_generation_bounded": True,
            "candidate_generation_deterministic": True,
            "full_pair_matrix": False,
            "question": question_metrics,
            "answer": answer_metrics,
            "raw_candidate_pairs": question_metrics["raw_candidate_pairs"] + answer_metrics["raw_candidate_pairs"],
            "deduplicated_candidate_pairs": question_metrics["deduplicated_candidate_pairs"] + answer_metrics["deduplicated_candidate_pairs"],
            "expensive_comparisons": question_metrics["expensive_comparisons"] + answer_metrics["expensive_comparisons"],
            "total_expensive_comparisons": question_metrics["expensive_comparisons"] + answer_metrics["expensive_comparisons"],
            "peak_memory_estimate_bytes": monitor.peak_memory_estimate_bytes,
            "elapsed_seconds": monitor.elapsed_seconds(),
            "final_phase": monitor.phase,
            "contract_status": "proposed_not_approved",
        },
        "policy": {
            "implementation": "draft",
            "label": "REVIEW_REQUIRED",
            "automatic_delete": False,
            "automatic_canonical": False,
            "automatic_split_change": False,
            "automatic_filtering": False,
        },
        "safety": {
            "raw_output": False,
            "substring_output": False,
            "preview_output": False,
            "data_id_output": False,
            "hash_output": False,
            "archive_path_output": False,
            "temporary_files": False,
            "worker_processes": False,
            "stdout_leak": False,
            "stderr_leak": False,
            "exception_leak": False,
        },
        "status": "completed",
        "execution_allowed": False,
    }
    guarded = guard_safe_output(result, source_values)
    source_values.clear()
    if guarded is not None:
        raise NearDuplicateScanError(guarded["error_code"])
    return result


def deterministic_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic aggregate excluding runtime-only observations."""

    payload = {**result, "performance": {**result["performance"]}}
    payload["performance"].pop("elapsed_seconds", None)
    return payload


def _scan_once(
    package_root: Path,
    *,
    execution_id: str,
    contract: NearDuplicatePerformanceContract,
    clock: Callable[[], float],
    cancelled: Callable[[], bool],
) -> dict[str, Any]:
    monitor = _RuntimeMonitor(contract, clock=clock, cancelled=cancelled)
    monitor.check("archive_contract")
    archives = _archive_contract(package_root)
    monitor.check("archive_contract")
    records: dict[str, list[tuple[str, str]]] = {"training": [], "validation": []}
    loaded_records = 0
    loaded_memory_estimate = 0
    try:
        for split in ("training", "validation"):
            with zipfile.ZipFile(archives[(split, "sftdata")]) as data_archive, zipfile.ZipFile(
                archives[(split, "sftlabel")]
            ) as label_archive:
                with data_archive.open(_entry_for(data_archive, "sftdata"), "r") as data_source, label_archive.open(
                    _entry_for(label_archive, "sftlabel"), "r"
                ) as label_source:
                    for data_record, label_record in zip_longest(
                        _iter_data_info(data_source),
                        _iter_data_info(label_source),
                        fillvalue=_MISSING,
                    ):
                        if data_record is _MISSING or label_record is _MISSING:
                            raise NearDuplicateScanError("COMPONENT_RECORD_COUNT_MISMATCH")
                        question = _string_field(data_record, "sftdata", ("question",))
                        answer = _string_field(label_record, "sftlabel", ("answer", "contents"))
                        records[split].append((question, answer))
                        loaded_records += 1
                        loaded_memory_estimate += (
                            sys.getsizeof(question) + sys.getsizeof(answer) + 72
                        )
                        data_record.clear()
                        label_record.clear()
                        if loaded_records % 128 == 0:
                            monitor.check("archive_stream_read", loaded_memory_estimate)
            if len(records[split]) != EXPECTED_RECORDS[split]:
                raise NearDuplicateScanError("RECORD_COUNT_DRIFT")
        monitor.check("archive_stream_read", loaded_memory_estimate)
        return summarize_near_duplicates(
            records,
            execution_id=execution_id,
            contract=contract,
            clock=clock,
            cancelled=cancelled,
            _monitor=monitor,
        )
    except NearDuplicateScanError:
        raise
    except JoinIntegrityError as exc:
        raise NearDuplicateScanError(exc.code) from None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, OverflowError):
        raise NearDuplicateScanError("ARCHIVE_READ_FAILED") from None
    finally:
        records.clear()


def scan_aihub_71748_near_duplicates(
    package_root: str | Path,
    *,
    execution_id: str,
    contract: NearDuplicatePerformanceContract = DEFAULT_PERFORMANCE_CONTRACT,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Run one separately approved scan; caller owns the single-use approval."""

    root = Path(package_root)
    if not root.is_dir():
        return {
            "status": "blocked",
            "error_code": "PACKAGE_ROOT_MISSING",
            "full_scan_count": 0,
            "execution_allowed": False,
        }
    try:
        result = _scan_once(
            root,
            execution_id=execution_id,
            contract=contract,
            clock=clock,
            cancelled=cancelled,
        )
        result["full_scan_count"] = 1
        return result
    except NearDuplicateScanError as exc:
        return {
            "status": "blocked",
            "error_code": exc.code,
            "full_scan_count": 1,
            "execution_allowed": False,
        }
