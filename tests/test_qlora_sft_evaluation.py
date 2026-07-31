from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from scripts.evaluation.run_qlora_sft_evaluation import _diagnosis, _verdict
from src.data.checksums import canonical_json_bytes
from src.evaluation.qlora_sft import (
    QLoRAEvaluationError,
    _canonical_hash,
    _character_f1,
    _rouge_l,
    batch_identity,
    deterministic_metric_fingerprint,
    evaluate_loss,
    load_evaluation_config,
    load_prompt_records,
    model_mode_report,
    verify_checksum_manifest,
    write_evaluation_artifact,
)
from src.training.qlora_training import DynamicSFTCollator

CONFIG = Path("configs/evaluation/dohalm-v0.1-qlora-evaluation.yaml")


class TinyLossModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.zeros(()), requires_grad=False)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, labels: torch.Tensor):
        del attention_mask
        vocab = 8
        logits = torch.zeros((*input_ids.shape, vocab), dtype=torch.float32)
        logits.scatter_(2, input_ids.unsqueeze(-1), 3.0)
        shifted = labels[:, 1:]
        loss = torch.nn.functional.cross_entropy(
            logits[:, :-1].reshape(-1, vocab), shifted.reshape(-1), ignore_index=-100,
        )
        return SimpleNamespace(logits=logits, loss=loss)


def _record(values: list[int], prompt: int) -> dict[str, list[int]]:
    labels = [-100] * prompt + values[prompt:]
    return {"input_ids": values, "attention_mask": [1] * len(values), "labels": labels}


def test_config_is_evaluation_only_and_has_no_absolute_paths() -> None:
    config = load_evaluation_config(CONFIG)
    assert config["execution"] == {
        "training_allowed": False,
        "optimizer_allowed": False,
        "adapter_write_allowed": False,
        "overwrite_allowed": False,
    }
    source = CONFIG.read_text(encoding="utf-8")
    assert "D:/" not in source and "/home/" not in source


def test_dynamic_collator_and_token_weighted_loss_are_deterministic() -> None:
    dataset = [
        _record([1, 1, 1, 1], 2),
        _record([1, 3, 2, 4, 5, 6], 1),
    ]
    collator = DynamicSFTCollator(pad_token_id=0, pad_to_multiple_of=8)
    first = evaluate_loss(
        TinyLossModel().eval(), dataset, collator,
        categories=["a", "b"], comparison_batches=2,
    )
    second = evaluate_loss(
        TinyLossModel().eval(), dataset, collator,
        categories=["a", "b"], comparison_batches=2,
    )
    assert first["valid_label_tokens"] == 7
    assert first["batches"] == 2
    assert first["token_weighted_loss"] != first["batch_mean_loss"]
    assert deterministic_metric_fingerprint(first, {"status": "synthetic"}) == deterministic_metric_fingerprint(second, {"status": "synthetic"})
    assert first["comparison_batches"] == second["comparison_batches"]
    assert first["comparison_batches"][0]["sequence_length"] == 8


def test_batch_identity_never_contains_token_values() -> None:
    collator = DynamicSFTCollator(pad_token_id=0)
    identity = batch_identity(collator([_record([1, 2, 3], 1)]))
    assert set(identity) == {
        "input_ids_checksum", "attention_mask_checksum", "labels_checksum",
        "sequence_length", "attention_tokens", "valid_label_tokens",
    }


