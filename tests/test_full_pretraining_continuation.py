from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from src.data.checksums import checksum_value
from src.model import DohaLMTiny, ModelConfig
from src.training.collator import CausalLMCollator
from src.training.config import TrainingConfig
from src.training.dataloader import create_dataloader
from src.training.errors import TrainingError
from src.training.full_pretraining import (
    ONE_EPOCH_OPTIMIZER_STEPS,
    FullPretrainingConfig,
)
from src.training.full_pretraining_backend import candidate_a_execution_plan
from src.training.production_host_foundation import ProductionTrainingHostIntent
from src.training.scheduler import CosineWarmupDecayScheduler
from src.training.dataset import SyntheticTokenDataset
from src.training.trainer import Trainer, seed_everything


def continuation_config() -> FullPretrainingConfig:
    return FullPretrainingConfig.from_yaml(
        "configs/full-pretraining-continuation.example.yaml"
    )


def _tiny_training_config(**changes) -> TrainingConfig:
    values = {
        "batch_size": 2,
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 1,
        "max_steps": 2,
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


def _tiny_trainer(output_root, *, config: TrainingConfig, resume: bool = False):
    seed_everything(config.seed)
    model = DohaLMTiny(
        ModelConfig(
            vocab_size=32,
            context_length=8,
            num_layers=1,
            hidden_size=16,
            num_heads=4,
            head_dim=4,
            ffn_size=32,
            dropout=0.0,
        )
    )
    dataset = SyntheticTokenDataset(
        vocab_size=32,
        sequence_length=5,
        num_records=8,
        seed=23,
        pattern=[2, 10, 11, 12, 3],
    )
    loader = create_dataloader(
        dataset, CausalLMCollator(context_length=8), config, shuffle=True
    )
    return Trainer(
        model=model,
        dataloader=loader,
        config=config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=checksum_value({"kind": "synthetic", "vocab": 32}),
        output_root=output_root,
        dataset_metadata={"kind": "test-synthetic"},
        resume=resume,
    )


def test_exact_continuation_profile_and_plan() -> None:
    config = continuation_config()
    plan = candidate_a_execution_plan(config)

    assert config.is_continuation is True
    assert plan["optimizer_step_limit"] == 34_817
    assert plan["checkpoint_steps"] == [19_850, 34_817]
    assert plan["evaluation_steps"] == [4_883, 34_817]
    assert plan["resume_requested"] is True


def test_continuation_profile_rejects_source_or_automatic_resume_drift() -> None:
    config = continuation_config()
    with pytest.raises(
        TrainingError, match="FULL_PRETRAINING_CONTINUATION_PROFILE_MISMATCH"
    ):
        replace(
            config,
            continuation={**config.continuation, "automatic_resume": True},
        )


def test_cosine_horizon_extension_preserves_global_step_without_warmup_restart() -> (
    None
):
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.AdamW([parameter], lr=3e-4)
    scheduler = CosineWarmupDecayScheduler(
        optimizer,
        warmup_steps=10,
        max_steps=ONE_EPOCH_OPTIMIZER_STEPS,
        min_lr_ratio=0.1,
    )
    source = {
        "scheduler_type": "cosine",
        "current_step": 4_883,
        "warmup_steps": 10,
        "max_steps": 4_883,
        "base_lrs": [3e-4],
        "min_lr_ratio": 0.1,
    }

    scheduler.load_state_dict_for_horizon_extension(source, expected_source_step=4_883)
    expected = 3e-4 * scheduler.factor(4_883)
    assert scheduler.current_step == 4_883
    assert scheduler.get_last_lr()[0] == pytest.approx(expected)
    assert scheduler.get_last_lr()[0] > 3e-5
    scheduler.step()
    assert scheduler.current_step == 4_884
    assert scheduler.get_last_lr()[0] == pytest.approx(3e-4 * scheduler.factor(4_884))


def test_cosine_horizon_extension_rejects_non_terminal_source() -> None:
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.AdamW([parameter], lr=3e-4)
    scheduler = CosineWarmupDecayScheduler(
        optimizer,
        warmup_steps=10,
        max_steps=ONE_EPOCH_OPTIMIZER_STEPS,
        min_lr_ratio=0.1,
    )
    with pytest.raises(TrainingError, match="RESUME_STATE_MISMATCH"):
        scheduler.load_state_dict_for_horizon_extension(
            {
                "scheduler_type": "cosine",
                "current_step": 4_883,
                "warmup_steps": 10,
                "max_steps": 10_000,
                "base_lrs": [3e-4],
                "min_lr_ratio": 0.1,
            },
            expected_source_step=4_883,
        )


def test_host_intent_allows_only_fresh_or_exact_continuation_mode() -> None:
    values = {
        "action": "full_pretraining",
        "execution_mode": "r3_one_epoch_continuation",
        "dataset_version_reference": "dataset-version:authority",
        "dataset_manifest_reference": "dataset-manifest:authority",
        "expected_dataset_pair_fingerprint": "sha256:" + "1" * 64,
        "training_config_reference": "config:authority",
        "expected_config_fingerprint": "sha256:" + "2" * 64,
        "readiness_evidence_reference": "readiness:authority",
        "expected_readiness_fingerprint": "sha256:" + "3" * 64,
        "run_id": "run-aihub-71748-local-v1-r4",
        "output_logical_root": (
            ".dohalm-local/training-output/run-aihub-71748-local-v1-r4"
        ),
        "decision_evidence_reference": "decision:authority",
    }
    assert (
        ProductionTrainingHostIntent(**values).execution_mode
        == values["execution_mode"]
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_INTENT_INVALID"):
        ProductionTrainingHostIntent(**{**values, "execution_mode": "resume"})


def test_checkpoint_continuation_restores_state_and_extends_only_horizon(
    tmp_path,
) -> None:
    source_config = _tiny_training_config(
        max_steps=1,
        save_every=1,
        scheduler_type="cosine",
        min_lr_ratio=0.1,
    )
    source = _tiny_trainer(tmp_path / "run", config=source_config)
    source.train(target_steps=1)
    target_config = replace(source_config, max_steps=3, save_every=3)
    resumed = _tiny_trainer(tmp_path / "run", config=target_config, resume=True)

    state = resumed.resume_from(
        tmp_path / "run" / "checkpoint-1",
        restore_rng=False,
        allow_scheduler_horizon_extension=True,
        expected_source_step=1,
    )

    assert state.global_step == 1
    assert state.optimizer_step == 1
    assert resumed.scheduler.current_step == 1
    assert resumed.scheduler.max_steps == 3
    assert resumed.train(target_steps=2).state.global_step == 2
