from __future__ import annotations

import pytest
import torch

from src.data.checksums import checksum_value
from src.model import DohaLMOutput, DohaLMTiny, ModelConfig
from src.training import (
    CausalLMCollator,
    SyntheticTokenDataset,
    Trainer,
    TrainingConfig,
    create_dataloader,
    seed_everything,
)
from src.training.errors import TrainingError


def _model_config() -> ModelConfig:
    return ModelConfig(
        vocab_size=32,
        context_length=8,
        num_layers=1,
        hidden_size=16,
        num_heads=4,
        head_dim=4,
        ffn_size=32,
        dropout=0.0,
    )


def _dataset() -> SyntheticTokenDataset:
    return SyntheticTokenDataset(
        vocab_size=32,
        sequence_length=5,
        num_records=8,
        seed=23,
        pattern=[2, 10, 11, 12, 3],
    )


def _training_config(**changes) -> TrainingConfig:
    values = {
        "batch_size": 2,
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 1,
        "max_steps": 1,
        "learning_rate": 0.02,
        "weight_decay": 0.01,
        "warmup_steps": 0,
        "max_grad_norm": 1.0,
        "seed": 23,
        "log_every": 1,
        "save_every": 2,
        "output_dir": "tests/output/unit-training",
        "device": "cpu",
        "num_workers": 0,
    }
    values.update(changes)
    return TrainingConfig(**values)


def _amp_trainer(output_root, *, max_steps: int = 1) -> Trainer:
    config = _training_config(
        max_steps=max_steps,
        save_every=max_steps + 1,
        device="cuda",
        use_amp=True,
        pin_memory=True,
    )
    seed_everything(config.seed)
    dataset = _dataset()
    loader = create_dataloader(
        dataset,
        CausalLMCollator(context_length=8),
        config,
        shuffle=True,
        stateful=True,
        dataset_fingerprint=dataset.fingerprint,
    )
    return Trainer(
        model=DohaLMTiny(_model_config()),
        dataloader=loader,
        config=config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=checksum_value({"kind": "synthetic", "vocab": 32}),
        output_root=output_root,
        dataset_metadata={"kind": "test-synthetic"},
    )


def _inject_gradient_overflow(trainer: Trainer, *, repeated: bool):
    calls = 0

    def hook(gradient: torch.Tensor) -> torch.Tensor:
        nonlocal calls
        calls += 1
        if repeated or calls == 1:
            return torch.full_like(gradient, float("inf"))
        return gradient

    return next(trainer.model.parameters()).register_hook(hook)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_single_amp_overflow_retries_same_batch_without_step_or_sampler_drift(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "overflow")
    events = []
    handle = _inject_gradient_overflow(trainer, repeated=False)
    try:
        result = trainer.train(amp_overflow_observer=events.append)
    finally:
        handle.remove()

    assert len(events) == 1
    assert events[0].global_step == 0
    assert events[0].next_optimizer_step == 1
    assert events[0].scale_after == events[0].scale_before / 2
    assert events[0].model_parameters_finite is True
    assert events[0].optimizer_state_finite is True
    assert result.state.global_step == result.state.optimizer_step == 1
    assert result.state.records_seen == 2
    assert result.state.micro_step == 1
    assert result.state.sampler_state is not None
    assert result.state.sampler_state["records_yielded"] == 2
    assert result.state.sampler_state["sample_offset"] == 2
    assert result.metrics[0].amp_step_skipped is False
    assert result.metrics[0].amp_overflow_count == 1


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_repeated_amp_overflow_fails_closed_without_optimizer_accounting(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "repeated")
    events = []
    handle = _inject_gradient_overflow(trainer, repeated=True)
    try:
        with pytest.raises(TrainingError, match="AMP_SKIP_LIMIT"):
            trainer.train(
                amp_overflow_observer=events.append,
                amp_overflow_limit=3,
            )
    finally:
        handle.remove()

    assert len(events) == 3
    assert [event.attempt for event in events] == [1, 2, 3]
    assert all(event.global_step == 0 for event in events)
    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0
    assert not trainer.optimizer.state


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_amp_overflow_with_corrupted_optimizer_state_is_fatal(tmp_path) -> None:
    trainer = _amp_trainer(tmp_path / "corrupted", max_steps=2)
    trainer.train(target_steps=1)
    optimizer_tensor = next(
        value
        for state in trainer.optimizer.state.values()
        for value in state.values()
        if isinstance(value, torch.Tensor) and value.is_floating_point()
    )
    optimizer_tensor.fill_(float("inf"))
    handle = _inject_gradient_overflow(trainer, repeated=True)
    try:
        with pytest.raises(TrainingError, match="NON_FINITE_GRADIENT"):
            trainer.train(target_steps=2)
    finally:
        handle.remove()

    assert trainer.state.global_step == trainer.state.optimizer_step == 1


def test_non_amp_non_finite_gradient_remains_fatal(tmp_path) -> None:
    config = _training_config(max_steps=1, save_every=2)
    seed_everything(config.seed)
    dataset = _dataset()
    loader = create_dataloader(
        dataset,
        CausalLMCollator(context_length=8),
        config,
        shuffle=True,
    )
    trainer = Trainer(
        model=DohaLMTiny(_model_config()),
        dataloader=loader,
        config=config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=checksum_value({"kind": "synthetic", "vocab": 32}),
        output_root=tmp_path / "non-amp",
    )
    handle = _inject_gradient_overflow(trainer, repeated=True)
    try:
        with pytest.raises(TrainingError, match="NON_FINITE_GRADIENT"):
            trainer.train()
    finally:
        handle.remove()

    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0


def test_non_finite_loss_remains_fatal(tmp_path) -> None:
    config = _training_config(max_steps=1, save_every=2)
    seed_everything(config.seed)
    dataset = _dataset()
    loader = create_dataloader(
        dataset,
        CausalLMCollator(context_length=8),
        config,
        shuffle=True,
    )
    trainer = Trainer(
        model=DohaLMTiny(_model_config()),
        dataloader=loader,
        config=config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=checksum_value({"kind": "synthetic", "vocab": 32}),
        output_root=tmp_path / "non-finite-loss",
    )
    original_forward = trainer.model.forward

    def non_finite_forward(*args, **kwargs) -> DohaLMOutput:
        output = original_forward(*args, **kwargs)
        assert output.loss is not None
        return DohaLMOutput(
            logits=output.logits,
            loss=output.loss * float("nan"),
            hidden_states=output.hidden_states,
        )

    trainer.model.forward = non_finite_forward  # type: ignore[method-assign]
    with pytest.raises(TrainingError, match="NON_FINITE_LOSS"):
        trainer.train()

    assert trainer.state.global_step == trainer.state.optimizer_step == 0
