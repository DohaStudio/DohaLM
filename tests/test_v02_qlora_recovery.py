from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from scripts.training.recover_dohalm_v02_evaluation import parser
from src.training.v02_qlora_recovery import (
    RECOVERY_ID,
    V02QLoRAError,
    _write_recovery_package,
    select_candidate,
    validate_checkpoint_inventory,
    validate_training_completion,
)
from src.training.v02_qlora_training import (
    expected_checkpoint_steps,
    validate_checkpoint_steps,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _checkpoint(root: Path, step: int, *, model: bytes, config: dict[str, object] | None = None) -> None:
    root.mkdir(parents=True)
    (root / "adapter_model.safetensors").write_bytes(model)
    (root / "adapter_config.json").write_text(
        json.dumps(config or {"base_model_name_or_path": "Qwen/Qwen2.5-1.5B-Instruct"}), encoding="utf-8",
    )
    (root / "trainer_state.json").write_text(
        json.dumps({"global_step": step, "epoch": 2.0}), encoding="utf-8",
    )


def _failed_artifact(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "DOHALM-V0.2-QLORA-20260801-0001.failed"
    terminal = b"terminal-adapter"
    for step in (250, 500, 750, 1000, 1250, 1298):
        _checkpoint(root / "checkpoints" / f"checkpoint-{step}", step, model=terminal if step == 1298 else str(step).encode())
    _checkpoint(root / "final-adapter", 1298, model=terminal)
    (root / "final-adapter" / "training-config.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (root / "metrics.jsonl").write_text(json.dumps({
        "global_step": 1298, "epoch": 2.0, "train_runtime": 16845.39, "train_loss": 1.119847,
    }) + "\n", encoding="utf-8")
    return root, _sha(terminal)


def test_checkpoint_schedule_accepts_single_non_aligned_terminal() -> None:
    expected = (250, 500, 750, 1000, 1250, 1298)
    assert expected_checkpoint_steps(save_steps=250, total_optimizer_steps=1298) == expected
    assert validate_checkpoint_steps(expected, save_steps=250, total_optimizer_steps=1298) == expected


def test_checkpoint_schedule_does_not_duplicate_aligned_terminal() -> None:
    assert expected_checkpoint_steps(save_steps=250, total_optimizer_steps=1250) == (250, 500, 750, 1000)


@pytest.mark.parametrize("steps", [
    (250, 500, 750, 1000, 1250),
    (250, 500, 750, 1000, 1250, 1297),
    (250, 500, 750, 1000, 1250, 1298, 1298),
    (250, 500, 750, 1000, 1100, 1250, 1298),
    (250, 500, 750, 1000, 1250, 1298, 1299),
])
def test_checkpoint_schedule_rejects_missing_or_invalid_steps(steps: tuple[int, ...]) -> None:
    with pytest.raises(V02QLoRAError, match="CHECKPOINT_SCHEDULE_INVALID"):
        validate_checkpoint_steps(steps, save_steps=250, total_optimizer_steps=1298)


def test_inventory_accepts_terminal_and_equivalent_final(tmp_path: Path) -> None:
    root, expected_sha = _failed_artifact(tmp_path)
    result = validate_checkpoint_inventory(root, expected_final_sha256=expected_sha)
    assert [item["step"] for item in result["candidates"]] == [250, 500, 750, 1000, 1250, 1298, 1298]
    assert result["terminal_checkpoint_equivalent_to_final_adapter"] is True
    assert result["candidates"][-1]["equivalent_to"] == "checkpoint-1298"


def test_inventory_rejects_missing_scheduled_checkpoint(tmp_path: Path) -> None:
    root, expected_sha = _failed_artifact(tmp_path)
    (root / "checkpoints" / "checkpoint-750").rename(root / "checkpoint-750-removed")
    with pytest.raises(V02QLoRAError, match="CHECKPOINT_SCHEDULE_INVALID"):
        validate_checkpoint_inventory(root, expected_final_sha256=expected_sha)


def test_inventory_rejects_different_final_config(tmp_path: Path) -> None:
    root, expected_sha = _failed_artifact(tmp_path)
    (root / "final-adapter" / "adapter_config.json").write_text(
        json.dumps({
            "base_model_name_or_path": "Qwen/Qwen2.5-1.5B-Instruct",
            "revision": "different",
        }), encoding="utf-8",
    )
    with pytest.raises(V02QLoRAError, match="FINAL_ADAPTER_EQUIVALENCE_FAILED"):
        validate_checkpoint_inventory(root, expected_final_sha256=expected_sha)


