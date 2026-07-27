import json
from pathlib import Path

from src.data.sequence_packing import PackingPolicy, pack_sequences
from src.evaluation.diagnostics import (
    CANDIDATE_B_TRAINING_STATUS,
    EVALUATION_POLICY_APPROVAL_DATE,
    EVALUATION_POLICY_STATUS,
    QUICK_V2_STATUS,
    REPRESENTATIVENESS_THRESHOLDS,
    _js_divergence,
    _ks,
    _psi,
    _rank_summary,
    _reference_evaluation_id,
    classify_eos_offset,
    inspect_packed_rows,
)


def test_approved_evaluation_policy_status_contract() -> None:
    assert EVALUATION_POLICY_STATUS == "approved"
    assert EVALUATION_POLICY_APPROVAL_DATE == "2026-07-27"
    assert CANDIDATE_B_TRAINING_STATUS == "not_approved"
    assert QUICK_V2_STATUS == "planned_awaiting_separate_approval"
    assert REPRESENTATIVENESS_THRESHOLDS["representative"] == {
        "loss": 0.05, "top1": 0.005, "top5": 0.0075, "top10": 0.01, "position_gap": 0.005,
    }
    assert REPRESENTATIVENESS_THRESHOLDS["approximately_representative"] == {
        "loss": 0.10, "top1": 0.015, "top5": 0.02, "top10": 0.02, "position_gap": 0.015,
    }


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_seventeen_position_zero_eos_are_completely_classified() -> None:
    offsets = [index * 256 for index in range(17)] + [1, 255, 257]
    reasons = [classify_eos_offset(offset) for offset in offsets]
    assert reasons.count("eos_shifted_out_of_target") == 17
    assert set(reasons) == {"eos_shifted_out_of_target", "eos_preserved"}


def test_packed_inspector_distinguishes_input_eos_from_shifted_target(tmp_path: Path) -> None:
    rows = [{
        "input_ids": [3, 2, 8, 3, 0, 0],
        "labels": [3, 2, 8, 3, -100, -100],
        "attention_mask": [1, 1, 1, 1, 0, 0],
    }]
    path = tmp_path / "packed.jsonl"
    _write_rows(path, rows)
    report = inspect_packed_rows(path, context_length=6)
    assert report["input_eos_tokens"] == 2
    assert report["target_eos_tokens"] == 1
    assert report["position_zero_eos"] == 1
    assert report["masked_eos_tokens"] == 0


def test_continuous_packing_label_shift_and_padding_cases() -> None:
    policy = PackingPolicy(context_length=8, mode="continuous", append_eos=False, remainder="pad")
    cases = [
        [[2, 8, 3]],
        [[2, 8, 8, 8, 8, 8, 8, 3]],
        [[2, 8, 8, 8, 8, 8, 3]],
        [[2, 8, 8, 8, 8, 8, 8, 8, 3]],
        [[2, 8, 3], [2, 9, 3]],
        [[2, 8, 8, 8, 8, 8, 8, 3]],
        [[2, 8, 3], [2, 9, 3]],
        [[2, 8, 3]],
        [[2, 3]],
    ]
    for records in cases:
        packed = list(pack_sequences(records, policy))
        assert packed
        for row in packed:
            assert len(row["input_ids"]) == len(row["labels"]) == len(row["attention_mask"]) == 8
            assert all(label == -100 for label, mask in zip(row["labels"], row["attention_mask"]) if mask == 0)
            assert all(label == token for token, label, mask in zip(row["input_ids"], row["labels"], row["attention_mask"]) if mask == 1)


def test_eos_at_position_255_is_target_and_next_block_position_zero_is_not() -> None:
    policy = PackingPolicy(context_length=256, mode="continuous", append_eos=False, remainder="pad")
    first = [2] + [8] * 254 + [3]
    rows = list(pack_sequences([first, [3, 2, 9, 3]], policy))
    assert rows[0]["input_ids"][255] == 3
    assert rows[0]["labels"][255] == 3
    assert rows[1]["input_ids"][0] == 3
    assert rows[1]["labels"][0] == 3
    assert rows[1]["labels"][1] == 2


def test_eos_rank_summary_includes_logit_probability_margin_and_bands() -> None:
    rows = [
        {"rank": 1.0, "logit": 3.0, "probability": 0.5, "logit_margin": 0.0, "probability_margin": 0.0},
        {"rank": 4.0, "logit": 1.0, "probability": 0.2, "logit_margin": 2.0, "probability_margin": 0.3},
        {"rank": 8.0, "logit": -1.0, "probability": 0.1, "logit_margin": 4.0, "probability_margin": 0.4},
        {"rank": 11.0, "logit": -2.0, "probability": 0.01, "logit_margin": 5.0, "probability_margin": 0.5},
    ]
    report = _rank_summary(rows)
    assert report["rank_1_rate"] == 0.25
    assert report["rank_2_5_rate"] == 0.25
    assert report["rank_6_10_rate"] == 0.25
    assert report["rank_11_plus_rate"] == 0.25
    assert report["logit_distribution"]["median"] == 0.0


def test_diagnostic_references_must_use_selected_artifact() -> None:
    assert _reference_evaluation_id(
        "candidate-b-final:candidate-b-final-full-20260728-03",
        "candidate-b-final",
    ) == "candidate-b-final-full-20260728-03"
    try:
        _reference_evaluation_id(
            "candidate-a-final:candidate-a-final-full-20260727-01",
            "candidate-b-final",
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "BASELINE_REFERENCE_INVALID"
    else:
        raise AssertionError("cross-artifact diagnostic reference was accepted")


def test_distribution_distances_are_zero_for_equal_inputs() -> None:
    distribution = {"a": 0.25, "b": 0.75}
    assert _js_divergence(distribution, distribution) == 0.0
    assert _psi(distribution, distribution) == 0.0
    assert _ks([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
