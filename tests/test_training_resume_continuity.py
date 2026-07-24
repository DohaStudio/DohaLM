from __future__ import annotations

from pathlib import Path

import src.training.tiny_validation as validation
from src.model import ModelConfig
from src.training import run_tiny_validation


def small_model_config(*, context_length: int = 256, dropout: float = 0.0) -> ModelConfig:
    return ModelConfig(vocab_size=64, context_length=context_length, num_layers=1, hidden_size=16, num_heads=2, head_dim=8, ffn_size=32, dropout=dropout)


def run(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(validation, "tiny_model_config", small_model_config)
    return run_tiny_validation(output_parent=tmp_path, mode="repeated_pattern", device="cpu", use_amp=False, steps=4, save_step=2, sequence_length=16, micro_batch_size=1, accumulation_steps=2, records=8, seed=23, learning_rate=0.01, warmup_steps=0, min_lr_ratio=0.1, run_id="continuity")


def test_resume_global_step_and_scheduler(tmp_path: Path, monkeypatch) -> None:
    report = run(tmp_path, monkeypatch)
    assert report["resume"]["final_global_step"] == 4
    assert report["resume"]["scheduler_step"] == 4


def test_resume_sampler_state_and_next_batch(tmp_path: Path, monkeypatch) -> None:
    report = run(tmp_path, monkeypatch)
    assert report["resume"]["sampler_state_equal_at_load"] is True
    assert report["resume"]["next_batch_fingerprint_equal"] is True


def test_resume_scaler_contract(tmp_path: Path, monkeypatch) -> None:
    assert run(tmp_path, monkeypatch)["resume"]["scaler_state_present"] is True


def test_resume_model_checksum_matches_uninterrupted(tmp_path: Path, monkeypatch) -> None:
    report = run(tmp_path, monkeypatch)
    assert report["resume"]["bitwise_model_equal"] is True


def test_resume_logits_match_uninterrupted(tmp_path: Path, monkeypatch) -> None:
    report = run(tmp_path, monkeypatch)
    assert report["resume"]["logits_allclose"] is True
    assert report["resume"]["logits_max_absolute_difference"] == 0.0


def test_resume_manifest_never_contains_absolute_output_path(tmp_path: Path, monkeypatch) -> None:
    run(tmp_path, monkeypatch)
    text = (tmp_path / "continuity" / "validation-manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
