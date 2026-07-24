"""Shared helpers for bounded synthetic training commands."""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

from src.data.checksums import checksum_value
from src.model import DohaLMTiny, ModelConfig
from src.runtime.paths import resolve_repository_path
from src.training import (
    CausalLMCollator,
    SyntheticTokenDataset,
    Trainer,
    TrainingConfig,
    TrainingError,
    create_dataloader,
    seed_everything,
)


def print_result(value: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        return
    for key, item in value.items():
        print(f"{key}: {item}")


def cli_error(exc: Exception) -> int:
    print(f"오류: {exc}", file=sys.stderr)
    return 2


def small_model_config(*, context_length: int = 32) -> ModelConfig:
    return ModelConfig(
        vocab_size=128,
        context_length=context_length,
        num_layers=2,
        hidden_size=32,
        num_heads=4,
        head_dim=8,
        ffn_size=64,
        dropout=0.0,
        layer_norm_eps=1e-5,
    )


def repeated_pattern(sequence_length: int, vocab_size: int) -> list[int]:
    return [2, *[8 + (index % (vocab_size - 8)) for index in range(sequence_length - 2)], 3]


def dataset_metadata(*, sequence_length: int, num_records: int, seed: int, vocab_size: int) -> dict[str, Any]:
    return {
        "kind": "synthetic-repeated-pattern-v1",
        "sequence_length": sequence_length,
        "num_records": num_records,
        "seed": seed,
        "vocab_size": vocab_size,
    }


def synthetic_tokenizer_fingerprint(vocab_size: int) -> str:
    return checksum_value({"kind": "synthetic-tokenizer-v1", "vocab_size": vocab_size})


def make_dataset(metadata: dict[str, Any]) -> SyntheticTokenDataset:
    return SyntheticTokenDataset(
        vocab_size=int(metadata["vocab_size"]),
        sequence_length=int(metadata["sequence_length"]),
        num_records=int(metadata["num_records"]),
        seed=int(metadata["seed"]),
        pattern=repeated_pattern(int(metadata["sequence_length"]), int(metadata["vocab_size"])),
    )


def config_from_document(value: dict[str, Any]) -> TrainingConfig:
    allowed = {field.name for field in fields(TrainingConfig)}
    cleaned = {key: item for key, item in value.items() if key in allowed}
    if "betas" in cleaned:
        cleaned["betas"] = tuple(cleaned["betas"])
    return TrainingConfig(**cleaned)


def build_trainer(
    *,
    model_config: ModelConfig,
    training_config: TrainingConfig,
    metadata: dict[str, Any],
    output_root: Path | None = None,
    resume: bool = False,
) -> tuple[Trainer, SyntheticTokenDataset]:
    seed_everything(training_config.seed)
    dataset = make_dataset(metadata)
    collator = CausalLMCollator(context_length=model_config.context_length)
    loader = create_dataloader(dataset, collator, training_config, shuffle=True)
    model = DohaLMTiny(model_config)
    logical_output = resolve_repository_path(training_config.output_dir) if output_root is None else output_root
    trainer = Trainer(
        model=model,
        dataloader=loader,
        config=training_config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=synthetic_tokenizer_fingerprint(model_config.vocab_size),
        output_root=logical_output,
        dataset_metadata=metadata,
        resume=resume,
    )
    return trainer, dataset