def test_prompt_selection_is_hash_only_category_balanced(monkeypatch, tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    validation = []
    category_map = {}
    for category_index in range(10):
        for row in range(5):
            record = {
                "instruction": f"synthetic question {category_index}-{row}",
                "input": None,
                "output": f"synthetic answer {category_index}-{row}",
                "system": None,
            }
            validation.append(record)
            category_map[_canonical_hash(record)] = f"category-{category_index}"
    train = [{"instruction": "train", "input": None, "output": "train answer", "system": None}]
    for name, rows in (("validation.jsonl", validation), ("train.jsonl", train)):
        (processed / name).write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    prompts = {
        "schema_version": 1,
        "prompts": [
            {"id": f"s-{index}", "category": "synthetic", "prompt": f"prompt {index}", "reference": f"answer {index}"}
            for index in range(30)
        ],
    }
    prompt_path = tmp_path / "prompts.yaml"
    import yaml
    prompt_path.write_text(yaml.safe_dump(prompts), encoding="utf-8")
    monkeypatch.setattr("src.evaluation.qlora_sft._raw_validation_categories", lambda path: category_map)
    selected, identity, output_hashes, categories = load_prompt_records(
        processed_root=processed, raw_root=tmp_path, prompt_path=prompt_path,
        expected_validation_rows=50,
    )
    assert len(selected) == 80
    assert len(categories) == 50
    assert identity["selected_held_out"] == 50
    assert identity["training_exact_overlap"] is False
    assert len(output_hashes) == 1


def test_model_mode_report_fails_closed_on_dropout() -> None:
    Qwen2DecoderLayer = type("Qwen2DecoderLayer", (torch.nn.Module,), {"forward": lambda self, x: x})
    model = torch.nn.Sequential(Qwen2DecoderLayer(), torch.nn.Dropout(.1))
    model.config = SimpleNamespace(use_cache=True)
    model.eval()
    report = model_mode_report(model)
    assert report["decoder_layers"] == 1
    assert report["dropout_modules_training"] == 0
    model[1].train()
    with pytest.raises(QLoRAEvaluationError, match="MODEL_MODE_MISMATCH"):
        model_mode_report(model)


def test_model_mode_report_accepts_base_active_adapters_method() -> None:
    model = torch.nn.Linear(2, 2)
    model.config = SimpleNamespace(use_cache=True)
    model.active_adapters = list  # type: ignore[attr-defined]
    model.eval()
    report = model_mode_report(model)
    assert report["active_adapters"] == []


def test_model_mode_report_accepts_base_no_adapter_error() -> None:
    model = torch.nn.Linear(2, 2)
    model.config = SimpleNamespace(use_cache=True)
    def no_adapter() -> list[str]:
        raise ValueError("No adapter loaded")
    model.active_adapters = no_adapter  # type: ignore[attr-defined]
    model.eval()
    assert model_mode_report(model)["active_adapters"] == []


def test_generation_text_metrics() -> None:
    assert _character_f1("서울입니다", "서울입니다") == 1.0
    assert _character_f1("", "서울") == 0.0
    assert _rouge_l("대한민국 서울", "서울") > 0
    assert _rouge_l("", "서울") == 0.0


def test_atomic_artifact_checksum_and_no_replace(tmp_path: Path) -> None:
    final = write_evaluation_artifact(
        output_root=tmp_path, evaluation_id="evaluation-1",
        files={"evaluation-result.yaml": {"status": "completed"}, "metrics.json": {"loss": 1.0}},
    )
    assert verify_checksum_manifest(final)
    with pytest.raises(QLoRAEvaluationError, match="EVALUATION_OUTPUT_CONFLICT"):
        write_evaluation_artifact(
            output_root=tmp_path, evaluation_id="evaluation-1",
            files={"evaluation-result.yaml": {"status": "completed"}},
        )


def test_checksum_tamper_is_rejected(tmp_path: Path) -> None:
    final = write_evaluation_artifact(
        output_root=tmp_path, evaluation_id="evaluation-2",
        files={"evaluation-result.yaml": {"status": "completed"}},
    )
    (final / "evaluation-result.yaml").write_text("status: tampered\n", encoding="utf-8")
    with pytest.raises(QLoRAEvaluationError, match="CHECKSUM_MISMATCH"):
        verify_checksum_manifest(final)


def test_path_diagnosis_reproduces_single_record_and_full_mean() -> None:
    comparison = [{
        "input_ids_checksum": "a", "attention_mask_checksum": "b", "labels_checksum": "c",
        "sequence_length": 8, "attention_tokens": 7, "valid_label_tokens": 3,
    }]
    models = {}
    for name in ("base", "checkpoint-1750", "checkpoint-1947", "final-adapter"):
        models[name] = {"loss": {
            "first_record_loss": 2.805816, "batch_mean_loss": 1.183955,
            "reload_style_first_record_loss": 2.805816,
            "token_weighted_loss": 1.2,
            "comparison_batches": [{**comparison[0], "batch_index": 0, "loss": 1.0, "logit_shape": [1, 8, 16], "finite": True}] * 10,
        }}
    diagnosis = _diagnosis(models, {
        "trainer_final_eval_loss": 1.183955, "reload_validation_loss": 2.805816,
    })
    assert diagnosis["confirmed_cause"] == "EVAL_DATASET_MISMATCH"
    assert diagnosis["same_batch_checksums"] is True


def test_verdict_contract() -> None:
    loss = {"models": {"base": {"token_weighted_loss": 2.0}, "final-adapter": {"token_weighted_loss": 1.0}}}
    generation = {
        "base": {"overall": {"character_f1": .4, "rouge_l": .4}},
        "final-adapter": {"overall": {"character_f1": .5, "rouge_l": .5}},
    }
    result = _verdict(loss, generation, {"serious_regression_rate": .01}, True)
    assert result["verdict"] == "PASS"
    assert result["deployment_ready"] is True


def test_cli_source_has_no_training_or_optimizer_calls() -> None:
    source = Path("scripts/evaluation/run_qlora_sft_evaluation.py").read_text(encoding="utf-8")
    assert ".train(" not in source
    assert "optimizer.step" not in source
    assert "save_pretrained" not in source
