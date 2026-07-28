from __future__ import annotations

from pathlib import Path

import pytest
import torch
import yaml

from src.evaluation.config import EvaluationError
from src.evaluation.generation_diagnostics import (
    REQUIRED_CATEGORIES,
    REQUIRED_LENGTHS,
    REQUIRED_PROFILES,
    GenerationDiagnosticConfig,
    _aggregate,
    _apply_repetition_controls,
    _seed,
    _select_token,
    load_generation_prompts,
)


ROOT = Path(__file__).parents[1]


def test_generation_diagnostic_config_has_exact_approved_grid() -> None:
    config = GenerationDiagnosticConfig.from_yaml(ROOT / "configs/eos-generation-diagnostic.example.yaml")
    assert config.generation_lengths == REQUIRED_LENGTHS
    assert tuple(profile["name"] for profile in config.profiles) == REQUIRED_PROFILES
    assert tuple(item["artifact_id"] for item in config.artifacts) == ("candidate-a-final", "candidate-b-final")
    assert config.maximum_prompt_tokens + max(config.generation_lengths) == 256


def test_generation_prompts_are_synthetic_unique_and_complete() -> None:
    prompts, fingerprint = load_generation_prompts(ROOT / "configs/eos-generation-prompts.example.yaml")
    assert tuple(prompt["category"] for prompt in prompts) == REQUIRED_CATEGORIES
    assert len({prompt["prompt_id"] for prompt in prompts}) == len(REQUIRED_CATEGORIES)
    assert fingerprint.startswith("sha256:")


def test_prompt_category_mismatch_and_duplicate_fail_closed(tmp_path: Path) -> None:
    source = yaml.safe_load((ROOT / "configs/eos-generation-prompts.example.yaml").read_text(encoding="utf-8"))
    source["prompts"][1]["category"] = source["prompts"][0]["category"]
    path = tmp_path / "prompts.yaml"
    path.write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    with pytest.raises(EvaluationError) as error:
        load_generation_prompts(path)
    assert error.value.code == "PROMPT_CATEGORY_MISMATCH"

    source = yaml.safe_load((ROOT / "configs/eos-generation-prompts.example.yaml").read_text(encoding="utf-8"))
    source["prompts"][1]["prompt_id"] = source["prompts"][0]["prompt_id"]
    path.write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    with pytest.raises(EvaluationError) as error:
        load_generation_prompts(path)
    assert error.value.code == "PROMPT_SET_INVALID"


def test_absolute_output_path_and_privacy_opt_in_are_blocked(tmp_path: Path) -> None:
    source = yaml.safe_load((ROOT / "configs/eos-generation-diagnostic.example.yaml").read_text(encoding="utf-8"))
    source["output_root"] = "D:/private"
    path = tmp_path / "diagnostic.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    with pytest.raises(EvaluationError) as error:
        GenerationDiagnosticConfig.from_yaml(path)
    assert error.value.code == "ABSOLUTE_PATH_BLOCKED"
    source["output_root"] = "analysis/evaluation"
    source["raw_text_storage"] = True
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    with pytest.raises(EvaluationError) as error:
        GenerationDiagnosticConfig.from_yaml(path)
    assert error.value.code == "EVALUATION_PRIVACY_POLICY"


def test_sampling_seed_is_artifact_independent_and_selection_is_reproducible() -> None:
    seed = _seed(17, "temperature-1.0", "minimal-01")
    assert seed == _seed(17, "temperature-1.0", "minimal-01")
    logits = torch.tensor([0.1, 0.5, 1.0, 0.4])
    profile = {"strategy": "sample", "temperature": 1.0}
    first = _select_token(logits, profile, torch.Generator().manual_seed(seed))
    second = _select_token(logits, profile, torch.Generator().manual_seed(seed))
    assert first == second


def test_repetition_penalty_and_no_repeat_ngram_change_only_working_logits() -> None:
    logits = torch.tensor([1.0, 4.0, 3.0, -2.0])
    original = logits.clone()
    penalized = _apply_repetition_controls(
        logits, [1, 2, 1], {"repetition_penalty": 2.0, "no_repeat_ngram": 0},
    )
    assert torch.equal(logits, original)
    assert penalized[1].item() == 2.0
    blocked = _apply_repetition_controls(
        logits, [1, 2, 1], {"repetition_penalty": 1.0, "no_repeat_ngram": 2},
    )
    assert blocked[2].item() == float("-inf")


def test_aggregate_has_required_eos_repetition_and_privacy_metrics() -> None:
    sample = {
        "eos_reached": True, "eos_step": 3, "maximum_length_reached": False,
        "generated_token_length": 3, "empty_generation": False, "best_eos_rank": 1,
        "mean_eos_rank": 2.0, "mean_eos_probability": 0.25, "maximum_eos_probability": 0.5,
        "mean_logit_margin": 1.0, "mean_probability_margin": 0.1,
        "eos_top5_step_rate": 1.0, "eos_top10_step_rate": 1.0,
        "special_token_exposure": 0.0, "unk_generation": 0.0, "byte_fallback_ratio": 0.0,
        "adjacent_repetition": 0.0, "repeated_bigram": 0.0, "repeated_trigram": 0.0,
        "distinct_1": 1.0, "distinct_2": 1.0, "distinct_3": 1.0,
        "degenerate_loop": False, "unique_token_ratio": 1.0, "loop_before_eos": False,
    }
    report = _aggregate([sample])
    assert report["eos_rate"] == 1.0
    assert report["eos_step"]["median"] == 3.0
    assert report["token_ids_stored"] is False
    assert "text" not in report
    assert "tokens" not in report
