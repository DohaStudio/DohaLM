"""Bounded pilot orchestration using DohaLMTiny, Trainer and CheckpointManager."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import hashlib
import json
import math
import shutil
import time
from typing import Any

import torch

from src.data.checksums import checksum_value, file_checksum
from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny
from src.runtime.paths import repository_root, resolve_repository_path
from src.runtime.environment import collect_environment
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
    raw = str(value)
    windows = PureWindowsPath(raw.replace("/", "\\"))
    posix = PurePosixPath(raw.replace("\\", "/"))
    if windows.is_absolute() or posix.is_absolute() or ".." in windows.parts or ".." in posix.parts:
        raise TrainingError(
            "PILOT_PATH_INVALID",
            "Pilot artifact 경로는 configured external root 상대경로여야 합니다.",
        )
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
    lineage = {
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
    prepared_root = files["corpus_manifest"].parent
    metadata_paths = {
        "source_lineage_manifest": prepared_root / "source-lineage.manifest.json",
        "tokenization_manifest": prepared_root / "tokenization-manifest.json",
        "packing_manifest": prepared_root / "packing-manifest.json",
        "pii_manifest": prepared_root / "pii-review.manifest.json",
        "fingerprints": prepared_root / "fingerprints.json",
    }
    if not all(path.is_file() for path in metadata_paths.values()):
        return lineage
    try:
        dataset = json.loads(files["corpus_manifest"].read_text(encoding="utf-8"))
        split = json.loads(files["split_manifest"].read_text(encoding="utf-8"))
        source = json.loads(metadata_paths["source_lineage_manifest"].read_text(encoding="utf-8"))
        tokenization = json.loads(metadata_paths["tokenization_manifest"].read_text(encoding="utf-8"))
        packing = json.loads(metadata_paths["packing_manifest"].read_text(encoding="utf-8"))
        pii = json.loads(metadata_paths["pii_manifest"].read_text(encoding="utf-8"))
        fingerprints = json.loads(metadata_paths["fingerprints"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingError("PILOT_LINEAGE_MISMATCH", "Pilot lineage metadata를 읽을 수 없습니다.") from exc
    audit_contract = {
        "contract_version": "aihub-71748-training-selection-v1",
        "archive_order": "relative_path_ascending",
        "entry_order": "json_filename_ascending",
        "quota_exception_policy": "stop_current_archive",
        "normalization": "NFC_LF_trailing_horizontal_whitespace_removed",
        "deduplication": "global_first_normalized_utf8_sha256_kept",
    }
    tokenizer_vocab = files["tokenizer_model"].with_name("tokenizer.vocab")
    expected = {
        "dataset_id": "AIHUB-71748",
        "dataset_version": "pilot-v2",
        "source_split": "Training",
        "text_field": "data_info[].contents",
        "pilot_dataset_fingerprint": fingerprints.get("dataset"),
        "split_fingerprint": fingerprints.get("split"),
        "pii_fingerprint": fingerprints.get("pii"),
        "source_lineage_verified": True,
        "tokenizer_fingerprint": tokenizer_fingerprint,
    }
    if (
        dataset.get("dataset_id") != expected["dataset_id"]
        or dataset.get("dataset_version") != expected["dataset_version"]
        or dataset.get("source_split") != expected["source_split"]
        or dataset.get("text_field") != expected["text_field"]
        or dataset.get("dataset_fingerprint") != expected["pilot_dataset_fingerprint"]
        or dataset.get("split_fingerprint") != expected["split_fingerprint"]
        or dataset.get("pii_result_fingerprint") != expected["pii_fingerprint"]
        or dataset.get("source_lineage_verified") is not True
        or dataset.get("tokenizer_fingerprint") != tokenizer_fingerprint
        or split.get("split_fingerprint") != expected["split_fingerprint"]
        or split.get("original_validation_used") is not False
        or split.get("exact_duplicate_cross_split") != 0
        or split.get("source_id_cross_split") != 0
        or tokenization.get("unknown_tokens") != 0
        or tokenization.get("out_of_range_ids") != 0
        or tokenization.get("empty_sequences") != 0
        or tokenization.get("split_mixing") is not False
        or tokenization.get("vocab_size") != 16_000
        or tokenization.get("special_token_ids") != list(range(8))
        or packing.get("split_mixing") is not False
        or pii.get("result_fingerprint") != expected["pii_fingerprint"]
        or source.get("status") != "verified"
        or source.get("source_record_count") != 107_226
        or source.get("selection_contract", {}).get("version") != audit_contract["contract_version"]
        or source.get("selection_contract_fingerprint") != checksum_value(source.get("selection_contract"))
        or not tokenizer_vocab.is_file()
    ):
        raise TrainingError("PILOT_LINEAGE_MISMATCH", "Pilot dataset·split·PII·tokenization·packing·source identity가 일치하지 않습니다.")
    lineage.update({
        **expected,
        "training_lineage_fingerprint": lineage["dataset_fingerprint"],
        "canonical_selection_contract": audit_contract["contract_version"],
        "canonical_contract_fingerprint": checksum_value(audit_contract),
        "prepared_selection_contract_fingerprint": source["selection_contract_fingerprint"],
        "source_lineage_fingerprint": file_checksum(metadata_paths["source_lineage_manifest"]),
        "source_corpus_fingerprint": source["source_corpus_fingerprint"],
        "source_corpus_sha256": source["source_corpus_sha256"],
        "source_record_count": source["source_record_count"],
        "tokenization_fingerprint": file_checksum(metadata_paths["tokenization_manifest"]),
        "packing_fingerprint": file_checksum(metadata_paths["packing_manifest"]),
        "tokenizer_vocab_checksum": file_checksum(tokenizer_vocab),
        "train_records": dataset["statistics"]["train"]["records"],
        "evaluation_records": dataset["statistics"]["evaluation"]["records"],
        "original_validation_used": False,
    })
    return lineage


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
    if config.max_steps > 5 and config.max_steps != 100:
        raise TrainingError("PILOT_SCOPE_EXCEEDED", "Pilot 실행은 최대 5-step Smoke 또는 정확히 100-step 승인 실행만 허용합니다.")
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
    checkpoint_save_seconds: dict[str, float | None] = {}
    while trainer.state.global_step < config.max_steps:
        target = min(config.max_steps, ((trainer.state.global_step // config.validation_every) + 1) * config.validation_every)
        result = trainer.train(target_steps=target)
        all_metrics.extend(metric.to_dict() for metric in result.metrics)
        checkpoints.extend(result.checkpoints)
        for checkpoint in result.checkpoints:
            checkpoint_save_seconds[checkpoint] = trainer.checkpoints.last_save_seconds
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
    if config.max_steps == 100 and checkpoints != ["checkpoint-25", "checkpoint-50", "checkpoint-75", "checkpoint-100"]:
        raise TrainingError("PILOT_CHECKPOINT_POLICY_MISMATCH", "100-step Pilot checkpoint 집합이 승인 정책과 일치하지 않습니다.")
    checkpoint_path = trainer.output_root / f"checkpoint-{trainer.state.global_step}"
    checkpoint_inspection = CheckpointManager.inspect(checkpoint_path).to_dict() if checkpoint_path.is_dir() else None
    metric_log = trainer.output_root / "pilot-training-metrics.jsonl"
    finite = all(math.isfinite(item["loss"]) for item in all_metrics)
    process_memory = _process_memory()
    elapsed = time.perf_counter() - run_started
    summary = {
        "status": "completed_pilot_100_steps" if config.max_steps == 100 else "completed_resource_smoke",
        "global_step": trainer.state.global_step,
        "training_metrics": all_metrics,
        "validation": validation_history,
        "generation_before": before,
        "generation_after": after,
        "checkpoints": checkpoints,
        "checkpoint_sizes_bytes": checkpoint_sizes,
        "checkpoint": checkpoint_inspection,
        "checkpoint_save_seconds": trainer.checkpoints.last_save_seconds,
        "checkpoint_save_seconds_by_name": checkpoint_save_seconds,
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
        "pilot_100_step_execution_allowed": config.max_steps == 100,
        "full_pretraining_allowed": False,
        "automatic_extension_allowed": False,
    }
    resolved_config = config.to_dict()
    resolved_config["prompt_sha256"] = f"sha256:{hashlib.sha256(config.prompt.encode('utf-8')).hexdigest()}"
    resolved_config["prompt_text_stored"] = False
    resolved_config.pop("prompt", None)
    write_pilot_json(trainer.output_root / "pilot-config-resolved.json", resolved_config)
    write_pilot_json(trainer.output_root / "pilot-environment-manifest.json", collect_environment(repository_root()))
    write_pilot_json(trainer.output_root / "pilot-dataset-reference-manifest.json", lineage)
    write_pilot_json(trainer.output_root / "pilot-evaluation-metrics.json", {"schema_version": "1.0", "evaluations": validation_history})
    write_pilot_json(trainer.output_root / "pilot-resource-report.json", {
        "schema_version": "1.0",
        "elapsed_seconds": elapsed,
        "mean_tokens_per_second": summary["mean_tokens_per_second"],
        "mean_optimizer_step_seconds": summary["mean_optimizer_step_seconds"],
        "peak_vram_allocated_bytes": summary["peak_vram_allocated_bytes"],
        "peak_vram_reserved_bytes": summary["peak_vram_reserved_bytes"],
        "peak_cpu_working_set_bytes": summary["peak_cpu_working_set_bytes"],
        "remaining_disk_bytes": shutil.disk_usage(trainer.output_root).free,
    })
    checkpoint_checksums = {
        name: {
            "bundle_bytes": checkpoint_sizes[name],
            "checksums_manifest_sha256": file_checksum(trainer.output_root / name / "checksums.json"),
        }
        for name in checkpoints
    }
    write_pilot_json(trainer.output_root / "pilot-checkpoint-checksum-manifest.json", {
        "schema_version": "1.0", "checkpoints": checkpoint_checksums,
    })
    write_pilot_json(trainer.output_root / "pilot-execution-manifest.json", {
        "schema_version": "1.0", "run_id": trainer.output_root.name,
        "status": summary["status"], "global_step": trainer.state.global_step,
        "dataset_fingerprint": lineage["dataset_fingerprint"],
        "tokenizer_fingerprint": lineage["tokenizer_fingerprint"],
        "training_config_fingerprint": config.to_training_config().fingerprint(),
        "model_fingerprint": checksum_value(config.model.to_dict()),
        "full_pretraining_allowed": False, "automatic_extension_allowed": False,
        "actual_text_values_stored": False,
    })
    write_pilot_json(trainer.output_root / "pilot-completion-report.json", {
        "schema_version": "1.0", "status": "completed",
        "global_step": trainer.state.global_step, "checkpoint_count": len(checkpoints),
        "nonfinite_metric_count": summary["nonfinite_metric_count"],
        "amp_skip_count": summary["amp_skip_count"], "oom_count": 0,
        "full_pretraining_effect": "none", "gate_effect": "none",
    })
    write_pilot_json(trainer.output_root / "pilot-run-summary.json", summary)
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
