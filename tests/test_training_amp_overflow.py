from __future__ import annotations

import json

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
from src.training.metrics import JsonlMetricLogger


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


def _set_amp_scale(trainer: Trainer, scale: float) -> None:
    state = trainer.scaler.state_dict()
    state["scale"] = scale
    state["_growth_tracker"] = 0
    trainer.scaler.load_state_dict(state)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_single_amp_overflow_retries_same_batch_without_step_or_sampler_drift(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "overflow")
    events = []
    diagnostics = []
    handle = _inject_gradient_overflow(trainer, repeated=False)
    try:
        result = trainer.train(
            amp_overflow_observer=events.append,
            amp_diagnostic_observer=diagnostics.append,
            minimum_amp_scale=64.0,
            amp_diagnostic_scale_floor=64.0,
        )
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
    assert [item.probe_scale for item in diagnostics] == [
        1_024.0,
        512.0,
        256.0,
        128.0,
        64.0,
    ]
    assert all(item.optimizer_step_applied is False for item in diagnostics)
    assert all(item.accounting_state_unchanged for item in diagnostics)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_r6_pattern_recovers_on_fourth_attempt_without_accounting_drift(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "r6-pattern")
    _set_amp_scale(trainer, 131_072.0)
    events = []

    def overflow_above_recovery_floor(gradient: torch.Tensor) -> torch.Tensor:
        if trainer.scaler.get_scale() > 16_384.0:
            return torch.full_like(gradient, float("inf"))
        return gradient

    handle = next(trainer.model.parameters()).register_hook(
        overflow_above_recovery_floor
    )
    try:
        result = trainer.train(
            amp_overflow_observer=events.append,
            minimum_amp_scale=1_024.0,
        )
    finally:
        handle.remove()

    assert len(events) == 3
    assert [event.attempt for event in events] == [1, 2, 3]
    assert all(event.global_step == 0 for event in events)
    assert [event.scale_before for event in events] == [131_072.0, 65_536.0, 32_768.0]
    assert [event.scale_after for event in events] == [65_536.0, 32_768.0, 16_384.0]
    assert result.state.global_step == result.state.optimizer_step == 1
    assert result.state.tokens_seen > 0 and result.state.records_seen == 2
    assert result.state.sampler_state is not None
    assert result.state.sampler_state["records_yielded"] == 2
    assert result.metrics[0].amp_overflow_count == 3


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_prospective_scale_probe_records_lower_scale_recovery_without_mutation(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "diagnostic-recovery")
    events = []
    diagnostic_path = tmp_path / "diagnostic-recovery.jsonl"
    logger = JsonlMetricLogger(diagnostic_path)
    first_max = None

    def scale_sensitive_overflow(gradient: torch.Tensor) -> torch.Tensor:
        nonlocal first_max
        maximum = float(gradient.detach().abs().max().item())
        if first_max is None:
            first_max = maximum
        assert first_max > 0
        if maximum > first_max * 0.2:
            return torch.full_like(gradient, float("inf"))
        return gradient

    before_model = trainer._model_state_fingerprint()
    before_optimizer = trainer._optimizer_state_fingerprint()
    probe_rng_boundaries = []
    original_probe = trainer._probe_amp_numerical_state

    def observe_probe_rng_boundary(**kwargs):
        before = trainer._rng_checksums(trainer._capture_attempt_rng())
        result = original_probe(**kwargs)
        after = trainer._rng_checksums(trainer._capture_attempt_rng())
        probe_rng_boundaries.append((before, after))
        return result

    trainer._probe_amp_numerical_state = observe_probe_rng_boundary
    handle = next(trainer.model.parameters()).register_hook(scale_sensitive_overflow)
    try:
        result = trainer.train(
            amp_overflow_observer=events.append,
            amp_diagnostic_observer=logger.write,
            minimum_amp_scale=64.0,
            amp_diagnostic_scale_floor=64.0,
        )
    finally:
        handle.remove()

    diagnostics = [
        json.loads(line)
        for line in diagnostic_path.read_text(encoding="utf-8").splitlines()
    ]
    forbidden_fields = {"text", "token_ids", "input_ids", "labels", "prompt"}
    assert all(not (forbidden_fields & set(item)) for item in diagnostics)
    final_attempt = [item for item in diagnostics if item["overflow_attempt"] == 3]
    assert [item["probe_scale"] for item in final_attempt] == [256.0, 128.0, 64.0]
    assert diagnostics[0]["grad_scaler_found_inf"] is True
    assert any(item["unscaled_gradients_finite"] for item in diagnostics[1:])
    assert len({item["batch_identity_sha256"] for item in diagnostics}) == 1
    assert len({item["python_rng_sha256"] for item in diagnostics}) == 1
    assert len({item["cpu_rng_sha256"] for item in diagnostics}) == 1
    assert len({item["cuda_rng_sha256"] for item in diagnostics}) == 1
    assert len({item["model_state_sha256"] for item in diagnostics}) == 1
    assert len({item["optimizer_state_sha256"] for item in diagnostics}) == 1
    assert all(item["model_state_unchanged"] for item in diagnostics)
    assert all(item["optimizer_state_unchanged"] for item in diagnostics)
    assert all(item["scheduler_state_unchanged"] for item in diagnostics)
    assert all(item["scaler_state_unchanged"] for item in diagnostics)
    assert all(item["sampler_state_unchanged"] for item in diagnostics)
    assert all(item["accounting_state_unchanged"] for item in diagnostics)
    assert all(item["rng_state_restored"] for item in diagnostics)
    assert all(item["optimizer_step_applied"] is False for item in diagnostics)
    assert all(item["actual_text_values_stored"] is False for item in diagnostics)
    assert all(item["token_ids_stored"] is False for item in diagnostics)
    assert trainer._model_state_fingerprint() != before_model
    assert trainer._optimizer_state_fingerprint() != before_optimizer
    assert all(before == after for before, after in probe_rng_boundaries)
    assert result.state.global_step == result.state.optimizer_step == 1
    assert result.state.tokens_seen > 0 and result.state.records_seen == 2
    assert len(events) == 3


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_prospective_scale_probe_records_all_scale_overflow_and_fails_closed(
    tmp_path,
) -> None:
    trainer = _amp_trainer(tmp_path / "diagnostic-overflow")
    diagnostics = []
    handle = _inject_gradient_overflow(trainer, repeated=True)
    try:
        with pytest.raises(
            TrainingError, match="FULL_PRETRAINING_AMP_SCALE_FLOOR_EXHAUSTED"
        ):
            trainer.train(
                amp_diagnostic_observer=diagnostics.append,
                minimum_amp_scale=64.0,
                amp_diagnostic_scale_floor=64.0,
            )
    finally:
        handle.remove()

    final_attempt = [item for item in diagnostics if item.overflow_attempt == 5]
    assert [item.probe_scale for item in final_attempt] == [64.0]
    assert all(item.grad_scaler_found_inf for item in final_attempt)
    assert all(not item.scaled_gradients_finite for item in final_attempt)
    assert all(not item.unscaled_gradients_finite for item in final_attempt)
    assert all(item.first_offending_parameter_id for item in final_attempt)
    assert all(item.first_offending_parameter_shape for item in final_attempt)
    assert all(item.first_offending_parameter_dtype for item in final_attempt)
    assert all(item.unscaled_non_finite_element_count > 0 for item in final_attempt)
    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_amp_overflow_recovers_at_configured_scale_floor(tmp_path) -> None:
    trainer = _amp_trainer(tmp_path / "floor-recovery")
    _set_amp_scale(trainer, 2_048.0)
    events = []

    def overflow_above_floor(gradient: torch.Tensor) -> torch.Tensor:
        if trainer.scaler.get_scale() > 1_024.0:
            return torch.full_like(gradient, float("inf"))
        return gradient

    handle = next(trainer.model.parameters()).register_hook(overflow_above_floor)
    try:
        result = trainer.train(
            amp_overflow_observer=events.append,
            minimum_amp_scale=1_024.0,
        )
    finally:
        handle.remove()

    assert len(events) == 1
    assert events[0].scale_before == 2_048.0
    assert events[0].scale_after == 1_024.0
    assert result.state.global_step == result.state.optimizer_step == 1
    assert result.metrics[0].amp_scale == 1_024.0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_amp_overflow_at_scale_floor_fails_without_accounting(tmp_path) -> None:
    trainer = _amp_trainer(tmp_path / "floor-exhausted")
    events = []
    handle = _inject_gradient_overflow(trainer, repeated=True)
    try:
        with pytest.raises(
            TrainingError, match="FULL_PRETRAINING_AMP_SCALE_FLOOR_EXHAUSTED"
        ):
            trainer.train(
                amp_overflow_observer=events.append,
                minimum_amp_scale=1_024.0,
            )
    finally:
        handle.remove()

    assert len(events) == 1
    assert events[0].scale_before == 1_024.0
    assert events[0].scale_after == 512.0
    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0
    assert trainer.state.sampler_state is None


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_amp_overflow_without_scale_backoff_is_fatal(tmp_path, monkeypatch) -> None:
    trainer = _amp_trainer(tmp_path / "backoff-failure")
    handle = _inject_gradient_overflow(trainer, repeated=True)
    monkeypatch.setattr(trainer.scaler, "update", lambda *args, **kwargs: None)
    try:
        with pytest.raises(TrainingError, match="NON_FINITE_GRADIENT"):
            trainer.train(minimum_amp_scale=64.0)
    finally:
        handle.remove()

    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_amp_overflow_with_corrupted_model_state_is_fatal(tmp_path) -> None:
    trainer = _amp_trainer(tmp_path / "model-corrupted")
    parameter = next(trainer.model.parameters())

    def corrupt_model(gradient: torch.Tensor) -> torch.Tensor:
        parameter.data.fill_(float("inf"))
        return torch.full_like(gradient, float("inf"))

    handle = parameter.register_hook(corrupt_model)
    try:
        with pytest.raises(TrainingError, match="NON_FINITE_GRADIENT"):
            trainer.train(minimum_amp_scale=64.0)
    finally:
        handle.remove()

    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is not available")
def test_prospective_scale_probe_evidence_failure_is_fatal(tmp_path) -> None:
    trainer = _amp_trainer(tmp_path / "diagnostic-write-failure")
    handle = _inject_gradient_overflow(trainer, repeated=True)

    def fail_evidence_write(_event) -> None:
        raise OSError("synthetic evidence failure")

    try:
        with pytest.raises(TrainingError, match="DIAGNOSTIC_EVIDENCE_FAILURE"):
            trainer.train(
                amp_diagnostic_observer=fail_evidence_write,
                minimum_amp_scale=64.0,
                amp_diagnostic_scale_floor=64.0,
            )
    finally:
        handle.remove()

    assert trainer.state.global_step == trainer.state.optimizer_step == 0
    assert trainer.state.tokens_seen == trainer.state.records_seen == 0


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
