from __future__ import annotations

import json

import pytest
import torch
from _training_helpers import build_tiny_trainer

from src.model.outputs import DohaLMOutput
from src.training import TrainingError


def test_cpu_training_updates_state_logs_and_clips(tmp_path):
    trainer, _ = build_tiny_trainer(tmp_path / "run")
    before = trainer.model.token_embedding.weight.detach().clone()
    result = trainer.train()
    assert not torch.equal(before, trainer.model.token_embedding.weight)
    assert result.state.global_step == 2
    assert all(metric.gradient_norm <= 1.00001 for metric in result.metrics)
    assert any(metric.gradient_norm_before_clip > metric.gradient_norm for metric in result.metrics)
    rows = [json.loads(line) for line in (tmp_path / "run" / "metrics.jsonl").read_text().splitlines()]
    assert [row["global_step"] for row in rows] == [1, 2]
    assert all("input_ids" not in row and "labels" not in row for row in rows)


def test_training_keeps_model_in_train_mode(tmp_path):
    trainer, _ = build_tiny_trainer(tmp_path / "run")
    trainer.model.eval()
    trainer.train()
    assert trainer.model.training is True


def test_target_steps_is_absolute_and_bounded(tmp_path):
    trainer, _ = build_tiny_trainer(tmp_path / "run")
    trainer.train(target_steps=1)
    with pytest.raises(TrainingError, match="INVALID_TRAINING_CONFIG"):
        trainer.train(target_steps=1)
    with pytest.raises(TrainingError, match="INVALID_TRAINING_CONFIG"):
        trainer.train(target_steps=3)


def test_non_finite_loss_is_blocked_without_step_advance(tmp_path, monkeypatch):
    trainer, _ = build_tiny_trainer(tmp_path / "run")
    original = trainer.model.forward

    def bad_forward(*args, **kwargs):
        output = original(*args, **kwargs)
        return DohaLMOutput(output.logits, output.loss * torch.tensor(float("nan")), output.hidden_states)

    monkeypatch.setattr(trainer.model, "forward", bad_forward)
    with pytest.raises(TrainingError, match="NON_FINITE_LOSS"):
        trainer.train(target_steps=1)
    assert trainer.state.global_step == 0 and trainer.state.micro_step == 0


def test_non_finite_gradient_is_blocked_without_step_advance(tmp_path, monkeypatch):
    trainer, _ = build_tiny_trainer(tmp_path / "run")

    def fail_clip(*args, **kwargs):
        raise RuntimeError("non-finite")

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", fail_clip)
    with pytest.raises(TrainingError, match="NON_FINITE_GRADIENT"):
        trainer.train(target_steps=1)
    assert trainer.state.global_step == 0 and trainer.state.micro_step == 0
    assert all(parameter.grad is None for parameter in trainer.model.parameters())


def test_output_root_overwrite_is_rejected(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(TrainingError, match="CHECKPOINT_ALREADY_EXISTS"):
        build_tiny_trainer(existing)


def test_deterministic_seed_reproduces_losses_and_weights(tmp_path):
    one, _ = build_tiny_trainer(tmp_path / "one")
    two, _ = build_tiny_trainer(tmp_path / "two")
    first, second = one.train(), two.train()
    assert [item.loss for item in first.metrics] == [item.loss for item in second.metrics]
    assert all(torch.equal(left, right) for left, right in zip(one.model.parameters(), two.model.parameters(), strict=True))
