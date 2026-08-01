from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
import yaml

from src.evaluation.decoding_evaluation import (
    DecodingPreset,
    automatic_incomplete,
    deployment_verdict,
    evaluate_decoding,
    rank_candidates,
    repetition_signals,
    score_result,
    select_diverse_candidates,
    termination_reason,
    validate_decoding_config,
    validate_eos_contract,
)
from src.evaluation.qlora_sft import PromptRecord, QLoRAEvaluationError, verify_checksum_manifest, write_evaluation_artifact
from scripts.evaluation.evaluate_dohalm_v01_decoding import _validate_paths


CONFIG = Path("configs/evaluation/dohalm-v0.1-decoding-evaluation.yaml")


class FakeTokenizer:
    eos_token_id = 151645
    pad_token_id = 151643
    eos_token = "<eos>"
    all_special_tokens = ["<eos>", "<pad>"]

    def apply_chat_template(self, *_args, **_kwargs):
        return torch.tensor([[10, 11]])

    def decode(self, tokens, *, skip_special_tokens):
        visible = [token for token in tokens if token not in {151645, 151643}]
        text = "정상 답변입니다." if visible else ""
        return text if skip_special_tokens else text + ("<eos>" if 151645 in tokens else "")


class FakeModel(torch.nn.Module):
    def __init__(self, generated: list[int]):
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.zeros(()), requires_grad=False)
        self.generated = generated
        self.config = SimpleNamespace(eos_token_id=151645, use_cache=True)
        self.generation_config = SimpleNamespace(eos_token_id=151645, pad_token_id=151643)

    def generate(self, ids, **kwargs):
        assert kwargs["do_sample"] is False
        assert kwargs["num_beams"] == 1
        assert kwargs["use_cache"] is True
        return torch.cat([ids, torch.tensor([self.generated], device=ids.device)], dim=1)


def _candidate(model: str, score: float, *, allowed: bool = True) -> dict:
    return {
        "model": model,
        "preset_id": f"preset-{model}-{score}",
        "preset": {"max_new_tokens": 96, "repetition_penalty": 1.1, "no_repeat_ngram_size": 3},
        "score": {"quality_score": score, "advance_allowed": allowed},
    }


def test_config_is_evaluation_only_and_has_no_absolute_paths() -> None:
    value = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config = validate_decoding_config(value)
    assert config["execution"] == {
        "training_allowed": False,
        "optimizer_allowed": False,
        "adapter_write_allowed": False,
        "overwrite_allowed": False,
    }
    source = CONFIG.read_text(encoding="utf-8")
    assert "/home/" not in source and "D:/" not in source


