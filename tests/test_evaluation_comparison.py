import json
import tempfile
from pathlib import Path

from src.evaluation.artifacts import ArtifactRegistry
from src.evaluation.comparison import ARTIFACT_ORDER, _comparability, _delta, publish_quick_comparison


REGISTRY = Path("configs/evaluation-artifacts.example.yaml")


def _result(
    artifact_id: str,
    *,
    config_fingerprint: str = "sha256:config",
    dataset_fingerprint: str = "sha256:dataset",
    tokenizer_fingerprint: str = "sha256:tokenizer",
) -> dict:
    manifest = {
        "artifact_id": artifact_id, "status": "completed", "profile": "quick", "precision": "fp16",
        "dataset_identity": {"evaluation_fingerprint": dataset_fingerprint},
        "evaluation_subset_identity": {"index_fingerprint": "sha256:subset"},
        "tokenizer_fingerprint": tokenizer_fingerprint, "config_fingerprint": config_fingerprint,
        "prompt_set_fingerprint": "sha256:prompt", "result_fingerprint": f"sha256:{artifact_id}",
        "environment": {}, "started_at": "2026-07-27T00:00:00+00:00",
    }
    generation = {
        "eos_rate": 0.0, "average_generation_length": 16.0, "maximum_length_rate": 1.0,
        "repetition_rate": 0.2, "repeated_bigram_rate": 0.3, "repeated_trigram_rate": 0.4,
        "unique_token_ratio": 0.5, "distinct_1": 0.5, "distinct_2": 0.6, "distinct_3": 0.7,
        "degenerate_loop_rate": 0.1, "empty_rate": 0.0, "special_token_rate": 0.0,
        "unk_rate": 0.0, "byte_fallback_rate": 0.0,
    }
    metrics = {
        "perplexity": {
            "loss": 2.0, "perplexity": 7.0, "perplexity_overflow": False,
            "sequences": 16, "target_tokens": 1024, "batches": 2,
        },
        "next_token": {"top1_accuracy": 0.1, "top5_accuracy": 0.2, "top10_accuracy": 0.3},
        "position": {"packed_top1": 0.1, "packed_top5": 0.2, "packed_loss": 2.0,
                     "rebased": {"top1_accuracy": 0.1, "top5_accuracy": 0.2, "loss": 2.0},
                     "position_gap": 0.0, "buckets": {}},
        "generation": generation, "continuation": {"rows": []}, "stability": {},
    }
    resource = {"evaluation_seconds": 1.0, "tokens_per_second": 100.0,
                "peak_gpu_allocated_bytes": 1, "peak_gpu_reserved_bytes": 2, "cpu_working_set_bytes": 3}
    return {"manifest": manifest, "metrics": metrics, "resource": resource}


def test_comparison_identity_and_order_are_fail_closed() -> None:
    results = [_result(artifact_id) for artifact_id in ARTIFACT_ORDER]
    assert _comparability(results) == ("comparable", {})
    results[-1] = _result(ARTIFACT_ORDER[-1], config_fingerprint="sha256:other")
    assert _comparability(results)[0] == "incomparable_config"


def test_dataset_and_tokenizer_mismatches_are_fail_closed() -> None:
    dataset_results = [_result(artifact_id) for artifact_id in ARTIFACT_ORDER]
    dataset_results[-1] = _result(ARTIFACT_ORDER[-1], dataset_fingerprint="sha256:other")
    assert _comparability(dataset_results)[0] == "incomparable_dataset"
    tokenizer_results = [_result(artifact_id) for artifact_id in ARTIFACT_ORDER]
    tokenizer_results[-1] = _result(ARTIFACT_ORDER[-1], tokenizer_fingerprint="sha256:other")
    assert _comparability(tokenizer_results)[0] == "incomparable_config"


def test_memorization_only_artifact_is_not_in_official_order() -> None:
    assert ARTIFACT_ORDER == ("initial-seed-17", "pilot-100", "candidate-a-mid", "candidate-a-final")
    assert "gate7-overfit-final" not in ARTIFACT_ORDER


def test_delta_contains_loss_accuracy_and_generation_changes() -> None:
    left = {"artifact_id": "a", "loss": 3.0, "perplexity": 20.0, "top1": .1, "top5": .2,
            "top10": .3, "packed_top1": .1, "rebased_top1": .1, "position_gap": 0.0,
            "eos_rate": 0.0, "maximum_length_rate": 1.0, "adjacent_repetition": .2,
            "distinct_1": .5, "distinct_2": .6, "distinct_3": .7,
            "evaluation_seconds": 2.0, "tokens_per_second": 10.0, "peak_gpu_reserved_bytes": 4}
    right = {**left, "artifact_id": "b", "loss": 2.0, "perplexity": 10.0, "top1": .2,
             "adjacent_repetition": .3}
    value = _delta(left, right, "a_to_b")
    assert value["delta"]["loss"] == -1.0
    assert value["delta"]["top1"] == 0.1
    assert value["delta"]["perplexity_ratio"] == 0.5


def test_comparison_package_is_atomic_and_immutable(monkeypatch) -> None:
    results = {artifact_id: _result(artifact_id) for artifact_id in ARTIFACT_ORDER}
    monkeypatch.setattr("src.evaluation.comparison.load_completed_result", lambda config, reference: results[reference.split(":", 1)[0]])
    registry = ArtifactRegistry.load(REGISTRY)
    with tempfile.TemporaryDirectory() as temporary:
        class Config:
            output_root = "analysis/evaluation"
            def external_path(self, logical: str) -> Path:
                return Path(temporary) / logical
        ids = {artifact_id: "evaluation-1" for artifact_id in ARTIFACT_ORDER}
        result = publish_quick_comparison(Config(), registry, comparison_id="comparison-1", evaluation_ids=ids)
        output = Path(temporary) / "analysis/evaluation/comparisons/comparison-1"
        manifest = json.loads((output / "manifests/comparison.json").read_text(encoding="utf-8"))
        assert result["status"] == "comparable"
        assert manifest["artifact_order"] == list(ARTIFACT_ORDER)
        assert (output / "manifests/checksums.json").is_file()
        try:
            publish_quick_comparison(Config(), registry, comparison_id="comparison-1", evaluation_ids=ids)
        except Exception as exc:
            assert getattr(exc, "code", None) == "EVALUATION_OUTPUT_EXISTS"
        else:
            raise AssertionError("comparison output was overwritten")
