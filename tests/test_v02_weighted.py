from __future__ import annotations

import inspect
import math
from pathlib import Path

import pytest
import torch

from src.data.errors import DataPipelineError
from src.training.v02_weighted import (
    EpochWeightedSampler,
    SidecarWeightedTrainerMixin,
    V02WeightedError,
    build_train_sampler,
    build_validation_sampler,
    read_safetensors_f64,
    write_safetensors_f64,
)
from src.training import v02_weighted


def test_weight_serialization_is_float64_and_exact(tmp_path: Path) -> None:
    path = tmp_path / "weights.safetensors"
    expected = {"train": [0.25, 1.0, 3.0], "validation": [1.0, 1.0]}
    write_safetensors_f64(path, expected)
    assert read_safetensors_f64(path) == expected
    assert path.read_bytes()[8:16] != b"\x00" * 8


@pytest.mark.parametrize("values", [[0.0], [-1.0], [math.inf], [math.nan]])
def test_weight_serialization_rejects_invalid_values(tmp_path: Path, values: list[float]) -> None:
    with pytest.raises(V02WeightedError, match="^SAMPLING_WEIGHT_INVALID$"):
        write_safetensors_f64(tmp_path / "weights.safetensors", {"train": values})


def test_weighted_sampler_is_deterministic_and_changes_by_epoch() -> None:
    sampler = EpochWeightedSampler([0.25, 1.0, 3.0], num_samples=20, base_seed=42)
    first = sampler.draw_order()
    assert first == sampler.draw_order()
    first_fingerprint = sampler.draw_order_fingerprint()
    sampler.set_epoch(1)
    assert sampler.draw_order() != first
    assert sampler.draw_order_fingerprint() != first_fingerprint


def test_weighted_sampler_uses_replacement_and_exact_draw_count() -> None:
    sampler = EpochWeightedSampler([0.01, 0.01, 100.0], num_samples=10374, base_seed=42)
    draws = list(sampler)
    assert len(draws) == 10374
    assert len(set(draws)) < len(draws)
    assert draws.count(2) > 10000


def test_sampler_fails_closed_for_distributed_training() -> None:
    with pytest.raises(V02WeightedError, match="^DISTRIBUTED_WEIGHTED_SAMPLING_UNSUPPORTED$"):
        build_train_sampler([1.0], dataset_size=1, world_size=2, rank=0)


def test_sampler_fails_closed_for_weight_alignment() -> None:
    with pytest.raises(V02WeightedError, match="^SAMPLING_WEIGHT_ALIGNMENT_INVALID$"):
        build_train_sampler([1.0], dataset_size=2, world_size=1, rank=0)


def test_validation_sampler_is_sequential_and_unweighted() -> None:
    sampler = build_validation_sampler(["a", "b", "c"])
    assert list(sampler) == [0, 1, 2]


def test_trainer_override_changes_only_sampler_boundary() -> None:
    source = inspect.getsource(SidecarWeightedTrainerMixin._get_train_sampler)
    assert "build_train_sampler" in source
    assert "optimizer" not in source
    assert "scheduler" not in source
    assert "loss" not in source


def test_repository_configs_are_fail_closed() -> None:
    import yaml

    tokenization = yaml.safe_load(Path("configs/training/dohalm-v0.2-weighted-tokenization.yaml").read_text(encoding="utf-8"))
    readiness = yaml.safe_load(Path("configs/training/dohalm-v0.2-qlora-readiness.yaml").read_text(encoding="utf-8"))
    assert tokenization["sampling"] == {
        "replacement": True,
        "draws_per_epoch": 10374,
        "base_seed": 42,
        "epoch_seed_formula": "base_seed + epoch_index",
        "world_size": 1,
        "rank": 0,
    }
    assert tokenization["validation"]["weighted"] is False
    assert readiness["training"]["expected_optimizer_steps_total"] == 1298
    assert readiness["training_allowed"] is False
    assert readiness["execution_allowed"] is False
    assert torch.tensor(0).item() == 0


def test_checksum_reload_and_no_replace_artifact(tmp_path: Path) -> None:
    final = tmp_path / "artifact"
    atomic = v02_weighted.AtomicArtifactDirectory(final)
    with atomic as staging:
        v02_weighted._write_json_durable(staging / "value.json", {"value": 1})
        expected = v02_weighted._write_checksums(staging)
        assert v02_weighted._validate_checksums(staging) == expected
        atomic.publish()
    second = v02_weighted.AtomicArtifactDirectory(final)
    with pytest.raises(DataPipelineError):
        second.__enter__()


def test_token_row_alignment_contract() -> None:
    metadata = {"prompt_tokens": 2, "assistant_tokens": 2, "total_tokens": 4}
    row = {
        "input_ids": [10, 11, 12, 151645],
        "attention_mask": [1, 1, 1, 1],
        "labels": [-100, -100, 12, 151645],
    }
    assert v02_weighted._validate_token_row(row, metadata) == {
        "total_tokens": 4,
        "assistant_tokens": 2,
    }
    row["labels"] = [-100, 11, 12, 151645]
    with pytest.raises(V02WeightedError, match="^TOKENIZATION_CONTRACT_INVALID$"):
        v02_weighted._validate_token_row(row, metadata)
