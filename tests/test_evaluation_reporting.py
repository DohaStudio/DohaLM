from pathlib import Path

from src.evaluation.config import EvaluationError
from src.evaluation.reporting import (
    compare_completed_results,
    compare_full_candidate_results,
    comparison_status,
    leaderboard_row,
)


def _result(dataset: str = "same", config: str = "same", status: str = "completed") -> dict:
    return {"manifest": {"dataset_identity": dataset, "config_fingerprint": config, "status": status}}


def test_comparison_fail_closed_statuses() -> None:
    assert comparison_status(_result(), _result()) == "comparable"
    assert comparison_status(_result("a"), _result("b")) == "incomparable_dataset"
    assert comparison_status(_result(config="a"), _result(config="b")) == "incomparable_config"
    assert comparison_status(_result(), _result(status="failed")) == "incomplete"


def test_leaderboard_preserves_metrics_without_composite_score() -> None:
    manifest = {
        "artifact_id": "candidate-a-final", "checkpoint_identity": {"global_step": 4883},
        "dataset_identity": {"evaluation_fingerprint": "sha256:e"}, "status": "completed", "result_fingerprint": "sha256:r",
    }
    metrics = {
        "perplexity": {"loss": 6.0, "perplexity": 403.0},
        "next_token": {"top1_accuracy": 0.2, "top5_accuracy": 0.4},
        "position": {"packed_top1": 0.2, "rebased": {"top1_accuracy": 0.1}},
        "generation": {"repetition_rate": 0.1, "eos_rate": 0.2},
    }
    row = leaderboard_row(manifest, metrics)
    assert row["artifact"] == "candidate-a-final"
    assert "score" not in row


def test_comparison_preserves_rows_without_ranking() -> None:
    manifest = {
        "artifact_id": "a", "checkpoint_identity": {"global_step": 1},
        "dataset_identity": {"evaluation_fingerprint": "sha256:e"},
        "config_fingerprint": "sha256:c", "status": "completed", "result_fingerprint": "sha256:r",
    }
    metrics = {
        "perplexity": {"loss": 2.0, "perplexity": 7.3}, "next_token": {"top1_accuracy": .1, "top5_accuracy": .2},
        "position": {"packed_top1": .1, "rebased": {"top1_accuracy": .1}}, "generation": {"repetition_rate": .2, "eos_rate": .0},
    }
    first = {"manifest": manifest, "metrics": metrics}
    second = {"manifest": {**manifest, "artifact_id": "b"}, "metrics": metrics}
    result = compare_completed_results([first, second])
    assert result["status"] == "comparable"
    assert result["composite_score_used"] is False


def test_leaderboard_separates_quick_and_full_profiles() -> None:
    document = Path("docs/evaluation/model-evaluation-leaderboard.md").read_text(encoding="utf-8")
    assert "| quick | 128 |" in document
    assert "| full | 14,329 |" in document
    assert "candidate-a-final-full-20260727-01" in Path(
        "docs/evaluation/candidate-a-final-full-result.md"
    ).read_text(encoding="utf-8")


def _full_result(artifact_id: str, *, prompt: str = "sha256:prompt", profile: str = "full") -> dict:
    manifest = {
        "artifact_id": artifact_id, "profile": profile, "status": "completed",
        "dataset_identity": {"evaluation_fingerprint": "sha256:dataset"},
        "tokenizer_fingerprint": "sha256:tokenizer", "model_fingerprint": "sha256:model",
        "prompt_set_fingerprint": prompt, "result_fingerprint": f"sha256:{artifact_id}",
    }
    category = {"top1_accuracy": .1, "top5_accuracy": .2, "top10_accuracy": .3, "mean_loss": 2.0}
    metrics = {
        "perplexity": {"loss": 2.0, "perplexity": 7.0},
        "next_token": {"top1_accuracy": .1, "top5_accuracy": .2, "top10_accuracy": .3,
                       "token_type_accuracy": {"eos": category}},
        "position": {"packed_top1": .1, "rebased": {"top1_accuracy": .1}, "position_gap": 0.0,
                     "buckets": {"0-31": {"top1_accuracy": .1}}},
    }
    resource = {"evaluation_seconds": 1.0, "tokens_per_second": 10.0,
                "peak_gpu_reserved_bytes": 2, "cpu_working_set_bytes": 3}
    return {"manifest": manifest, "metrics": metrics, "resource": resource}


def test_full_candidate_comparison_is_separate_from_quick_reference() -> None:
    result = compare_full_candidate_results(_full_result("candidate-a-final"), _full_result("candidate-b-final"))
    assert result["status"] == "completed"
    assert result["teacher_forced_metrics"] == "comparable"
    assert result["composite_score_used"] is False


def test_full_candidate_comparison_marks_generation_prompt_incomparable() -> None:
    result = compare_full_candidate_results(
        _full_result("candidate-a-final", prompt="sha256:historical"),
        _full_result("candidate-b-final", prompt="sha256:current"),
    )
    assert result["status"] == "completed_with_incomparable_generation_reference"
    assert result["generation_prompt_error_code"] == "GENERATION_PROMPT_INCOMPARABLE"


def test_quick_result_is_not_a_full_baseline() -> None:
    try:
        compare_full_candidate_results(
            _full_result("candidate-a-final", profile="quick"), _full_result("candidate-b-final"),
        )
    except EvaluationError as exc:
        assert exc.code == "BASELINE_REFERENCE_INVALID"
    else:
        raise AssertionError("Quick result was accepted as a Full baseline")
