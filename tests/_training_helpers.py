from __future__ import annotations

from pathlib import Path

from src.data.checksums import checksum_value
from src.model import DohaLMTiny, ModelConfig
from src.training import (
    CausalLMCollator,
    SyntheticTokenDataset,
    Trainer,
    TrainingConfig,
    create_dataloader,
    seed_everything,
)


def tiny_model_config() -> ModelConfig:
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


def training_config(**changes) -> TrainingConfig:
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


def repeated_dataset(*, records: int = 8) -> SyntheticTokenDataset:
    return SyntheticTokenDataset(
        vocab_size=32,
        sequence_length=5,
        num_records=records,
        seed=23,
        pattern=[2, 10, 11, 12, 3],
    )


def build_tiny_trainer(
    output_root: Path,
    *,
    config: TrainingConfig | None = None,
    state=None,
    resume: bool = False,
) -> tuple[Trainer, SyntheticTokenDataset]:
    actual_config = config or training_config()
    seed_everything(actual_config.seed)
    model_config = tiny_model_config()
    model = DohaLMTiny(model_config)
    dataset = repeated_dataset()
    loader = create_dataloader(dataset, CausalLMCollator(context_length=8), actual_config, shuffle=True)
    trainer = Trainer(
        model=model,
        dataloader=loader,
        config=actual_config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=checksum_value({"kind": "synthetic", "vocab": 32}),
        output_root=output_root,
        dataset_metadata={"kind": "test-synthetic"},
        state=state,
        resume=resume,
    )
    return trainer, dataset