def test_output_root_may_contain_baseline_as_a_sibling(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    training = tmp_path / "training"
    processed = tmp_path / "processed"
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    output = tmp_path / "evaluation"
    baseline = output / "baseline"
    for path in (repository, training, processed, raw, cache, baseline):
        path.mkdir(parents=True, exist_ok=True)
    arguments = SimpleNamespace(
        repository=repository, training_run_root=training, processed_root=processed,
        raw_dataset_root=raw, model_cache_root=cache,
        baseline_evaluation_root=baseline, output_root=output, evaluation_id="new-evaluation",
    )
    _validate_paths(arguments)
    (output / "new-evaluation").mkdir()
    with pytest.raises(QLoRAEvaluationError, match="EVALUATION_OUTPUT_CONFLICT"):
        _validate_paths(arguments)


def test_eos_contract_and_termination_reasons() -> None:
    tokenizer = FakeTokenizer()
    model = FakeModel([20, 151645]).eval()
    assert validate_eos_contract(tokenizer, model)["override_consistent"] is True
    assert termination_reason([1, 151645], eos_token_id=151645, max_new_tokens=4) == "eos_token"
    assert termination_reason([1, 2, 3, 4], eos_token_id=151645, max_new_tokens=4) == "max_new_tokens"
    assert termination_reason([1], eos_token_id=151645, max_new_tokens=4) == "other_stopping_criteria"
    assert termination_reason([], eos_token_id=151645, max_new_tokens=4) == "empty_output"
    model.generation_config.eos_token_id = 1
    with pytest.raises(QLoRAEvaluationError, match="EOS_ID_MISMATCH"):
        validate_eos_contract(tokenizer, model)


def test_repetition_signals_separate_legacy_and_detailed_types() -> None:
    signals = repetition_signals("반복 반복 반복. 같은 문장. 같은 문장.", [1, 2, 3, 4] * 4)
    assert signals["word_repetition"] is True
    assert signals["sentence_repetition"] is True
    assert signals["ngram_repetition"] is True
    assert signals["legacy_repetition"] is True
    assert signals["long_loop"] is True
    assert signals["repetition_any"] is True


def test_incomplete_separates_automatic_and_semantic_judgment() -> None:
    truncated = automatic_incomplete("완료되지 않은 답변", "max_new_tokens")
    assert truncated["automatic_incomplete"] is True
    assert truncated["max_length_truncation"] is True
    assert truncated["semantic_incomplete"] == "not_assessed_without_approved_judge"
    complete = automatic_incomplete("완료된 답변입니다.", "eos_token")
    assert complete["automatic_incomplete"] is False


def test_decoding_evaluation_is_deterministic_and_stores_no_text_or_tokens() -> None:
    prompt = PromptRecord("hash", "synthetic", "test", "질문", "정상 답변입니다.", "short")
    model = FakeModel([20, 151645]).eval()
    preset = DecodingPreset(64, 1.1, 3)
    first = evaluate_decoding(model, FakeTokenizer(), [prompt], preset, train_output_hashes=set())
    second = evaluate_decoding(model, FakeTokenizer(), [prompt], preset, train_output_hashes=set())
    assert first["metric_fingerprint"] == second["metric_fingerprint"]
    assert first["termination_reason_fingerprint"] == second["termination_reason_fingerprint"]
    assert first["generated_token_fingerprint"] == second["generated_token_fingerprint"]
    assert first["summary"]["eos_terminated"] == 1
    assert "text" not in first["rows"][0] and "tokens" not in first["rows"][0]


def test_grid_pruning_and_checkpoint_diversity() -> None:
    values = [
        _candidate("checkpoint-1750", 0.9),
        _candidate("checkpoint-1750", 0.8),
        _candidate("final-adapter", 0.7),
        _candidate("final-adapter", 1.0, allowed=False),
    ]
    assert [row["score"]["quality_score"] for row in rank_candidates(values, 2)] == [0.9, 0.8]
    selected = select_diverse_candidates(values, 3)
    assert {row["model"] for row in selected} == {"checkpoint-1750", "final-adapter"}
    assert len(selected) == 3


def test_score_hard_blocker_and_deployment_contract() -> None:
    summary = {
        "samples": 100, "character_f1": 0.50, "rouge_l": 0.31,
        "eos_terminated": 85, "max_length_terminated": 5,
        "repetition_any": 10, "automatic_incomplete": 10,
        "special_token_exposure": 0, "empty_output": 0,
    }
    score = score_result(summary)
    assert score["hard_blocked"] is False
    assert deployment_verdict(summary, deterministic=True)["verdict"] == "PASS"
    summary["repetition_any"] = 51
    assert score_result(summary)["hard_blockers"]["repetition_over_50_percent"] is True


def test_inference_preset_serialization_and_artifact_reload(tmp_path: Path) -> None:
    preset = {
        "model_candidate": "checkpoint-1750",
        "generation": {"max_new_tokens": 96, "repetition_penalty": 1.1, "no_repeat_ngram_size": 3},
    }
    final = write_evaluation_artifact(
        output_root=tmp_path, evaluation_id="decode-1",
        files={"inference-preset.yaml": preset, "final-comparison.json": {"status": "synthetic"}},
    )
    assert verify_checksum_manifest(final)
    assert yaml.safe_load((final / "inference-preset.yaml").read_text(encoding="utf-8")) == preset


def test_cli_source_has_no_training_weight_write_or_merge_calls() -> None:
    source = Path("scripts/evaluation/evaluate_dohalm_v01_decoding.py").read_text(encoding="utf-8")
    for forbidden in (".train(", "optimizer.step", "backward(", "save_pretrained", "merge_and_unload"):
        assert forbidden not in source
