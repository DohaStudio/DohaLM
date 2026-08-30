from __future__ import annotations

import pytest
from _training_helpers import training_config

from src.training import TrainingConfig, TrainingError


def test_default_training_config_contract():
    config = TrainingConfig()
    assert config.effective_batch_size == 2
    assert config.amp_dtype == "float16"
    assert config.device == "cpu"


def test_training_config_round_trip_and_fingerprints():
    config = training_config()
    assert config.to_dict()["effective_batch_size"] == 2
    assert config.fingerprint().startswith("sha256:")
    assert config.resume_fingerprint().startswith("sha256:")


def test_non_core_output_fields_do_not_change_resume_fingerprint():
    one = training_config(output_dir="tests/output/a", log_every=1, save_every=1)
    two = training_config(output_dir="tests/output/b", log_every=2, save_every=2)
    assert one.fingerprint() != two.fingerprint()
    assert one.resume_fingerprint() == two.resume_fingerprint()


@pytest.mark.parametrize("changes", [
    {"batch_size": 0},
    {"micro_batch_size": 0},
    {"gradient_accumulation_steps": 0},
    {"max_steps": 0},
    {"learning_rate": 0},
    {"weight_decay": -0.1},
    {"epsilon": 0},
    {"max_grad_norm": 0},
    {"warmup_steps": 3},
    {"num_workers": -1},
    {"seed": -1},
    {"batch_size": 3},
])
def test_invalid_numeric_training_config(changes):
    with pytest.raises(TrainingError, match="INVALID_TRAINING_CONFIG"):
        training_config(**changes)


@pytest.mark.parametrize("output", ["result", "../tests/output/x", "D:/outside", "/tmp/out", ""])
def test_output_must_be_repository_relative_ignored_path(output):
    with pytest.raises(TrainingError, match="INVALID_TRAINING_CONFIG"):
        training_config(output_dir=output)


def test_supported_output_roots():
    for output in ("tests/output/x", "checkpoints/x", "artifacts/x", "logs/x", "experiments/x"):
        assert training_config(output_dir=output).output_dir == output


def test_bfloat16_is_explicitly_unsupported():
    with pytest.raises(TrainingError, match="INVALID_TRAINING_CONFIG"):
        training_config(amp_dtype="bfloat16")


def test_cpu_amp_is_blocked():
    with pytest.raises(TrainingError, match="AMP_NOT_AVAILABLE"):
        training_config(use_amp=True, device="cpu")
