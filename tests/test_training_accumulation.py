from __future__ import annotations

import torch
from _training_helpers import build_tiny_trainer, training_config


def test_accumulation_one_updates_once_per_micro_batch(tmp_path):
    trainer, _ = build_tiny_trainer(tmp_path / "one", config=training_config(max_steps=2, save_every=2))
    result = trainer.train()
    assert result.state.global_step == 2
    assert result.state.micro_step == 2
    assert result.state.optimizer_step == 2
    assert trainer.scheduler.current_step == 2


def test_accumulation_two_delays_optimizer_boundary(tmp_path):
    config = training_config(
        batch_size=2,
        micro_batch_size=1,
        gradient_accumulation_steps=2,
        max_steps=2,
        save_every=2,
    )
    trainer, _ = build_tiny_trainer(tmp_path / "two", config=config)
    calls = 0
    original = trainer.optimizer.step

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    trainer.optimizer.step = counted
    result = trainer.train()
    assert calls == 2
    assert result.state.micro_step == 4
    assert result.state.records_seen == 4


def test_large_batch_and_accumulation_have_close_single_update(tmp_path):
    large_config = training_config(max_steps=1, save_every=1)
    accumulation_config = training_config(
        batch_size=2,
        micro_batch_size=1,
        gradient_accumulation_steps=2,
        max_steps=1,
        save_every=1,
    )
    large, _ = build_tiny_trainer(tmp_path / "large", config=large_config)
    accumulated, _ = build_tiny_trainer(tmp_path / "accumulated", config=accumulation_config)
    large.train(); accumulated.train()
    for left, right in zip(large.model.parameters(), accumulated.model.parameters(), strict=True):
        # Separate micro-batch reductions may change float32 summation order.
        assert torch.allclose(left, right, atol=3e-4, rtol=1e-4)
