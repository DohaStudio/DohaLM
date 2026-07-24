"""Bounded pilot orchestration using DohaLMTiny, Trainer and CheckpointManager."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from src.data.checksums import checksum_value, file_checksum
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny
from src.runtime.paths import repository_root, resolve_repository_path
from src.tokenizer import DohaTokenizer, validate_pilot_tokenizer

from .collator import CausalLMCollator
from .dataloader import create_dataloader
from .errors import TrainingError
from .pilot_config import PilotPretrainingConfig
from .pilot_metrics import write_pilot_json
from .trainer import Trainer, seed_everything
from .validation import ValidationResult, evaluate_language_model


def _resolve(config: PilotPretrainingConfig, value: str) -> Path:
    return resolve_repository_path(value)


def _lineage(config: PilotPretrainingConfig) -> dict[str, Any]:
    files = {
        "train_dataset": _resolve(config, config.train_dataset),
        "validation_dataset": _resolve(config, config.validation_dataset),
        "tokenizer_model": _resolve(config, config.tokenizer_model),
        "corpus_manifest": _resolve(config, config.corpus_manifest),
        "split_manifest": _resolve(config, config.split_manifest),
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise TrainingError("PILOT_ARTIFACT_MISSING", f"필수 pilot artifact가 없습니다: {missing}")
    checksums = {name: file_checksum(path) for name, path in files.items()}
    return {
        "schema_version": "1.0",
        "checksums": checksums,
        "dataset_fingerprint": checksum_value({key: checksums[key] for key in ("train_dataset", "validation_dataset", "corpus_manifest", "split_manifest")}),
        "tokenizer_fingerprint": checksums["tokenizer_model"],
        "local_experiment_only": True,
        "publish_allowed": False,
        "redistribution_allowed": False,
        "model_release_allowed": False,
    }


def _generation(model: DohaLMTiny, tokenizer: DohaTokenizer, prompt: str, *, device: torch.device, max_new_tokens: int) -> dict[str, Any]:
    encoded = tokenizer.encode(prompt)
    ids = encoded.ids[: max(1, model.config.context_length - max_new_tokens)]
    input_ids = torch.tensor([ids], dtype=torch.long, device=device)
    output = model.generate(input_ids, max_new_tokens=max_new_tokens, eos_token_id=3)
    generated_ids = output[0].detach().cpu().tolist()
    return {
        "prompt_token_count": len(ids),
        "generated_token_count": len(generated_ids) - len(ids),
        "token_ids": generated_ids,
        "decoded": tokenizer.decode(generated_ids, skip_special_tokens=True),
    }


def build_pilot_trainer(config: PilotPretrainingConfig, *, resume: bool = False) -> tuple[Trainer, TokenizedJsonlDataset, TokenizedJsonlDataset, dict[str, Any]]:
    training = config.to_training_config()
    seed_everything(training.seed)
    lineage = _lineage(config)
    train_dataset = TokenizedJsonlDataset(_resolve(config, config.train_dataset), context_length=config.model.context_length, vocab_size=config.model.vocab_size)
    validation_dataset = TokenizedJsonlDataset(_resolve(config, config.validation_dataset), context_length=config.model.context_length, vocab_size=config.model.vocab_size)
    collator = CausalLMCollator(context_length=config.model.context_length)
    train_loader = create_dataloader(train_dataset, collator, training, shuffle=True, stateful=True, dataset_fingerprint=lineage["dataset_fingerprint"])
    model = DohaLMTiny(config.model)
    output_root = _resolve(config, config.output_dir)
    trainer = Trainer(
        model=model,
        dataloader=train_loader,
        config=training,
        dataset_fingerprint=lineage["dataset_fingerprint"],
        tokenizer_fingerprint=lineage["tokenizer_fingerprint"],
        output_root=output_root,
        dataset_metadata={"kind": "local-pilot-tokenized-v1", **lineage},
        resume=resume,
        metric_filename="pilot-training-metrics.jsonl",
    )
    return trainer, train_dataset, validation_dataset, lineage


def run_pilot_pretraining(config: PilotPretrainingConfig) -> dict[str, Any]:
    resume = config.resume_checkpoint is not None
    trainer, _, validation_dataset, lineage = build_pilot_trainer(config, resume=resume)
    if resume:
        trainer.resume_from(_resolve(config, config.resume_checkpoint or ""))
    tokenizer, tokenizer_report = validate_pilot_tokenizer(_resolve(config, config.tokenizer_model))
    if tokenizer.vocab_size != config.model.vocab_size:
        raise TrainingError("PILOT_TOKENIZER_MISMATCH", "tokenizer vocabulary가 model config와 일치하지 않습니다.")
    validation_loader = create_dataloader(
        validation_dataset,
        CausalLMCollator(context_length=config.model.context_length),
        config.to_training_config(),
        shuffle=False,
    )
    initial_validation = evaluate_language_model(trainer.model, validation_loader, device=trainer.device, use_amp=trainer.amp_enabled)
    before = _generation(trainer.model, tokenizer, config.prompt, device=trainer.device, max_new_tokens=config.max_new_tokens)
    validation_history: list[dict[str, Any]] = [{"global_step": trainer.state.global_step, **initial_validation.to_dict()}]
    all_metrics: list[dict[str, Any]] = []
    checkpoints: list[str] = []
    while trainer.state.global_step < config.max_steps:
        target = min(config.max_steps, ((trainer.state.global_step // config.validation_every) + 1) * config.validation_every)
        result = trainer.train(target_steps=target)
        all_metrics.extend(metric.to_dict() for metric in result.metrics)
        checkpoints.extend(result.checkpoints)
        validation = evaluate_language_model(trainer.model, validation_loader, device=trainer.device, use_amp=trainer.amp_enabled)
        validation_history.append({"global_step": trainer.state.global_step, **validation.to_dict()})
    after = _generation(trainer.model, tokenizer, config.prompt, device=trainer.device, max_new_tokens=config.max_new_tokens)
    checkpoint_sizes = {
        path.name: sum(item.stat().st_size for item in path.iterdir() if item.is_file())
        for path in sorted(trainer.output_root.glob("checkpoint-*"))
        if path.is_dir()
    }
    summary = {
        "status": "completed_local_pilot",
        "global_step": trainer.state.global_step,
        "training_metrics": all_metrics,
        "validation": validation_history,
        "generation_before": before,
        "generation_after": after,
        "checkpoints": checkpoints,
        "checkpoint_sizes_bytes": checkpoint_sizes,
        "lineage": lineage,
        "tokenizer_compatibility": tokenizer_report,
        "effective_batch_size": config.effective_batch_size,
        "gate_effect": "none",
        "approval_effect": "none",
    }
    write_pilot_json(trainer.output_root / "pilot-run-summary.json", summary)
    write_pilot_json(trainer.output_root / "pilot-config-resolved.json", config.to_dict())
    return summary


def evaluate_pilot_checkpoint(config: PilotPretrainingConfig, checkpoint: str) -> ValidationResult:
    resumed = PilotPretrainingConfig(**{**config.__dict__, "resume_checkpoint": checkpoint})
    trainer, _, validation_dataset, _ = build_pilot_trainer(resumed, resume=True)
    trainer.resume_from(_resolve(resumed, checkpoint), restore_rng=False)
    loader = create_dataloader(validation_dataset, CausalLMCollator(context_length=config.model.context_length), config.to_training_config(), shuffle=False)
    return evaluate_language_model(trainer.model, loader, device=trainer.device, use_amp=trainer.amp_enabled)


def generate_from_pilot_checkpoint(config: PilotPretrainingConfig, checkpoint: str, prompt: str) -> dict[str, Any]:
    resumed = PilotPretrainingConfig(**{**config.__dict__, "resume_checkpoint": checkpoint, "prompt": prompt})
    trainer, _, _, _ = build_pilot_trainer(resumed, resume=True)
    trainer.resume_from(_resolve(resumed, checkpoint), restore_rng=False)
    tokenizer, _ = validate_pilot_tokenizer(_resolve(resumed, resumed.tokenizer_model))
    return _generation(trainer.model, tokenizer, prompt, device=trainer.device, max_new_tokens=resumed.max_new_tokens)
