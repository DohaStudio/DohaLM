from __future__ import annotations

import pytest
import torch
from _training_helpers import build_tiny_trainer, training_config

from src.training import CheckpointManager, TrainingError


def prepare(tmp_path):
    config = training_config(max_steps=2, save_every=1)
    trainer, _ = build_tiny_trainer(tmp_path / "split", config=config)
    trainer.train(target_steps=1)
    return config, trainer, tmp_path / "split" / "checkpoint-1"


def test_resume_restores_step_lr_and_weight_tying(tmp_path):
    config, _, checkpoint = prepare(tmp_path)
    resumed, _ = build_tiny_trainer(tmp_path / "split", config=config, resume=True)
    state = resumed.resume_from(checkpoint)
    assert state.global_step == state.optimizer_step == resumed.scheduler.current_step == 1
    assert state.last_learning_rate == resumed.scheduler.get_last_lr()[0]
    assert resumed.model.token_embedding.weight is resumed.model.lm_head.weight


def test_resume_continuation_matches_uninterrupted_weights(tmp_path):
    config = training_config(max_steps=2, save_every=2)
    uninterrupted, _ = build_tiny_trainer(tmp_path / "full", config=config)
    uninterrupted.train()
    split_config = training_config(max_steps=2, save_every=1)
    split, _ = build_tiny_trainer(tmp_path / "split", config=split_config)
    split.train(target_steps=1)
    resumed, _ = build_tiny_trainer(tmp_path / "split", config=split_config, resume=True)
    resumed.resume_from(tmp_path / "split" / "checkpoint-1")
    result = resumed.train(target_steps=2)
    assert result.state.global_step == 2
    for left, right in zip(uninterrupted.model.parameters(), resumed.model.parameters(), strict=True):
        assert torch.equal(left, right)


def test_resume_appends_metrics_without_rewriting_history(tmp_path):
    config, _, checkpoint = prepare(tmp_path)
    metrics = checkpoint.parent / "metrics.jsonl"
    before = metrics.read_text()
    resumed, _ = build_tiny_trainer(checkpoint.parent, config=config, resume=True)
    resumed.resume_from(checkpoint)
    resumed.train(target_steps=2)
    after = metrics.read_text()
    assert after.startswith(before) and len(after.splitlines()) == 2


@pytest.mark.parametrize("kind,code", [
    ("dataset", "CHECKPOINT_DATASET_MISMATCH"),
    ("tokenizer", "CHECKPOINT_TOKENIZER_MISMATCH"),
])
def test_resume_fingerprint_mismatch_is_blocked(tmp_path, kind, code):
    config, _, checkpoint = prepare(tmp_path)
    resumed, _ = build_tiny_trainer(checkpoint.parent, config=config, resume=True)
    if kind == "dataset":
        resumed.dataset_fingerprint = "sha256:different"
    else:
        resumed.tokenizer_fingerprint = "sha256:different"
    with pytest.raises(TrainingError, match=code):
        resumed.resume_from(checkpoint)


@pytest.mark.parametrize("changes", [
    {"vocab_size": 33},
    {"num_layers": 2},
    {"hidden_size": 20, "head_dim": 5, "ffn_size": 40},
])
def test_resume_model_config_mismatch_is_blocked(tmp_path, changes):
    config, trainer, checkpoint = prepare(tmp_path)
    altered = trainer.model.config.to_dict()
    altered.update(changes)
    object.__setattr__(trainer.model, "config", type(trainer.model.config)(**altered))
    with pytest.raises(TrainingError, match="CHECKPOINT_CONFIG_MISMATCH"):
        CheckpointManager.load(
            checkpoint,
            model=trainer.model,
            model_config=trainer.model.config,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            training_config=config,
            dataset_fingerprint=trainer.dataset_fingerprint,
            tokenizer_fingerprint=trainer.tokenizer_fingerprint,
            device=torch.device("cpu"),
        )


def test_resume_accumulation_policy_mismatch_is_blocked(tmp_path):
    _, _, checkpoint = prepare(tmp_path)
    changed = training_config(
        batch_size=2, micro_batch_size=1, gradient_accumulation_steps=2, max_steps=2, save_every=1
    )
    resumed, _ = build_tiny_trainer(checkpoint.parent, config=changed, resume=True)
    with pytest.raises(TrainingError, match="CHECKPOINT_CONFIG_MISMATCH"):
        resumed.resume_from(checkpoint)


def test_resume_allows_logging_and_output_policy_changes(tmp_path):
    _, _, checkpoint = prepare(tmp_path)
    changed = training_config(max_steps=2, save_every=2, log_every=2, output_dir="tests/output/other")
    resumed, _ = build_tiny_trainer(checkpoint.parent, config=changed, resume=True)
    state = resumed.resume_from(checkpoint)
    assert state.global_step == 1
