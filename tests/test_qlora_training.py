from __future__ import annotations

import inspect
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from scripts.training.train_dohalm_v01_qlora import _expected_run_id, _roots
from src.training import qlora_training
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
    run_stability_smoke,
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


def test_wsl_runtime_ids_are_separate_from_windows() -> None:
    assert _expected_run_id("full", "windows") != _expected_run_id("full", "wsl")
    assert _expected_run_id("allocation", "wsl").endswith("WSL-20260731-0002")
    assert _expected_run_id("backward", "wsl").endswith("WSL-20260731-0002")
    assert _expected_run_id("training-smoke-1", "wsl") == (
        qlora_training.WSL_TRAINING_SMOKE_STAGE1_RUN_ID
    )
    assert _expected_run_id("training-smoke-2", "wsl") == (
        qlora_training.WSL_TRAINING_SMOKE_STAGE2_RUN_ID
    )
    assert qlora_training.RETIRED_WSL_STABILITY_RUN_ID.endswith("WSL-20260731-0001")
    assert qlora_training.WSL_STABILITY_RUN_ID.endswith("WSL-20260731-0002")
    assert _expected_run_id("stability", "wsl") == qlora_training.WSL_STABILITY_RUN_ID
    assert _expected_run_id("full", "wsl") == qlora_training.WSL_RUN_ID


def test_wsl_prerequisite_roots_use_distinct_active_ids(tmp_path: Path) -> None:
    roots = _roots(tmp_path, "wsl")
    assert roots["allocation"].name == qlora_training.WSL_ALLOCATION_SMOKE_RUN_ID
    assert roots["backward"].name == qlora_training.WSL_BACKWARD_DIAGNOSTIC_RUN_ID
    assert roots["training_stage_1"] == (
        tmp_path
        / "smoke"
        / qlora_training.WSL_TRAINING_SMOKE_STAGE1_RUN_ID
        / "stage-1"
    )
    assert roots["training_stage_2"] == (
        tmp_path
        / "smoke"
        / qlora_training.WSL_TRAINING_SMOKE_STAGE2_RUN_ID
        / "stage-2"
    )


def test_windows_training_smoke_roots_remain_backward_compatible(tmp_path: Path) -> None:
    roots = _roots(tmp_path, "windows")
    base = tmp_path / "smoke" / qlora_training.TRAINING_SMOKE_RUN_ID
    assert roots["training_stage_1"] == base / "stage-1"
    assert roots["training_stage_2"] == base / "stage-2"


@pytest.mark.parametrize(
    ("mode", "retired_run_id"),
    (
        ("allocation", qlora_training.RETIRED_WSL_ALLOCATION_SMOKE_RUN_ID),
        ("backward", qlora_training.RETIRED_WSL_BACKWARD_DIAGNOSTIC_RUN_ID),
        ("training-smoke-1", qlora_training.RETIRED_WSL_TRAINING_SMOKE_RUN_ID),
        ("training-smoke-2", qlora_training.RETIRED_WSL_TRAINING_SMOKE_RUN_ID),
    ),
)
def test_wsl_prerequisites_reject_retired_run_ids(
    mode: str,
    retired_run_id: str,
) -> None:
    with pytest.raises(QLoRATrainingError, match="^EXPLICIT_RUN_APPROVAL_REQUIRED$"):
        require_execution_approval(
            expected_run_id=_expected_run_id(mode, "wsl"),
            approved_run_id=retired_run_id,
        )


def test_wsl_stability_uses_0002_canonical_root(tmp_path: Path) -> None:
    root = _roots(tmp_path, "wsl")["stability"]
    assert root == tmp_path / "stability" / qlora_training.WSL_STABILITY_RUN_ID
    assert "0001" not in root.as_posix()


@pytest.mark.parametrize("occupied", ("final", "staging", "failed"))
def test_wsl_stability_0002_canonical_root_is_no_replace(
    tmp_path: Path,
    occupied: str,
) -> None:
    root = _roots(tmp_path / occupied, "wsl")["stability"]
    paths = artifact_paths(root)
    getattr(paths, occupied).mkdir(parents=True)
    with pytest.raises(QLoRATrainingError, match="^OUTPUT_RUN_ID_ALREADY_USED$"):
        ensure_unused_output(root)


@pytest.mark.parametrize(
    "rejected_run_id",
    (
        qlora_training.RETIRED_WSL_STABILITY_RUN_ID,
        "DOHALM-V0.1-QLORA-STABILITY-WSL-20260731-0003",
        qlora_training.WSL_RUN_ID,
        "NOT-AVAILABLE-WINDOWS",
        "",
    ),
)
def test_wsl_stability_rejects_non_active_run_ids(
    tmp_path: Path,
    rejected_run_id: str,
) -> None:
    expected = _expected_run_id("stability", "wsl")
    with pytest.raises(QLoRATrainingError, match="^EXPLICIT_RUN_APPROVAL_REQUIRED$"):
        require_execution_approval(expected_run_id=expected, approved_run_id=rejected_run_id)
    assert not _roots(tmp_path, "wsl")["stability"].exists()


def test_stability_smoke_runs_128_batches_and_8_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_cuda_counters: None,
) -> None:
    del cpu_cuda_counters
    monkeypatch.setattr(
        qlora_training,
        "create_optimizer",
        lambda model, **_: torch.optim.SGD(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=0.01,
        ),
    )
    records = [_records()[index % 3] for index in range(128)]
    config = {
        "training": {
            "seed": 42,
            "learning_rate": 0.01,
            "weight_decay": 0.0,
            "max_grad_norm": 1.0,
        },
    }
    result = run_stability_smoke(
        paths=ensure_unused_output(tmp_path / "stability"),
        model=_TinyDiagnosticModel(),
        tokenizer=SimpleNamespace(pad_token_id=0),
        train_dataset=records,
        config=config,
        environment={"platform": "synthetic"},
        git_identity={"head": "abc"},
        dataset_identity={"fingerprint": "synthetic"},
        model_statistics_value={"model": "tiny"},
        training_smoke_result={
            "evaluation_seconds": 1.0,
            "eval_batches": 2,
            "checkpoint_seconds": 1.0,
        },
        reporter=StageReporter(stream=StringIO()),
        device="cpu",
        autocast_enabled=False,
    )
    assert result["micro_batches"] == 128
    assert result["optimizer_steps"] == 8
    assert result["stalled_batches"] == 0
    assert result["base_weights_changed"] is False
    assert (tmp_path / "stability" / "checksums.sha256").is_file()


def test_full_training_has_300_second_micro_batch_heartbeat() -> None:
    source = inspect.getsource(qlora_training.run_full_training)
    assert '"full_training_micro_batch"' in source
    assert 'STAGE_TIMEOUTS["full_training_micro_batch"]' in source
    assert "torch.cuda.synchronize()" in source
