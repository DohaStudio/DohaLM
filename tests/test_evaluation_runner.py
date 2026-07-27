from pathlib import Path
from types import SimpleNamespace
import tempfile

import torch

from src.data.checksums import checksum_value
from src.evaluation.config import EvaluationConfig
from src.evaluation.datasets import deterministic_indices
from src.evaluation.runner import (
    _aggregate_teacher_forced,
    _model_digest,
    _prepare_model,
    _publish,
    _quick_full_comparison,
    _validate_quick_reference,
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


def test_candidate_b_full_accepts_candidate_b_same_artifact_quick_reference() -> None:
    categories = {"eos": {"accuracy": 0.1, "top1_accuracy": 0.1}}
    buckets = {"0-31": {"accuracy": 0.1, "top1_accuracy": 0.1}}
    full_metrics = {
        "perplexity": {"loss": 5.5, "perplexity": 244.0},
        "next_token": {"top1_accuracy": .23, "top5_accuracy": .38, "top10_accuracy": .45, "token_type_accuracy": categories},
        "position": {"packed_top1": .23, "rebased": {"top1_accuracy": .24}, "position_gap": .01, "buckets": buckets},
    }
    quick_result = {
        "manifest": {
            "artifact_id": "candidate-b-final", "profile": "quick",
            "result_fingerprint": "sha256:quick-b", "evaluation_id": "quick-b-1",
        },
        "metrics": full_metrics,
        "resource": {"evaluation_seconds": 1.0, "peak_gpu_reserved_bytes": 10},
    }
    result = _quick_full_comparison(
        full_metrics,
        {"evaluation_seconds": 100.0, "peak_gpu_reserved_bytes": 10},
        quick_result,
        expected_artifact_id="candidate-b-final",
    )
    assert result["quick_evaluation_id"] == "quick-b-1"


def test_candidate_b_full_rejects_candidate_a_quick_as_direct_reference() -> None:
    quick_result = {
        "manifest": {
            "artifact_id": "candidate-a-final", "profile": "quick",
            "result_fingerprint": "sha256:quick-a", "evaluation_id": "quick-a-1",
        },
        "metrics": {},
        "resource": {},
    }
    try:
        _quick_full_comparison({}, {}, quick_result, expected_artifact_id="candidate-b-final")
    except TypeError:
        raise AssertionError("same-artifact Quick contract is not implemented")
    except Exception as exc:
        assert getattr(exc, "code", None) == "QUICK_REFERENCE_ARTIFACT_MISMATCH"
    else:
        raise AssertionError("cross-artifact Quick reference was accepted")


def _quick_reference_validation_fixture() -> tuple[dict, SimpleNamespace, dict]:
    metrics = {"fixture": "evaluation-result-v2"}
    artifact = SimpleNamespace(
        artifact_id="candidate-b-final",
        identity_fingerprint="sha256:artifact-b",
        value={
            "checkpoint_step": 12208,
            "model_fingerprint": "sha256:model",
            "split_fingerprint": "sha256:split",
            "source_lineage_fingerprint": "sha256:lineage",
        },
    )
    manifest = {
        "artifact_id": "candidate-b-final", "artifact_identity_fingerprint": "sha256:artifact-b",
        "profile": "quick", "checkpoint_identity": {"global_step": 12208},
        "model_fingerprint": "sha256:model", "tokenizer_fingerprint": "sha256:tokenizer",
        "dataset_identity": {"evaluation_fingerprint": "sha256:dataset"},
        "split_fingerprint": "sha256:split", "source_lineage_fingerprint": "sha256:lineage",
        "prompt_set_fingerprint": "sha256:prompt", "result_fingerprint_schema": "evaluation-result-v2",
        "result_fingerprint": checksum_value(metrics),
    }
    return {"manifest": manifest, "metrics": metrics, "resource": {}}, artifact, {
        "evaluation_fingerprint": "sha256:dataset",
    }


def test_quick_reference_validator_accepts_same_artifact_identity() -> None:
    result, artifact, dataset = _quick_reference_validation_fixture()
    report = _validate_quick_reference(
        result, artifact=artifact, dataset_identity=dataset,
        tokenizer_fingerprint="sha256:tokenizer", prompt_fingerprint="sha256:prompt",
    )
    assert report["teacher_forced_metrics"] == "comparable"
    assert report["generation_metrics"] == "comparable"


def test_quick_reference_validator_separates_prompt_incomparability() -> None:
    result, artifact, dataset = _quick_reference_validation_fixture()
    report = _validate_quick_reference(
        result, artifact=artifact, dataset_identity=dataset,
        tokenizer_fingerprint="sha256:tokenizer", prompt_fingerprint="sha256:different",
    )
    assert report["overall_status"] == "completed_with_incomparable_generation_reference"
    assert report["generation_prompt_error_code"] == "GENERATION_PROMPT_INCOMPARABLE"


def test_quick_reference_validator_uses_specific_fail_closed_codes() -> None:
    cases = (
        ("profile", "full", "QUICK_REFERENCE_PROFILE_INVALID"),
        ("artifact_id", "candidate-a-final", "QUICK_REFERENCE_ARTIFACT_MISMATCH"),
        ("artifact_identity_fingerprint", "sha256:other", "QUICK_REFERENCE_ARTIFACT_MISMATCH"),
        ("checkpoint_identity", {"global_step": 4883}, "QUICK_REFERENCE_CHECKPOINT_MISMATCH"),
        ("model_fingerprint", "sha256:other", "QUICK_REFERENCE_MODEL_MISMATCH"),
        ("tokenizer_fingerprint", "sha256:other", "QUICK_REFERENCE_TOKENIZER_MISMATCH"),
        ("dataset_identity", {"evaluation_fingerprint": "sha256:other"}, "QUICK_REFERENCE_DATASET_MISMATCH"),
        ("result_fingerprint", "sha256:other", "QUICK_REFERENCE_RESULT_FINGERPRINT_INVALID"),
    )
    for field, value, expected_code in cases:
        result, artifact, dataset = _quick_reference_validation_fixture()
        result["manifest"][field] = value
        try:
            _validate_quick_reference(
                result, artifact=artifact, dataset_identity=dataset,
                tokenizer_fingerprint="sha256:tokenizer", prompt_fingerprint="sha256:prompt",
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == expected_code
        else:
            raise AssertionError(f"{field} mismatch was accepted")


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