def test_recovery_gate_accepts_only_complete_finite_training(tmp_path: Path) -> None:
    root, _ = _failed_artifact(tmp_path)
    result = validate_training_completion(root)
    assert result["training_completed"] is True
    assert result["optimizer_steps"] == 1298
    (root / "metrics.jsonl").write_text(json.dumps({
        "global_step": 1297, "epoch": 1.99, "train_runtime": 1, "train_loss": 1.0,
    }) + "\n", encoding="utf-8")
    with pytest.raises(V02QLoRAError, match="TRAINING_COMPLETION_EVIDENCE_INVALID"):
        validate_training_completion(root)


def test_recovery_gate_rejects_nonfinite_training(tmp_path: Path) -> None:
    root, _ = _failed_artifact(tmp_path)
    (root / "metrics.jsonl").write_text(json.dumps({
        "global_step": 1298, "epoch": 2.0, "train_runtime": 1, "train_loss": float("nan"),
    }) + "\n", encoding="utf-8")
    with pytest.raises(V02QLoRAError, match="TRAINING_COMPLETION_EVIDENCE_INVALID"):
        validate_training_completion(root)


def test_recovery_gate_rejects_other_failure_code(tmp_path: Path) -> None:
    root, _ = _failed_artifact(tmp_path)
    with pytest.raises(V02QLoRAError, match="RECOVERY_FAILURE_NOT_ELIGIBLE"):
        validate_training_completion(root, failure_code="CUDA_OOM")


def _candidate(*, f1: float, rouge: float, eos: int, repetition: int, loss: float) -> dict[str, object]:
    overall = {
        "samples": 20, "character_f1": f1, "rouge_l": rouge, "empty": 0,
        "special_token_exposure": 0, "repetition": repetition,
        "maximum_length_reached": 20 - eos, "eos_terminated": eos,
    }
    from src.training.v02_qlora_training import generation_verdict
    return {
        "token_weighted_validation_loss": loss,
        "generation": {"overall": overall},
        "verdict": generation_verdict(overall),
    }


def test_candidate_selection_rejects_hard_blocker_and_is_not_loss_only() -> None:
    result = select_candidate({
        "low-loss-blocked": _candidate(f1=.3, rouge=.2, eos=20, repetition=0, loss=.5),
        "stable": _candidate(f1=.5, rouge=.4, eos=20, repetition=0, loss=1.2),
        "less-stable": _candidate(f1=.49, rouge=.35, eos=18, repetition=2, loss=.8),
    })
    assert result["selected_candidate"] == "stable"
    assert result["deployment_ready"] is True


def test_atomic_recovery_writer_is_no_replace_and_has_no_staging_residue(tmp_path: Path) -> None:
    final = _write_recovery_package(tmp_path, {
        "recovery-manifest.yaml": {"status": "ok"},
        "checkpoint-inventory.json": {"candidates": []},
        "validation-loss-results.json": {},
        "generation-evaluation.json": {},
        "candidate-selection.json": {},
        "environment.json": {},
        "training-recovery-result.yaml": {"status": "completed"},
    })
    assert final.is_dir()
    assert (final / "checksums.sha256").is_file()
    assert not final.with_name(final.name + ".staging").exists()
    with pytest.raises(Exception, match="OUTPUT_RUN_ID_ALREADY_USED"):
        _write_recovery_package(tmp_path, {"recovery-manifest.yaml": {}})


def test_atomic_recovery_writer_quarantines_injected_failure(tmp_path: Path) -> None:
    def fail() -> None:
        raise RuntimeError("injected")

    files = {
        "recovery-manifest.yaml": {}, "checkpoint-inventory.json": {},
        "validation-loss-results.json": {}, "generation-evaluation.json": {},
        "candidate-selection.json": {}, "environment.json": {},
        "training-recovery-result.yaml": {},
    }
    with pytest.raises(RuntimeError, match="injected"):
        _write_recovery_package(tmp_path, files, before_publish=fail)
    final = tmp_path / RECOVERY_ID
    assert not final.exists()
    assert not final.with_name(final.name + ".staging").exists()
    assert final.with_name(final.name + ".failed").is_dir()


def test_recovery_service_has_no_training_surface() -> None:
    from src.training.v02_qlora_recovery import recover_dohalm_v02_training_evaluation
    source = inspect.getsource(recover_dohalm_v02_training_evaluation)
    assert ".train(" not in source
    assert ".backward(" not in source
    assert "optimizer.step" not in source
    assert "save_pretrained" not in source


def test_cli_requires_exact_recovery_identity() -> None:
    arguments = parser().parse_args([
        "--approved-recovery-id", RECOVERY_ID,
        "--evaluation-governance-head", "a" * 40,
        "--failed-training-root", "failed",
        "--output-root", "output",
        "--tokenized-root", "tokenized",
        "--sidecar-root", "sidecar",
        "--model-cache-root", "cache",
    ])
    assert arguments.approved_recovery_id == RECOVERY_ID
