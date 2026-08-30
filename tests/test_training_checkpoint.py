from __future__ import annotations

import json
import os
import random

import pytest
import torch
from _training_helpers import build_tiny_trainer, training_config

from src.data.checksums import file_checksum
from src.training import (
    CheckpointManager,
    TrainingError,
    capture_rng_state,
    restore_rng_state,
)


def saved_checkpoint(tmp_path, *, maximum=2):
    config = training_config(max_steps=maximum, save_every=1)
    trainer, _ = build_tiny_trainer(tmp_path / "run", config=config)
    trainer.train(target_steps=1)
    return trainer, tmp_path / "run" / "checkpoint-1"


def test_checkpoint_contains_exact_required_files(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    assert {path.name for path in checkpoint.iterdir()} == {
        "model.pt", "optimizer.pt", "scheduler.pt", "scaler.pt",
        "training-state.json", "config.json", "manifest.json", "checksums.json",
    }


def test_checkpoint_checksums_cover_every_content_file(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    checksums = json.loads((checkpoint / "checksums.json").read_text())
    assert len(checksums["files"]) == 7
    assert all(checksums["files"][name] == file_checksum(checkpoint / name) for name in checksums["files"])


def test_checkpoint_inspection_exposes_no_absolute_path(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    report = CheckpointManager.inspect(checkpoint).to_dict()
    assert report["path_name"] == "checkpoint-1"
    assert str(tmp_path) not in json.dumps(report)
    for name in ("training-state.json", "config.json", "manifest.json", "checksums.json"):
        assert str(tmp_path) not in (checkpoint / name).read_text(encoding="utf-8")


def test_quarantined_checkpoint_cannot_be_inspected_or_loaded(tmp_path):
    trainer, checkpoint = saved_checkpoint(tmp_path)
    (checkpoint.parent / "quarantine-policy.json").write_text(
        json.dumps({"status": "quarantined", "not_for_resume": True}),
        encoding="utf-8",
    )
    with pytest.raises(TrainingError, match="CHECKPOINT_QUARANTINED"):
        CheckpointManager.inspect(checkpoint)
    with pytest.raises(TrainingError, match="CHECKPOINT_QUARANTINED"):
        trainer.resume_from(checkpoint, restore_rng=False)


def test_existing_checkpoint_is_never_overwritten(tmp_path):
    trainer, checkpoint = saved_checkpoint(tmp_path)
    before = {path.name: file_checksum(path) for path in checkpoint.iterdir()}
    with pytest.raises(TrainingError, match="CHECKPOINT_ALREADY_EXISTS"):
        trainer.checkpoints.save(
            model=trainer.model,
            model_config=trainer.model.config,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            training_config=trainer.config,
            state=trainer.state,
        )
    assert before == {path.name: file_checksum(path) for path in checkpoint.iterdir()}


def test_checksum_corruption_is_rejected(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    with (checkpoint / "model.pt").open("ab") as handle:
        handle.write(b"corrupt")
    with pytest.raises(TrainingError, match="CHECKPOINT_CHECKSUM_MISMATCH"):
        CheckpointManager.inspect(checkpoint)


def test_missing_file_is_rejected(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    (checkpoint / "scaler.pt").unlink()
    with pytest.raises(TrainingError, match="RESUME_STATE_MISMATCH"):
        CheckpointManager.inspect(checkpoint)


def test_manifest_records_lineage_fingerprints(tmp_path):
    trainer, checkpoint = saved_checkpoint(tmp_path)
    manifest = json.loads((checkpoint / "manifest.json").read_text())
    assert manifest["dataset_fingerprint"] == trainer.dataset_fingerprint
    assert manifest["tokenizer_fingerprint"] == trainer.tokenizer_fingerprint
    assert manifest["model_config_fingerprint"] == trainer.state.model_config_fingerprint


def test_resume_rejects_dataset_lineage_metadata_change(tmp_path):
    config = training_config(max_steps=2, save_every=1)
    trainer, _ = build_tiny_trainer(tmp_path / "run", config=config)
    trainer.train(target_steps=1)
    resumed, _ = build_tiny_trainer(tmp_path / "run", config=config, resume=True)
    resumed.dataset_metadata = {"kind": "changed-lineage"}
    with pytest.raises(TrainingError, match="CHECKPOINT_DATASET_MISMATCH"):
        resumed.resume_from(tmp_path / "run" / "checkpoint-1", restore_rng=False)


def test_rng_state_round_trip_cpu_and_python():
    random.seed(99); torch.manual_seed(99)
    state = capture_rng_state()
    expected = (random.random(), torch.rand(3))
    random.random(); torch.rand(3)
    restore_rng_state(state)
    actual = (random.random(), torch.rand(3))
    assert actual[0] == expected[0]
    assert torch.equal(actual[1], expected[1])


def test_checkpoint_staging_is_removed_after_publish(tmp_path):
    _, checkpoint = saved_checkpoint(tmp_path)
    assert checkpoint.is_dir()
    assert not list(checkpoint.parent.glob(".checkpoint-*.staging-*"))


def test_atomic_publish_failure_leaves_no_final_or_staging(tmp_path, monkeypatch):
    config = training_config(max_steps=2, save_every=2)
    trainer, _ = build_tiny_trainer(tmp_path / "run", config=config)
    trainer.train(target_steps=1)

    def fail_replace(source, target):
        raise OSError("injected publish failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(TrainingError):
        trainer.checkpoints.save(
            model=trainer.model,
            model_config=trainer.model.config,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            training_config=trainer.config,
            state=trainer.state,
        )
    assert not (tmp_path / "run" / "checkpoint-1").exists()
    assert not list((tmp_path / "run").glob(".checkpoint-*.staging-*"))
