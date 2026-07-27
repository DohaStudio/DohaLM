from pathlib import Path
from types import SimpleNamespace
import tempfile

import torch

from src.evaluation.config import EvaluationConfig
from src.evaluation.datasets import deterministic_indices
from src.evaluation.runner import (
    _aggregate_teacher_forced,
    _model_digest,
    _prepare_model,
    _publish,
    _quick_full_comparison,
    publish_failure,
)
from src.evaluation.artifacts import ArtifactRegistry


def test_quick_subset_is_deterministic() -> None:
    first = deterministic_indices(100, 12, seed=17, dataset_fingerprint="sha256:test")
    second = deterministic_indices(100, 12, seed=17, dataset_fingerprint="sha256:test")
    assert first == second
    assert len(first) == len(set(first)) == 12


def test_full_subset_uses_every_sequence_in_source_order() -> None:
    assert deterministic_indices(14329, 14329, seed=17, dataset_fingerprint="sha256:test") == list(range(14329))


def test_eos_diagnostics_cover_target_masking_and_packing() -> None:
    class Model:
        def __call__(self, ids, attention_mask=None):
            return SimpleNamespace(logits=torch.zeros((*ids.shape, 16), dtype=torch.float32))
    class Processor:
        def id_to_piece(self, token_id):
            return "한" if token_id == 8 else f"piece{token_id}"
    tokenizer = SimpleNamespace(vocab_size=16, processor=Processor())
    batch = {
        "input_ids": torch.tensor([[2, 8, 3, 0]], dtype=torch.long),
        "labels": torch.tensor([[2, 8, 3, -100]], dtype=torch.long),
        "attention_mask": torch.tensor([[1, 1, 1, 0]], dtype=torch.bool),
    }
    aggregate, _ = _aggregate_teacher_forced(
        Model(), [batch], tokenizer, torch.device("cpu"), use_amp=False, timeout_seconds=10,
    )
    eos = aggregate["eos_diagnostics"]
    assert eos["target_tokens"] == 1
    assert eos["masked_eos_tokens"] == 0
    assert eos["packing_boundary_preserved"] is True
    assert eos["included_in_loss"] is True


def test_quick_full_comparison_keeps_policy_unapproved() -> None:
    categories = {"eos": {"accuracy": 0.1, "top1_accuracy": 0.1}}
    buckets = {"0-31": {"accuracy": 0.1, "top1_accuracy": 0.1}}
    full_metrics = {
        "perplexity": {"loss": 6.3, "perplexity": 544.0},
        "next_token": {"top1_accuracy": .18, "top5_accuracy": .30, "top10_accuracy": .37, "token_type_accuracy": categories},
        "position": {"packed_top1": .18, "rebased": {"top1_accuracy": .19}, "position_gap": .01, "buckets": buckets},
    }
    quick_metrics = {
        "perplexity": {"loss": 6.28, "perplexity": 535.0},
        "next_token": {"top1_accuracy": .182, "top5_accuracy": .309, "top10_accuracy": .370, "token_type_accuracy": categories},
        "position": {"packed_top1": .182, "rebased": {"top1_accuracy": .193}, "position_gap": .011, "buckets": buckets},
    }
    quick_result = {
        "manifest": {"artifact_id": "candidate-a-final", "profile": "quick", "result_fingerprint": "sha256:quick", "evaluation_id": "quick-1"},
        "metrics": quick_metrics,
        "resource": {"evaluation_seconds": 1.0, "peak_gpu_reserved_bytes": 10},
    }
    result = _quick_full_comparison(
        full_metrics, {"evaluation_seconds": 100.0, "peak_gpu_reserved_bytes": 10}, quick_result,
    )
    assert result["representativeness_status"] == "insufficient_evidence"
    assert result["policy_status"] == "proposed_not_approved"


def test_initial_model_is_evaluation_only_and_unchanged() -> None:
    config = EvaluationConfig.from_yaml(Path("configs/evaluation.example.yaml"))
    artifact = ArtifactRegistry.load(Path("configs/evaluation-artifacts.example.yaml")).get("initial-seed-17")
    model, checksum = _prepare_model(config, artifact, torch.device("cpu"))
    before = _model_digest(model)
    with torch.inference_mode():
        model(torch.tensor([[2, 8, 3]], dtype=torch.long))
    assert checksum is None
    assert model.training is False
    assert not any(parameter.requires_grad for parameter in model.parameters())
    assert _model_digest(model) == before


def test_atomic_output_rejects_existing_run() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "evaluation"
        _publish(output, {"reports/summary.json": {"status": "completed"}})
        assert (output / "manifests/checksums.json").is_file()
        try:
            _publish(output, {"reports/summary.json": {"status": "replacement"}})
        except Exception as exc:
            assert getattr(exc, "code", None) == "EVALUATION_OUTPUT_EXISTS"
        else:
            raise AssertionError("existing evaluation output was overwritten")


def test_failure_report_is_text_free_and_immutable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        class Config:
            output_root = "analysis/evaluation"
            def external_path(self, logical: str) -> Path:
                return Path(temporary) / logical
        error = type("Failure", (RuntimeError,), {"code": "TEST_FAILURE"})("sensitive detail")
        assert publish_failure(Config(), "artifact", "evaluation-1", error) is True
        failure = (Path(temporary) / "analysis/evaluation/artifact/evaluation-1/failures/failure.json").read_text(encoding="utf-8")
        assert "sensitive detail" not in failure
        assert "TEST_FAILURE" in failure
        assert publish_failure(Config(), "artifact", "evaluation-1", error) is False
