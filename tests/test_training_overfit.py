from __future__ import annotations

from _training_helpers import build_tiny_trainer, training_config


def test_repeated_single_batch_loss_decreases(tmp_path):
    config = training_config(max_steps=20, save_every=20, learning_rate=0.02)
    trainer, _ = build_tiny_trainer(tmp_path / "overfit", config=config)
    result = trainer.train()
    assert result.initial_loss > result.final_loss
    assert result.final_loss < result.initial_loss * 0.5


def test_overfit_is_deterministic_for_same_seed(tmp_path):
    config = training_config(max_steps=5, save_every=5)
    one, _ = build_tiny_trainer(tmp_path / "one", config=config)
    two, _ = build_tiny_trainer(tmp_path / "two", config=config)
    first, second = one.train(), two.train()
    assert first.initial_loss == second.initial_loss
    assert first.final_loss == second.final_loss
