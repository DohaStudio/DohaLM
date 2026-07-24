from __future__ import annotations

from pathlib import Path

import pytest
import torch

import src.training.tiny_validation as validation
from src.model import DohaLMTiny, ModelConfig, ParameterCounter
from src.training import (
    BatchCandidate,
    CosineWarmupDecayScheduler,
    TrainingConfig,
    TrainingError,
    build_synthetic_stream,
    probe_batch_candidates,
    run_tiny_validation,
)


def small_model_config(*, context_length: int = 256, dropout: float = 0.0) -> ModelConfig:
    return ModelConfig(vocab_size=64, context_length=context_length, num_layers=1, hidden_size=16, num_heads=2, head_dim=8, ffn_size=32, dropout=dropout)


def test_actual_tiny_parameter_count() -> None:
    assert ParameterCounter.count(DohaLMTiny(ModelConfig())).total == 16_889_856


@pytest.mark.parametrize("mode", ["repeated_pattern", "deterministic_random"])
def test_synthetic_stream_contract(mode: str) -> None:
    dataset = build_synthetic_stream(mode=mode, sequence_length=16, num_records=3, seed=7)
    record = dataset[0]
    assert record["input_ids"].shape == (16,)
    assert torch.equal(record["input_ids"], record["labels"])
    assert record["input_ids"][0].item() == 2
    assert record["input_ids"][-1].item() == 3


def test_synthetic_stream_is_deterministic() -> None:
    left = build_synthetic_stream(mode="deterministic_random", sequence_length=8, num_records=2, seed=9)
    right = build_synthetic_stream(mode="deterministic_random", sequence_length=8, num_records=2, seed=9)
    assert left.fingerprint == right.fingerprint
    assert torch.equal(left[0]["input_ids"], right[0]["input_ids"])


def test_cosine_scheduler_boundaries_and_minimum() -> None:
    parameter = torch.nn.Parameter(torch.ones(()))
    optimizer = torch.optim.AdamW([parameter], lr=1.0)
    scheduler = CosineWarmupDecayScheduler(optimizer, warmup_steps=2, max_steps=10, min_lr_ratio=0.1)
    assert scheduler.factor(0) == 0.0
    assert scheduler.factor(2) == 1.0
    assert 0.1 < scheduler.factor(6) < 1.0
    assert scheduler.factor(10) == 0.1
    assert scheduler.factor(20) == 0.1


def test_cosine_scheduler_resume_continuity() -> None:
    first_optimizer = torch.optim.AdamW([torch.nn.Parameter(torch.ones(()))], lr=1.0)
    first = CosineWarmupDecayScheduler(first_optimizer, warmup_steps=1, max_steps=4, min_lr_ratio=0.2)
    first.step(); first.step()
    second_optimizer = torch.optim.AdamW([torch.nn.Parameter(torch.ones(()))], lr=1.0)
    second = CosineWarmupDecayScheduler(second_optimizer, warmup_steps=1, max_steps=4, min_lr_ratio=0.2)
    second.load_state_dict(first.state_dict())
    assert second.current_step == first.current_step
    assert second.get_last_lr() == first.get_last_lr()


def test_training_config_keeps_linear_default_and_explicit_cosine() -> None:
    assert TrainingConfig().scheduler_type == "linear"
    assert TrainingConfig(scheduler_type="cosine", min_lr_ratio=0.1).scheduler_type == "cosine"


def test_probe_matrix_continues_after_mocked_oom(tmp_path: Path) -> None:
    calls = 0
    def runner(candidate, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise torch.OutOfMemoryError("mock oom")
        return {**candidate.to_dict(), "status": "passed"}
    report = probe_batch_candidates(
        [BatchCandidate(64, 1, 1), BatchCandidate(64, 2, 1)],
        device="cpu", use_amp=False, output_root=tmp_path / "probe", runner=runner,
    )
    assert [item["status"] for item in report["candidates"]] == ["oom", "passed"]
    assert report["oom_count"] == 1


def test_probe_report_is_structured_and_synthetic(tmp_path: Path) -> None:
    def runner(candidate, **kwargs):
        return {**candidate.to_dict(), "status": "passed", "tokens_per_second": 1.0}
    report = probe_batch_candidates([BatchCandidate(64, 1, 1)], device="cpu", use_amp=False, output_root=tmp_path / "probe", runner=runner)
    assert report["synthetic_only"] is True
    assert (tmp_path / "probe" / "batch-probe.json").is_file()


def test_generated_run_id_is_windows_safe() -> None:
    run_id = validation._run_id("tiny", {"seed": 17})
    assert ":" not in run_id


def test_tiny_validation_smoke_checkpoint_resume_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(validation, "tiny_model_config", small_model_config)
    report = run_tiny_validation(
        output_parent=tmp_path,
        mode="repeated_pattern",
        device="cpu",
        use_amp=False,
        steps=4,
        save_step=2,
        sequence_length=16,
        micro_batch_size=1,
        accumulation_steps=2,
        records=8,
        seed=17,
        learning_rate=0.01,
        warmup_steps=0,
        min_lr_ratio=0.1,
        run_id="test-run",
    )
    run_dir = tmp_path / "test-run"
    assert report["global_step"] == 4
    assert report["resume"]["next_batch_fingerprint_equal"] is True
    assert report["resume"]["weight_tying_preserved"] is True
    assert (run_dir / "checkpoint-2").is_dir()
    assert (run_dir / "training-metrics.jsonl").is_file()
    assert (run_dir / "validation-manifest.json").is_file()


def test_tiny_validation_rejects_invalid_save_step(tmp_path: Path) -> None:
    with pytest.raises(TrainingError):
        run_tiny_validation(output_parent=tmp_path, mode="repeated_pattern", device="cpu", use_amp=False, steps=2, save_step=2, sequence_length=8, micro_batch_size=1, accumulation_steps=1, records=2, seed=1, learning_rate=0.01, warmup_steps=0, min_lr_ratio=0.1)
