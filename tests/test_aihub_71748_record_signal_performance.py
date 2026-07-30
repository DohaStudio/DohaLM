from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from difflib import SequenceMatcher
import hashlib
import json

import src.data.aihub_71748_pii as pii
import src.data.processing.aihub_71748_processor as processor
from src.data.aihub_71748_near_duplicate import normalize_near_duplicate_text
from src.data.aihub_71748_pii import _detect_text, _risk
from src.data.processing.aihub_71748_processor import JoinedRecord, RecordSignal


def _legacy_record_signals(
    records: tuple[JoinedRecord, ...],
    *,
    review_min: float,
    high_similarity_min: float,
) -> tuple[RecordSignal, ...]:
    """Pre-hotfix reference used only to prove policy-result equivalence."""

    signals = [RecordSignal() for _ in records]
    normalized = [
        normalize_near_duplicate_text(record.question + "\n" + record.answer)
        for record in records
    ]
    exact_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    answers_by_question: dict[str, set[str]] = defaultdict(set)
    for index, record in enumerate(records):
        exact_groups[(record.question, record.answer)].append(index)
        answers_by_question[record.question].add(record.answer)
        types = set(_detect_text(record.question)["types"]) | set(
            _detect_text(record.answer)["types"]
        )
        if _risk(types) in {"critical", "high", "medium"}:
            signals[index] = RecordSignal(pii="exclude")
    assert not any(len(answers) > 1 for answers in answers_by_question.values())
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        training = [index for index in group if records[index].split == "training"]
        keep = training[0] if training else group[0]
        for index in group:
            if index != keep:
                values = dict(signals[index].__dict__)
                values["exact_duplicate"] = "duplicate"
                signals[index] = RecordSignal(**values)

    grams = []
    for value in normalized:
        normalized_again = normalize_near_duplicate_text(value)
        grams.append(
            frozenset(
                normalized_again[index : index + 3]
                for index in range(max(1, len(normalized_again) - 2))
            )
        )
    postings: dict[str, list[int]] = defaultdict(list)
    candidates: set[tuple[int, int]] = set()
    for right, features in enumerate(grams):
        counts: dict[int, int] = defaultdict(int)
        for feature in features:
            for left in postings[feature]:
                counts[left] += 1
        for left, overlap in counts.items():
            denominator = len(grams[left] | features)
            if denominator and overlap / denominator >= max(0.25, review_min - 0.5):
                candidates.add((left, right))
        for feature in features:
            postings[feature].append(right)
    for left, right in sorted(candidates):
        if (records[left].question, records[left].answer) == (
            records[right].question,
            records[right].answer,
        ):
            continue
        score = SequenceMatcher(None, normalized[left], normalized[right]).ratio()
        if score < review_min:
            continue
        cross_split = records[left].split != records[right].split
        if cross_split:
            for index in (left, right):
                if records[index].split != "validation":
                    continue
                values = dict(signals[index].__dict__)
                values["near_duplicate"] = "duplicate"
                values["leakage"] = "exclude"
                signals[index] = RecordSignal(**values)
        elif records[right].split == "validation" or score >= high_similarity_min:
            values = dict(signals[right].__dict__)
            values["near_duplicate"] = "duplicate"
            signals[right] = RecordSignal(**values)
    return tuple(signals)


def _golden_records() -> tuple[JoinedRecord, ...]:
    base = JoinedRecord(
        "training",
        "synthetic-1",
        "Explain deterministic synthetic processing.",
        "A deterministic synthetic response for policy testing.",
        "qa",
        "general",
    )
    exact = replace(base, source_id="synthetic-2")
    near = replace(
        base,
        source_id="synthetic-3",
        question="Explain deterministic synthetic processing!",
        answer="A deterministic synthetic response for policy testing!",
    )
    cross_split = replace(
        base,
        split="validation",
        source_id="synthetic-4",
        question="Explain deterministic synthetic processing?",
        answer="A deterministic synthetic response for policy testing?",
    )
    unrelated = replace(
        base,
        source_id="synthetic-5",
        question="Count symbols 1 2 3 + - = in a synthetic sample.",
        answer="Symbols and numbers remain deterministic.",
    )
    pii = replace(
        base,
        source_id="synthetic-6",
        question="Send the synthetic result to test@example.com.",
        answer="Synthetic contact data is excluded.",
    )
    return base, exact, near, cross_split, unrelated, pii


def test_optimized_signals_match_legacy_golden_policy_results() -> None:
    records = _golden_records()
    expected = _legacy_record_signals(
        records,
        review_min=0.90,
        high_similarity_min=0.97,
    )

    actual = processor.recompute_record_signals(
        records,
        review_min=0.90,
        high_similarity_min=0.97,
    )

    assert actual == expected


def test_record_text_is_normalized_once_per_derived_value(monkeypatch) -> None:
    records = _golden_records()
    calls = 0
    original = processor.normalize_near_duplicate_text

    def counted(value: str) -> str:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(processor, "normalize_near_duplicate_text", counted)
    processor.recompute_record_signals(
        records,
        review_min=0.90,
        high_similarity_min=0.97,
    )

    assert calls == len(records) * 2


def test_optimized_signals_are_deterministic_for_same_order() -> None:
    records = _golden_records()

    first = processor.recompute_record_signals(
        records,
        review_min=0.90,
        high_similarity_min=0.97,
    )
    second = processor.recompute_record_signals(
        records,
        review_min=0.90,
        high_similarity_min=0.97,
    )

    assert first == second
    first_fingerprint = hashlib.sha256(
        json.dumps(
            [signal.__dict__ for signal in first],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    second_fingerprint = hashlib.sha256(
        json.dumps(
            [signal.__dict__ for signal in second],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert first_fingerprint == second_fingerprint


def test_pii_patterns_are_not_compiled_per_record(monkeypatch) -> None:
    def unexpected_compile(*_args, **_kwargs):
        raise AssertionError("regex compiled during record signal calculation")

    monkeypatch.setattr(pii.re, "compile", unexpected_compile)

    processor.recompute_record_signals(
        _golden_records(),
        review_min=0.90,
        high_similarity_min=0.97,
    )
