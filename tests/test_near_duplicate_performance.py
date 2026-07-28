import pytest

import src.data.aihub_71748_near_duplicate as module
from src.data.aihub_71748_near_duplicate import (
    NearDuplicatePerformanceContract,
    NearDuplicateScanError,
    _Fingerprint,
    deterministic_result_payload,
    summarize_near_duplicates,
)


def _records(size: int):
    def value(index: int, salt: int) -> str:
        state = (index + 1) * 0x9E3779B1 ^ salt
        characters = []
        for _ in range(48):
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            characters.append(chr(65 + state % 26))
        return "".join(characters)

    records = [
        (
            value(index, 0xA5A5A5A5),
            value(index, 0x5A5A5A5A),
        )
        for index in range(size)
    ]
    if size >= 4:
        records[1] = (records[0][0] + "!", records[0][1] + "!")
        records[3] = (records[2][0] + "?", records[2][1] + "?")
    return records


@pytest.mark.parametrize("size", [100, 1_000, 5_000, 12_000])
def test_increasing_synthetic_benchmark_is_bounded(size: int):
    result = summarize_near_duplicates({"training": _records(size), "validation": ()})
    assert result["status"] == "completed"
    assert result["question"]["scanned"] == size
    assert result["answer"]["scanned"] == size
    assert result["qa_pair"]["candidate_groups"] >= (2 if size >= 4 else 0)
    assert result["performance"]["total_expensive_comparisons"] <= 100_000
    assert result["performance"]["peak_memory_estimate_bytes"] <= 512 * 1024 * 1024


def _colliding_fingerprint(normalized: str) -> _Fingerprint:
    return _Fingerprint(
        normalized=normalized,
        character_ngrams=frozenset({1, 2, 3}),
        token_ngrams=frozenset({4, 5}),
        simhash=0,
        minhash=tuple([0] * 16),
    )


def test_adversarial_same_lsh_bucket_fails_total_limit(monkeypatch):
    monkeypatch.setattr(module, "_fingerprint_normalized", _colliding_fingerprint)
    contract = NearDuplicatePerformanceContract(
        maximum_total_pairs=5,
        maximum_per_record=100,
    )
    with pytest.raises(NearDuplicateScanError, match="^CANDIDATE_PAIR_LIMIT_EXCEEDED$"):
        summarize_near_duplicates({"training": _records(8)}, contract=contract)


def test_per_record_candidate_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "_fingerprint_normalized", _colliding_fingerprint)
    contract = NearDuplicatePerformanceContract(
        maximum_total_pairs=100,
        maximum_per_record=1,
    )
    with pytest.raises(NearDuplicateScanError, match="^PER_RECORD_CANDIDATE_LIMIT_EXCEEDED$"):
        summarize_near_duplicates({"training": _records(4)}, contract=contract)


def test_expensive_comparison_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "_fingerprint_normalized", _colliding_fingerprint)
    contract = NearDuplicatePerformanceContract(
        maximum_total_pairs=100,
        maximum_per_record=100,
        maximum_expensive_comparisons=1,
    )
    with pytest.raises(NearDuplicateScanError, match="^EXPENSIVE_COMPARISON_LIMIT_EXCEEDED$"):
        summarize_near_duplicates({"training": _records(3)}, contract=contract)


def test_memory_budget_fails_closed():
    contract = NearDuplicatePerformanceContract(memory_budget_bytes=1)
    with pytest.raises(NearDuplicateScanError, match="^MEMORY_BUDGET_EXCEEDED$"):
        summarize_near_duplicates({"training": _records(2)}, contract=contract)


def test_runtime_budget_fails_closed_with_injected_clock():
    ticks = iter([0.0, 0.0, 1.0, 2.0, 3.0])
    contract = NearDuplicatePerformanceContract(runtime_budget_seconds=0.5)
    with pytest.raises(NearDuplicateScanError, match="^RUNTIME_BUDGET_EXCEEDED$"):
        summarize_near_duplicates(
            {"training": _records(2)},
            contract=contract,
            clock=lambda: next(ticks),
        )


def test_real_scan_runtime_budget_starts_before_archive_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(module.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(module, "_archive_contract", lambda _root: {})
    ticks = iter([0.0, 0.0, 1.0])
    contract = NearDuplicatePerformanceContract(runtime_budget_seconds=0.5)
    result = module.scan_aihub_71748_near_duplicates(
        tmp_path,
        execution_id="SYNTHETIC_ARCHIVE_TIMEOUT",
        contract=contract,
        clock=lambda: next(ticks),
    )
    assert result == {
        "status": "blocked",
        "error_code": "RUNTIME_BUDGET_EXCEEDED",
        "full_scan_count": 1,
        "execution_allowed": False,
    }


def test_cancellation_is_fail_closed_without_workers_or_temp_files():
    with pytest.raises(NearDuplicateScanError, match="^SCAN_CANCELLED$"):
        summarize_near_duplicates(
            {"training": _records(2)},
            cancelled=lambda: True,
        )


def test_candidate_pair_is_refined_once_after_dedup(monkeypatch):
    monkeypatch.setattr(module, "_fingerprint_normalized", _colliding_fingerprint)
    result = summarize_near_duplicates({"training": _records(2)})
    question = result["performance"]["question"]
    assert question["raw_candidate_pairs"] > question["deduplicated_candidate_pairs"]
    assert question["deduplicated_group_pairs"] == 1
    assert question["expensive_comparisons"] == 1


def test_deterministic_repeat_is_order_independent():
    records = _records(500)
    first = summarize_near_duplicates({"training": records})
    second = summarize_near_duplicates({"training": reversed(records)})
    assert deterministic_result_payload(first) == deterministic_result_payload(second)
