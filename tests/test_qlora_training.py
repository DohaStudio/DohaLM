from __future__ import annotations

import inspect
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from src.training.qlora_training import (
    DynamicSFTCollator,
    QLoRATrainingError,
    StageReporter,
    artifact_paths,
    canonical_fingerprint,
    enable_gradient_checkpointing_once,
    ensure_unused_output,
    require_execution_approval,
    run_allocation_smoke,
    run_backward_diagnostic,
    run_training_smoke,
    validate_checkpoint,
    validate_runtime_config,
)


def test_explicit_run_approval_is_exact() -> None:
    require_execution_approval(expected_run_id="RUN-1", approved_run_id="RUN-1")
    with pytest.raises(QLoRATrainingError, match="^EXPLICIT_RUN_APPROVAL_REQUIRED$"):
        require_execution_approval(expected_run_id="RUN-1", approved_run_id="RUN-2")


def test_dynamic_collator_preserves_labels_and_masks_padding() -> None:
    collator = DynamicSFTCollator(pad_token_id=0, pad_to_multiple_of=8)
    batch = collator([
        {"input_ids": [1, 2, 3], "attention_mask": [1, 1, 1], "labels": [-100, 2, 3]},
        {"input_ids": [4, 5], "attention_mask": [1, 1], "labels": [-100, 5]},
    ])
    assert tuple(batch["input_ids"].shape) == (2, 8)
    assert torch.equal(batch["attention_mask"][1], torch.tensor([1, 1, 0, 0, 0, 0, 0, 0]))
    assert torch.equal(batch["labels"][1], torch.tensor([-100, 5, -100, -100, -100, -100, -100, -100]))


def test_output_collision_is_fail_closed(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    paths = ensure_unused_output(destination)
    assert paths == artifact_paths(destination)
    destination.mkdir()
    with pytest.raises(QLoRATrainingError, match="^OUTPUT_RUN_ID_ALREADY_USED$"):
        ensure_unused_output(destination)


def test_qlora_config_is_cpu_safe_and_execution_disabled() -> None:
    config = validate_runtime_config("configs/training/dohalm-v0.1-qlora.yaml")
    assert config["training_allowed"] is False
    assert config["execution_allowed"] is False
    assert config["training"]["optimizer"] == "paged_adamw_8bit"  # type: ignore[index]


def test_adapter_checkpoint_rejects_full_model_weights(tmp_path: Path) -> None:
    (tmp_path / "adapter_model.safetensors").write_bytes(b"adapter")
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trainer_state.json").write_text(json.dumps({"global_step": 1}), encoding="utf-8")
    result = validate_checkpoint(tmp_path)
    assert result["base_model_weights_present"] is False
    (tmp_path / "model.safetensors").write_bytes(b"forbidden")
    with pytest.raises(QLoRATrainingError, match="^ADAPTER_CHECKPOINT_INVALID$"):
        validate_checkpoint(tmp_path)


def test_canonical_fingerprint_is_order_independent() -> None:
    assert canonical_fingerprint({"a": 1, "b": 2}) == canonical_fingerprint({"b": 2, "a": 1})


class _TinyDiagnosticModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.lora_weight = torch.nn.Parameter(torch.tensor(1.0))
        self.base_weight = torch.nn.Parameter(torch.tensor(1.0), requires_grad=False)

    def forward(self, input_ids: torch.Tensor, labels: torch.Tensor, **_: object) -> object:
        selected = labels != -100
        value = input_ids.float()[selected].mean() * self.lora_weight * self.base_weight
        return SimpleNamespace(loss=value.square())


def _records() -> list[dict[str, list[int]]]:
    return [
        {"input_ids": list(range(1, length + 1)), "attention_mask": [1] * length,
         "labels": [-100] + list(range(2, length + 1))}
        for length in (4, 8, 12)
    ]


@pytest.fixture
def cpu_cuda_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda: None)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda: None)
    monkeypatch.setattr(torch.cuda, "memory_allocated", lambda: 0)
    monkeypatch.setattr(torch.cuda, "memory_reserved", lambda: 0)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda: 0)


def test_allocation_smoke_is_forward_only(cpu_cuda_counters: None) -> None:
    del cpu_cuda_counters
    model = _TinyDiagnosticModel()
    result = run_allocation_smoke(
        model=model,
        tokenizer=SimpleNamespace(pad_token_id=0),
        train_dataset=_records(),
        validation_dataset=_records()[:2],
        reporter=StageReporter(stream=StringIO()),
        device="cpu",
        autocast_enabled=False,
    )
    assert result["backward_calls"] == 0
    assert result["optimizer_creations"] == 0
    assert result["optimizer_steps"] == 0
    assert len(result["batches"]) == 2
    assert model.lora_weight.grad is None


def test_backward_diagnostic_has_no_optimizer_step(cpu_cuda_counters: None) -> None:
    del cpu_cuda_counters
    result = run_backward_diagnostic(
        model=_TinyDiagnosticModel(),
        tokenizer=SimpleNamespace(pad_token_id=0),
        train_dataset=_records(),
        validation_dataset=_records()[:2],
        target_length=128,
        reporter=StageReporter(stream=StringIO()),
        device="cpu",
        autocast_enabled=False,
    )
    assert result["gradient_finite"] is True
    assert result["lora_gradient_tensors"] == 1
    assert result["base_gradient_tensors"] == 0
    assert result["optimizer_creations"] == 0
    assert result["optimizer_steps"] == 0


def test_stage_reporter_fails_after_deadline() -> None:
    clock = iter((0.0, 2.0))
    reporter = StageReporter(clock=lambda: next(clock), stream=StringIO())
    with (
        pytest.raises(QLoRATrainingError, match="^STAGE_TIMEOUT_SAMPLE$"),
        reporter.stage("sample", timeout_seconds=1.0),
    ):
        pass
    assert reporter.events[-1]["status"] == "timeout"


def test_gradient_checkpointing_has_one_owner() -> None:
    class Model:
        is_gradient_checkpointing = False
        input_calls = 0
        checkpoint_calls = 0

        def enable_input_require_grads(self) -> None:
            self.input_calls += 1

        def gradient_checkpointing_enable(self, **_: object) -> None:
            self.checkpoint_calls += 1
            self.is_gradient_checkpointing = True

    model = Model()
    enable_gradient_checkpointing_once(model)
    assert model.input_calls == 1
    assert model.checkpoint_calls == 1
    with pytest.raises(QLoRATrainingError, match="^GRADIENT_CHECKPOINTING_ALREADY_ENABLED$"):
        enable_gradient_checkpointing_once(model)


def test_only_training_smoke_owns_optimizer_creation() -> None:
    assert "create_optimizer(" not in inspect.getsource(run_allocation_smoke)
    assert "create_optimizer(" not in inspect.getsource(run_backward_diagnostic)
    assert "create_optimizer(" in inspect.getsource(run_training_smoke)
