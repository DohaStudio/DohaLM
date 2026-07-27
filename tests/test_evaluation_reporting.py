from pathlib import Path

from src.evaluation.reporting import compare_completed_results, comparison_status, leaderboard_row


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
