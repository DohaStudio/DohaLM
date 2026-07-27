"""Bounded pilot orchestration using DohaLMTiny, Trainer and CheckpointManager."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import hashlib
import math
import time

import torch

from src.data.checksums import checksum_value, file_checksum
from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny
from src.runtime.paths import repository_root, resolve_repository_path
from src.tokenizer import DohaTokenizer, validate_pilot_tokenizer
from src.tokenizer.operating import validate_operating_candidate

from .collator import CausalLMCollator
from .checkpoint import CheckpointManager
from .dataloader import create_dataloader
from .errors import TrainingError
from .pilot_config import PilotPretrainingConfig
from .pilot_metrics import write_pilot_json
from .trainer import Trainer, seed_everything
from .validation import ValidationResult, evaluate_language_model


def resolve_pilot_path(config: PilotPretrainingConfig, value: str) -> Path:
    if config.path_root == "repository":
        return resolve_repository_path(value)
    external_root, _ = resolve_local_paths(resolve_repository_path(config.local_dataset_config))
    resolved = (external_root / value).resolve()
    if external_root not in resolved.parents:
        raise TrainingError("PILOT_PATH_INVALID", "Pilot artifact 경로가 configured external root 밖입니다.")
    return resolved


def _resolve(config: PilotPretrainingConfig, value: str) -> Path:
    return resolve_pilot_path(config, value)


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
    tokenizer_manifest_path = files["tokenizer_model"].with_name("tokenizer-manifest.json")
    try:
        tokenizer_manifest = json.loads(tokenizer_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingError("PILOT_TOKENIZER_MISMATCH", "운영 tokenizer manifest를 읽을 수 없습니다.") from exc
    tokenizer_fingerprint = tokenizer_manifest.get("tokenizer_fingerprint")
    if tokenizer_manifest.get("model_checksum") != checksums["tokenizer_model"] or not isinstance(tokenizer_fingerprint, str):
        raise TrainingError("PILOT_TOKENIZER_MISMATCH", "운영 tokenizer model checksum 또는 fingerprint가 일치하지 않습니다.")
    return {
        "schema_version": "1.0",
        "checksums": checksums,
        "dataset_fingerprint": checksum_value({key: checksums[key] for key in ("train_dataset", "validation_dataset", "corpus_manifest", "split_manifest")}),
        "tokenizer_fingerprint": tokenizer_fingerprint,
        "tokenizer_model_checksum": checksums["tokenizer_model"],
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
    encoded_ids = json.dumps(generated_ids, separators=(",", ":")).encode("ascii")
    return {
        "prompt_token_count": len(ids),
        "generated_token_count": len(generated_ids) - len(ids),
        "token_ids_sha256": f"sha256:{hashlib.sha256(encoded_ids).hexdigest()}",
        "token_ids_stored": False,
        "decoded_sha256": f"sha256:{hashlib.sha256(tokenizer.decode(generated_ids, skip_special_tokens=True).encode('utf-8')).hexdigest()}",
        "decoded_text_stored": False,
    }


def _validate_runtime_tokenizer(model_path: Path) -> tuple[DohaTokenizer, dict[str, Any]]:
    if (model_path.parent / "tokenizer-manifest.json").is_file():
        report = validate_operating_candidate(model_path.parent)
        return DohaTokenizer(model_path), {**report, "operating_candidate": True, "approval_effect": "none"}
    return validate_pilot_tokenizer(model_path)


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
    if config.max_steps > 5:
        raise TrainingError("PILOT_SMOKE_SCOPE_EXCEEDED", "이 실행 경로는 최대 5 optimizer step Smoke만 허용합니다.")
    from .gate7_overfit import _process_memory

    run_started = time.perf_counter()
    resume = config.resume_checkpoint is not None
    trainer, _, validation_dataset, lineage = build_pilot_trainer(config, resume=resume)
    if resume:
        trainer.resume_from(_resolve(config, config.resume_checkpoint or ""))
    tokenizer, tokenizer_report = _validate_runtime_tokenizer(_resolve(config, config.tokenizer_model))
    if tokenizer.vocab_size != config.model.vocab_size:
        raise TrainingError("PILOT_TOKENIZER_MISMATCH", "tokenizer vocabulary가 model config와 일치하지 않습니다.")
    validation_loader = create_dataloader(
        validation_dataset,
        CausalLMCollator(context_length=config.model.context_length),
        config.to_training_config(),
        shuffle=False,
    )
    initial_validation = evaluate_language_model(
        trainer.model, validation_loader, device=trainer.device, use_amp=trainer.amp_enabled, max_batches=config.validation_max_batches
    )
    before = _generation(trainer.model, tokenizer, config.prompt, device=trainer.device, max_new_tokens=config.max_new_tokens)
    validation_history: list[dict[str, Any]] = [{"global_step": trainer.state.global_step, **initial_validation.to_dict()}]
    all_metrics: list[dict[str, Any]] = []
    checkpoints: list[str] = []
    while trainer.state.global_step < config.max_steps:
        target = min(config.max_steps, ((trainer.state.global_step // config.validation_every) + 1) * config.validation_every)
        result = trainer.train(target_steps=target)
        all_metrics.extend(metric.to_dict() for metric in result.metrics)
        checkpoints.extend(result.checkpoints)
        validation = evaluate_language_model(
            trainer.model, validation_loader, device=trainer.device, use_amp=trainer.amp_enabled, max_batches=config.validation_max_batches
        )
        validation_history.append({"global_step": trainer.state.global_step, **validation.to_dict()})
    after = _generation(trainer.model, tokenizer, config.prompt, device=trainer.device, max_new_tokens=config.max_new_tokens)
    checkpoint_sizes = {
        path.name: sum(item.stat().st_size for item in path.iterdir() if item.is_file())
        for path in sorted(trainer.output_root.glob("checkpoint-*"))
        if path.is_dir()
    }
    checkpoint_path = trainer.output_root / f"checkpoint-{trainer.state.global_step}"
    checkpoint_inspection = CheckpointManager.inspect(checkpoint_path).to_dict() if checkpoint_path.is_dir() else None
    metric_log = trainer.output_root / "pilot-training-metrics.jsonl"
    finite = all(math.isfinite(item["loss"]) for item in all_metrics)
    process_memory = _process_memory()
    elapsed = time.perf_counter() - run_started
    summary = {
        "status": "completed_resource_smoke",
        "global_step": trainer.state.global_step,
        "training_metrics": all_metrics,
        "validation": validation_history,
        "generation_before": before,
        "generation_after": after,
        "checkpoints": checkpoints,
        "checkpoint_sizes_bytes": checkpoint_sizes,
        "checkpoint": checkpoint_inspection,
        "checkpoint_save_seconds": trainer.checkpoints.last_save_seconds,
        "metric_log_bytes": metric_log.stat().st_size if metric_log.is_file() else 0,
        "elapsed_seconds": elapsed,
        "mean_tokens_per_second": sum(item["tokens_per_second"] for item in all_metrics) / len(all_metrics),
        "mean_optimizer_step_seconds": sum(item["step_time"] for item in all_metrics) / len(all_metrics),
        "peak_vram_allocated_bytes": max(item["peak_memory_allocated"] for item in all_metrics),
        "peak_vram_reserved_bytes": max(item["peak_memory_reserved"] for item in all_metrics),
        "peak_cpu_working_set_bytes": process_memory.get("peak_working_set_bytes"),
        "cpu_memory_source": process_memory.get("source"),
        "amp_skip_count": sum(bool(item.get("amp_step_skipped")) for item in all_metrics),
        "nonfinite_metric_count": 0 if finite else 1,
        "disk_usage_bytes": sum(path.stat().st_size for path in trainer.output_root.rglob("*") if path.is_file()),
        "lineage": lineage,
        "tokenizer_compatibility": tokenizer_report,
        "effective_batch_size": config.effective_batch_size,
        "gate_effect": "none",
        "approval_effect": "none",
        "pilot_100_step_execution_allowed": False,
    }
    write_pilot_json(trainer.output_root / "pilot-run-summary.json", summary)
    resolved_config = config.to_dict()
    resolved_config["prompt_sha256"] = f"sha256:{hashlib.sha256(config.prompt.encode('utf-8')).hexdigest()}"
    resolved_config["prompt_text_stored"] = False
    resolved_config.pop("prompt", None)
    write_pilot_json(trainer.output_root / "pilot-config-resolved.json", resolved_config)
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
    tokenizer, _ = _validate_runtime_tokenizer(_resolve(resumed, resumed.tokenizer_model))
    return _generation(trainer.model, tokenizer, prompt, device=trainer.device, max_new_tokens=resumed.max_new_tokens)
