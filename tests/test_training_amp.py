from __future__ import annotations

import json

import pytest
import torch

from tests._training_helpers import build_tiny_trainer, training_config


def test_cpu_scaler_is_disabled_but_checkpointed(tmp_path):
    trainer, _ = build_tiny_trainer(tmp_path / "cpu", config=training_config(max_steps=1, save_every=1))
    trainer.train()
    assert trainer.scaler.is_enabled() is False
    assert (tmp_path / "cpu" / "checkpoint-1" / "scaler.pt").is_file()


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_fp16_amp_updates_with_finite_metrics(tmp_path):
    config = training_config(
        max_steps=1,
        save_every=1,
        device="cuda",
        use_amp=True,
        pin_memory=True,
    )
    trainer, _ = build_tiny_trainer(tmp_path / "cuda", config=config)
    result = trainer.train()
    assert trainer.scaler.is_enabled() is True
    metric = result.metrics[0]
    assert torch.isfinite(torch.tensor(metric.loss))
    assert metric.peak_memory_allocated > 0 and metric.peak_memory_reserved > 0
    state = torch.load(tmp_path / "cuda" / "checkpoint-1" / "scaler.pt", weights_only=True)
    assert "scale" in state


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_cuda_amp_checkpoint_resume_restores_scaler(tmp_path):
    config = training_config(max_steps=2, save_every=1, device="cuda", use_amp=True, pin_memory=True)
    trainer, _ = build_tiny_trainer(tmp_path / "cuda", config=config)
    trainer.train(target_steps=1)
    scale = trainer.scaler.get_scale()
    resumed, _ = build_tiny_trainer(tmp_path / "cuda", config=config, resume=True)
    resumed.resume_from(tmp_path / "cuda" / "checkpoint-1")
    assert resumed.scaler.get_scale() == scale
    result = resumed.train(target_steps=2)
    assert result.state.global_step == 2
