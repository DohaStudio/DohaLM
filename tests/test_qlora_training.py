from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from src.training.qlora_training import (
    DynamicSFTCollator,
    QLoRATrainingError,
    artifact_paths,
    canonical_fingerprint,
    ensure_unused_output,
    require_execution_approval,
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
