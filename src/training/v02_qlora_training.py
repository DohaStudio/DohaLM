"""Weighted QLoRA runtime for the immutable DohaLM v0.2 Sidecar package."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import yaml

from src.data.checksums import checksum_value
from src.training import qlora_training as common
from src.training.v02_weighted import (
    DATASET_FINGERPRINT,
    DATASET_ID,
    PACKAGE_FINGERPRINT,
    POLICY_FINGERPRINT,
    ROWS,
    SIDECAR_FINGERPRINT,
    SIMULATION_ID,
    TOKENIZATION_ID,
    TOKENIZER_FINGERPRINT,
    EpochWeightedSampler,
    SidecarWeightedTrainerMixin,
    read_safetensors_f64,
    validate_v02_tokenized_package,
)

ALLOCATION_ID = "DOHALM-V0.2-QLORA-ALLOCATION-SMOKE-WSL-20260801-0001"
BACKWARD_ID = "DOHALM-V0.2-QLORA-BACKWARD-DIAG-WSL-20260801-0001"
STAGE1_ID = "DOHALM-V0.2-QLORA-TRAINING-SMOKE-STAGE1-WSL-20260801-0001"
STAGE2_ID = "DOHALM-V0.2-QLORA-TRAINING-SMOKE-STAGE2-WSL-20260801-0001"
STABILITY_ID = "DOHALM-V0.2-QLORA-STABILITY-WSL-20260801-0001"
FULL_ID = "DOHALM-V0.2-QLORA-20260801-0001"
MODEL_ID = common.MODEL_ID
MODEL_REVISION = common.MODEL_REVISION
BACKWARD_LENGTHS = (128, 256, 512, 768, 1015)
SIMULATION_EPOCH0_FINGERPRINT = "sha256:b8157713c04bf2cdb7fd178031de1b8cb3f19287246577d14663940fb12998d3"
V01_BASELINE = {"character_f1": 0.4105867990028522, "rouge_l": 0.2725672754797666}


class V02QLoRAError(RuntimeError):
    """Stable fail-closed runtime error."""


@dataclass(frozen=True)
class WeightedContext:
    train: Any
    validation: Any
    train_sidecar: tuple[dict[str, Any], ...]
    validation_sidecar: tuple[dict[str, Any], ...]
    train_weights: tuple[float, ...]
    validation_weights: tuple[float, ...]
    epoch0_indices: tuple[int, ...]
    dataset_identity: dict[str, object]


def run_ids() -> dict[str, str]:
    return {
        "allocation": ALLOCATION_ID,
        "backward": BACKWARD_ID,
        "training-smoke-1": STAGE1_ID,
        "training-smoke-2": STAGE2_ID,
        "stability": STABILITY_ID,
        "full": FULL_ID,
    }


def output_roots(training_root: Path) -> dict[str, Path]:
    return {
        "allocation": training_root / "smoke" / ALLOCATION_ID,
        "backward": training_root / "diagnostics" / BACKWARD_ID,
        "training-smoke-1": training_root / "smoke" / STAGE1_ID,
        "training-smoke-2": training_root / "smoke" / STAGE2_ID,
        "stability": training_root / "stability" / STABILITY_ID,
        "full": training_root / "DohaLM-v0.2" / FULL_ID,
    }


def validate_config(path: Path) -> dict[str, object]:
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise V02QLoRAError("V02_CONFIG_INVALID") from None
    if not isinstance(config, dict):
        raise V02QLoRAError("V02_CONFIG_INVALID")
    model = config.get("model")
    quantization = config.get("quantization")
    lora = config.get("lora")
    training = config.get("training")
    dataset = config.get("dataset")
    sampling = config.get("sampling")
    evaluation = config.get("evaluation")
    if not all(isinstance(value, dict) for value in (model, quantization, lora, training, dataset, sampling, evaluation)):
        raise V02QLoRAError("V02_CONFIG_INVALID")
    assert isinstance(model, dict) and isinstance(quantization, dict)
    assert isinstance(lora, dict) and isinstance(training, dict)
    assert isinstance(dataset, dict) and isinstance(sampling, dict)
    assert isinstance(evaluation, dict)
    expected_targets = list(common.TARGET_MODULES)
    if (
        config.get("schema_version") != 1
        or model.get("base_model") != MODEL_ID
        or model.get("revision") != MODEL_REVISION
        or model.get("trust_remote_code") is not False
        or quantization != {"load_in_4bit": True, "quant_type": "nf4", "use_double_quant": True, "compute_dtype": "bfloat16"}
        or lora.get("r") != 16 or lora.get("alpha") != 32 or lora.get("dropout") != 0.05
        or lora.get("target_modules") != expected_targets
        or training.get("epochs") != 2
        or training.get("gradient_accumulation_steps") != 16
        or training.get("max_seq_length") != 1536
        or training.get("packing") is not False
        or training.get("dynamic_padding") is not True
        or training.get("assistant_only_loss") is not True
        or training.get("bf16") is not True or training.get("fp16") is not False
        or dataset.get("tokenization_id") != TOKENIZATION_ID
        or dataset.get("artifact_fingerprint") != f"sha256:{'ff6808122a5539c70ebb5d4bc503bda223852d25bba9149eb123f55a8c2b3b8e'}"
        or sampling.get("replacement") is not True
        or sampling.get("draws_per_epoch") != ROWS["train"]
        or sampling.get("base_seed") != 42
        or sampling.get("world_size") != 1
        or evaluation.get("generation_prompts") != 20
        or config.get("training_allowed") is not True
        or config.get("execution_allowed") is not True
    ):
        raise V02QLoRAError("V02_CONFIG_INVALID")
    return config


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V02QLoRAError("SIDECAR_RELOAD_FAILED") from None
    if any(not isinstance(value, dict) for value in values):
        raise V02QLoRAError("SIDECAR_RELOAD_FAILED")
    return values


def load_weighted_context(tokenized_root: Path, sidecar_root: Path) -> WeightedContext:
    from datasets import load_from_disk

    tokenized = validate_v02_tokenized_package(tokenized_root)
    if tokenized["artifact_fingerprint"] != "sha256:ff6808122a5539c70ebb5d4bc503bda223852d25bba9149eb123f55a8c2b3b8e":
        raise V02QLoRAError("TOKENIZED_ARTIFACT_MISMATCH")
    manifest = yaml.safe_load((sidecar_root / "manifest.yaml").read_text(encoding="utf-8"))
    fingerprints = manifest.get("fingerprints", {}) if isinstance(manifest, dict) else {}
    if (
        not isinstance(fingerprints, dict)
        or fingerprints.get("package") != f"sha256:{PACKAGE_FINGERPRINT}"
        or fingerprints.get("sidecar") != f"sha256:{SIDECAR_FINGERPRINT}"
        or fingerprints.get("sampling_policy") != f"sha256:{POLICY_FINGERPRINT}"
    ):
        raise V02QLoRAError("SOURCE_FINGERPRINT_MISMATCH")
    sidecar = _jsonl(sidecar_root / "quality-sidecar.jsonl")
    train_sidecar = tuple(value for value in sidecar if value.get("split") == "train")
    validation_sidecar = tuple(value for value in sidecar if value.get("split") == "validation")
    weights = read_safetensors_f64(tokenized_root / "sampling-weights.safetensors")
    train_weights = tuple(weights.get("train", []))
    validation_weights = tuple(weights.get("validation", []))
    if (
        len(train_sidecar) != ROWS["train"] or len(validation_sidecar) != ROWS["validation"]
        or len(train_weights) != ROWS["train"] or len(validation_weights) != ROWS["validation"]
        or any(value != 1.0 for value in validation_weights)
    ):
        raise V02QLoRAError("WEIGHT_ALIGNMENT_INVALID")
    sampler = EpochWeightedSampler(train_weights, num_samples=ROWS["train"], base_seed=42)
    epoch0 = tuple(sampler.draw_order())
    if sampler.draw_order_fingerprint() != SIMULATION_EPOCH0_FINGERPRINT:
        raise V02QLoRAError("SIMULATION_FINGERPRINT_MISMATCH")
    return WeightedContext(
        train=load_from_disk(tokenized_root / "train"),
        validation=load_from_disk(tokenized_root / "validation"),
        train_sidecar=train_sidecar,
        validation_sidecar=validation_sidecar,
        train_weights=train_weights,
        validation_weights=validation_weights,
        epoch0_indices=epoch0,
        dataset_identity={
            "dataset_id": DATASET_ID,
            "dataset_fingerprint": DATASET_FINGERPRINT,
            "package_fingerprint": f"sha256:{PACKAGE_FINGERPRINT}",
            "tokenization_id": TOKENIZATION_ID,
            "tokenized_artifact_fingerprint": tokenized["artifact_fingerprint"],
            "tokenizer_fingerprint": TOKENIZER_FINGERPRINT,
            "sampling_policy_fingerprint": f"sha256:{POLICY_FINGERPRINT}",
            "simulation_id": SIMULATION_ID,
            "simulation_epoch0_fingerprint": SIMULATION_EPOCH0_FINGERPRINT,
        },
    )


def _opaque_record(context: WeightedContext, index: int, draw_index: int) -> dict[str, object]:
    metadata = context.train_sidecar[index]
    return {
        "draw_index": draw_index,
        "record_hash": metadata["record_hash"],
        "source_line_index": index,
        "sequence_length": int(metadata["total_tokens"]),
        "sampling_weight": context.train_weights[index],
        "length_bucket": metadata["length_bucket"],
        "category_hash": hashlib.sha256(str(metadata.get("category")).encode("utf-8")).hexdigest(),
    }


def _model_mode(model: Any) -> dict[str, object]:
    decoder_layers = [
        module for name, module in model.named_modules()
        if re.search(r"(?:^|\.)layers\.\d+$", name)
    ]
    dropout = [module for name, module in model.named_modules() if "lora_dropout" in name]
    return {
        "top_level_model_training": bool(model.training),
        "decoder_layers_training": bool(decoder_layers) and all(module.training for module in decoder_layers),
        "lora_dropout_training": bool(dropout) and all(module.training for module in dropout),
        "gradient_checkpointing_owner_count": int(bool(getattr(model, "is_gradient_checkpointing", False))),
        "use_cache": bool(model.config.use_cache),
    }


def _load_runtime_model(config: Mapping[str, object], cache_root: Path) -> tuple[Any, Any, dict[str, object]]:
    tokenizer, base = common.load_tokenizer_and_model(config, cache_dir=cache_root)
    model = common.attach_lora(base, config)
    model.train()
    mode = _model_mode(model)
    if mode != {
        "top_level_model_training": True,
        "decoder_layers_training": True,
        "lora_dropout_training": True,
        "gradient_checkpointing_owner_count": 1,
        "use_cache": False,
    }:
        raise V02QLoRAError("MODEL_TRAIN_MODE_INVALID")
    stats = common.model_statistics(model, tokenizer).__dict__
    return tokenizer, model, {"model_statistics": stats, "training_mode": mode}


def run_allocation(
    *, config: Mapping[str, object], cache_root: Path, context: WeightedContext,
) -> dict[str, object]:
    tokenizer, model, model_meta = _load_runtime_model(config, cache_root)
    collator = common.DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    drawn = list(context.epoch0_indices)
    lengths = [len(context.train[index]["input_ids"]) for index in drawn]
    ordered = sorted(lengths)
    targets = [
        drawn[0],
        drawn[min(range(len(drawn)), key=lambda i: abs(lengths[i] - ordered[len(ordered) // 2]))],
        drawn[max(range(len(drawn)), key=lambda i: lengths[i])],
    ]
    selected = [("train", index, context.train[index]) for index in targets]
    validation_index = max(range(len(context.validation)), key=lambda i: len(context.validation[i]["input_ids"]))
    selected.append(("validation", validation_index, context.validation[validation_index]))
    records: list[dict[str, object]] = []
    torch.cuda.reset_peak_memory_stats()
    for ordinal, (split, index, row) in enumerate(selected):
        batch = common.move_batch(collator([row]))
        started = time.perf_counter()
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            loss = model(**batch).loss
        torch.cuda.synchronize()
        if loss is None or not torch.isfinite(loss):
            raise V02QLoRAError("ALLOCATION_LOSS_NONFINITE")
        metadata = context.train_sidecar[index] if split == "train" else context.validation_sidecar[index]
        records.append({
            "role": ("first_draw", "p50_draw", "longest_draw", "validation_longest")[ordinal],
            "split": split, "line_index": index, "record_hash": metadata["record_hash"],
            "sequence_length": len(row["input_ids"]), "padded_length": int(batch["input_ids"].shape[1]),
            "loss": float(loss.item()), "forward_seconds": time.perf_counter() - started,
            "allocated_bytes": torch.cuda.memory_allocated(), "reserved_bytes": torch.cuda.memory_reserved(),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        })
        del batch, loss
        torch.cuda.empty_cache()
    result = {
        "status": "passed", "run_id": ALLOCATION_ID, "sampled_records": records,
        "forward_records": 4, "backward_calls": 0, "optimizer_creations": 0,
        "optimizer_steps": 0, "loss_finite": True, "cpu_offload": False,
        "base_weights_frozen": True, "lora_attached": True, **model_meta,
        "simulation_fingerprint_valid": True,
    }
    del model
    common.release_cuda()
    return result


def run_backward(
    *, config: Mapping[str, object], cache_root: Path, context: WeightedContext,
) -> dict[str, object]:
    tokenizer, model, model_meta = _load_runtime_model(config, cache_root)
    unique = list(dict.fromkeys(context.epoch0_indices))
    records: list[dict[str, object]] = []
    for target in BACKWARD_LENGTHS:
        index = min(unique, key=lambda value: abs(len(context.train[value]["input_ids"]) - target))
        view = context.train.select([index])
        result = common.run_backward_diagnostic(
            model=model, tokenizer=tokenizer, train_dataset=view,
            validation_dataset=view.select([]), target_length=target,
            run_id=BACKWARD_ID, timeout_seconds=300,
        )
        result.update(_opaque_record(context, index, context.epoch0_indices.index(index)))
        records.append(result)
    if any(record["lora_gradient_tensors"] != 392 or record["base_gradient_tensors"] != 0 for record in records):
        raise V02QLoRAError("BACKWARD_GRADIENT_CONTRACT_INVALID")
    result = {
        "status": "passed", "run_id": BACKWARD_ID, "lengths": records,
        "all_lengths_completed": True, "finite_loss": True, "finite_gradients": True,
        "lora_gradient_tensors": 392, "base_gradient_tensors": 0,
        "optimizer_steps": 0, "stage_timeout": False, **model_meta,
        "simulation_fingerprint_valid": True,
    }
    del model
    common.release_cuda()
    return result


def _publish_simple(root: Path, filename: str, result: Mapping[str, object], environment: Mapping[str, object]) -> None:
    paths = common.ensure_unused_output(root)
    common.publish_result_artifact(paths, filename=filename, result=result, environment=environment)
    common.validate_result_artifact(root, filename=filename, expected_run_id=str(result["run_id"]))


def validate_prerequisite(root: Path, filename: str, run_id: str, expected_head: str) -> dict[str, object]:
    result = common.validate_result_artifact(root, filename=filename, expected_run_id=run_id)
    git = result.get("git")
    if not isinstance(git, dict) or git.get("head") != expected_head:
        raise V02QLoRAError("PREREQUISITE_GIT_MISMATCH")
    return result


def run_micro_training(
    *, mode: str, config: Mapping[str, object], cache_root: Path,
    context: WeightedContext, micro_batches: int, accumulation: int,
    validation_batches: int, save_checkpoint: bool,
) -> dict[str, object]:
    from peft import PeftModel
    from transformers import get_cosine_schedule_with_warmup

    run_id = {"stage1": STAGE1_ID, "stage2": STAGE2_ID, "stability": STABILITY_ID}[mode]
    expected_steps = micro_batches // accumulation
    tokenizer, model, model_meta = _load_runtime_model(config, cache_root)
    training = config["training"]
    assert isinstance(training, Mapping)
    collator = common.DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    optimizer = common.create_optimizer(model, learning_rate=float(training["learning_rate"]), weight_decay=float(training["weight_decay"]))
    scheduler = get_cosine_schedule_with_warmup(optimizer, num_warmup_steps=0, num_training_steps=expected_steps)
    indices = list(context.epoch0_indices[:micro_batches])
    if len(indices) != micro_batches:
        raise V02QLoRAError("MICRO_TRAINING_BUDGET_INVALID")
    base_versions = {name: parameter._version for name, parameter in model.named_parameters() if "lora_" not in name}
    trainable_before = {name: parameter.detach().clone() for name, parameter in model.named_parameters() if parameter.requires_grad}
    metrics: list[dict[str, object]] = []
    optimizer.zero_grad(set_to_none=True)
    optimizer_steps = 0
    duplicate_counts: Counter[int] = Counter()
    started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    for ordinal, index in enumerate(indices, start=1):
        duplicate_counts[index] += 1
        row = context.train[index]
        batch = common.move_batch(collator([row]))
        forward_started = time.perf_counter()
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            loss = model(**batch).loss
        torch.cuda.synchronize()
        forward_seconds = time.perf_counter() - forward_started
        if loss is None or not torch.isfinite(loss):
            raise V02QLoRAError("MICRO_TRAINING_LOSS_NONFINITE")
        backward_started = time.perf_counter()
        (loss / accumulation).backward()
        torch.cuda.synchronize()
        backward_seconds = time.perf_counter() - backward_started
        finite, gradient_norm = common.finite_gradients(model)
        if not finite:
            raise V02QLoRAError("MICRO_TRAINING_GRADIENT_NONFINITE")
        if ordinal % accumulation == 0:
            torch.nn.utils.clip_grad_norm_([parameter for parameter in model.parameters() if parameter.requires_grad], float(training["max_grad_norm"]))
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            optimizer_steps += 1
        metrics.append({
            **_opaque_record(context, index, ordinal - 1),
            "duplicate_draw": duplicate_counts[index] > 1,
            "forward_seconds": forward_seconds, "backward_seconds": backward_seconds,
            "total_seconds": forward_seconds + backward_seconds, "loss": float(loss.item()),
            "gradient_norm": gradient_norm, "optimizer_step": optimizer_steps,
            "allocated_vram_bytes": torch.cuda.memory_allocated(),
            "reserved_vram_bytes": torch.cuda.memory_reserved(),
            "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        })
        del loss, batch
        torch.cuda.empty_cache()
    if optimizer_steps != expected_steps:
        raise V02QLoRAError("MICRO_TRAINING_STEP_MISMATCH")
    lora_changed = any(not torch.equal(trainable_before[name], parameter.detach()) for name, parameter in model.named_parameters() if parameter.requires_grad)
    base_changed = any(base_versions[name] != parameter._version for name, parameter in model.named_parameters() if "lora_" not in name)
    if not lora_changed or base_changed:
        raise V02QLoRAError("MICRO_TRAINING_WEIGHT_CONTRACT_INVALID")
    eval_losses: list[float] = []
    if validation_batches:
        model.eval()
        with torch.no_grad():
            for index in range(validation_batches):
                batch = common.move_batch(collator([context.validation[index]]))
                loss = model(**batch).loss
                if loss is None or not torch.isfinite(loss):
                    raise V02QLoRAError("MICRO_TRAINING_EVAL_NONFINITE")
                eval_losses.append(float(loss.item()))
                del batch, loss
        model.train()
    checkpoint_info: dict[str, object] | None = None
    checkpoint_temp: Path | None = None
    if save_checkpoint:
        checkpoint_temp = cache_root.parent / f".{run_id}.checkpoint.tmp"
        if checkpoint_temp.exists():
            raise V02QLoRAError("CHECKPOINT_TEMP_COLLISION")
        model.save_pretrained(checkpoint_temp, safe_serialization=True)
        (checkpoint_temp / "trainer_state.json").write_text(json.dumps({"global_step": optimizer_steps}), encoding="utf-8")
        checkpoint_info = common.validate_checkpoint(checkpoint_temp)
        del model
        common.release_cuda()
        _, reload_base = common.load_tokenizer_and_model(config, cache_dir=cache_root)
        reload_model = PeftModel.from_pretrained(reload_base, checkpoint_temp, is_trainable=False)
        reload_model.eval()
        with torch.no_grad():
            batch = common.move_batch(collator([context.validation[0]]))
            reload_loss = reload_model(**batch).loss
        if reload_loss is None or not torch.isfinite(reload_loss):
            raise V02QLoRAError("CHECKPOINT_RELOAD_INVALID")
        checkpoint_info["reload_validated"] = True
        checkpoint_info["validation_loss"] = float(reload_loss.item())
        shutil.rmtree(checkpoint_temp)
        del reload_model, reload_base, batch, reload_loss
        common.release_cuda()
    else:
        del model
        common.release_cuda()
    durations = [float(value["total_seconds"]) for value in metrics]
    length_counts = Counter(str(value["length_bucket"]) for value in metrics)
    result: dict[str, object] = {
        "status": "passed", "run_id": run_id, "mode": mode,
        "micro_batches": micro_batches, "gradient_accumulation_steps": accumulation,
        "optimizer_steps": optimizer_steps, "validation_batches": validation_batches,
        "train_loss_mean": statistics.fmean(float(value["loss"]) for value in metrics),
        "eval_loss": statistics.fmean(eval_losses) if eval_losses else None,
        "metrics": metrics, "unique_rows": len(set(indices)),
        "coverage_ratio": len(set(indices)) / ROWS["train"],
        "duplicate_draws": micro_batches - len(set(indices)),
        "maximum_single_record_draws": max(Counter(indices).values()),
        "length_distribution": {key: value / micro_batches for key, value in sorted(length_counts.items())},
        "token_budget": sum(int(value["sequence_length"]) for value in metrics),
        "mean_sampling_weight": statistics.fmean(float(value["sampling_weight"]) for value in metrics),
        "mean_batch_seconds": statistics.fmean(durations), "p50_batch_seconds": _percentile(durations, .5),
        "p90_batch_seconds": _percentile(durations, .9), "p95_batch_seconds": _percentile(durations, .95),
        "p99_batch_seconds": _percentile(durations, .99), "max_batch_seconds": max(durations),
        "duration_seconds": time.perf_counter() - started,
        "stalled_batches": 0, "nonfinite_losses": 0, "nonfinite_gradients": 0,
        "cuda_oom": False, "base_weights_changed": False, "lora_weights_changed": True,
        "sampler_draw_fingerprint": checksum_value({"epoch": 0, "seed": 42, "indices": list(context.epoch0_indices)}),
        "simulation_fingerprint_valid": True, "validation_sampler_used": "sequential" if validation_batches else False,
        "checkpoint": checkpoint_info, **model_meta,
    }
    return result


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def runtime_estimate(stability: Mapping[str, object], simulation_root: Path) -> dict[str, object]:
    token_budget = json.loads((simulation_root / "token-budget.json").read_text(encoding="utf-8"))
    mean_batch = float(stability["mean_batch_seconds"])
    epoch_seconds = mean_batch * ROWS["train"]
    training_seconds = epoch_seconds * 2
    # Twelve Trainer evaluations plus six checkpoint/final evaluations traverse
    # the full validation split.  A validation forward is conservatively
    # budgeted at half a measured forward+backward microbatch.
    evaluation_events = 12 + 6
    evaluation_overhead = mean_batch * 0.5 * ROWS["validation"] * evaluation_events
    checkpoint_overhead = training_seconds * 0.05
    generation_overhead = 6 * 20 * 4.0
    total = training_seconds + evaluation_overhead + checkpoint_overhead + generation_overhead
    return {
        "weighted_epoch_tokens": token_budget["weighted_mean_epoch_total_tokens"],
        "mean_microbatch_seconds": mean_batch, "epoch_seconds": epoch_seconds,
        "training_seconds": training_seconds, "evaluation_overhead_seconds": evaluation_overhead,
        "evaluation_events": evaluation_events,
        "checkpoint_overhead_seconds": checkpoint_overhead,
        "generation_overhead_seconds": generation_overhead,
        "total_seconds": total, "total_hours": total / 3600,
        "acceptance_limit_hours": 48, "acceptable": total <= 48 * 3600,
    }


def validate_stage_result(result: Mapping[str, object], *, mode: str) -> None:
    """Validate a completed stage without weakening the stage-specific contract."""
    expected = run_ids().get(mode)
    if expected is None or result.get("run_id") != expected or result.get("status") != "passed":
        raise V02QLoRAError("STAGE_RESULT_INVALID")
    if result.get("simulation_fingerprint_valid") is not True:
        raise V02QLoRAError("SAMPLER_FINGERPRINT_INVALID")
    if mode == "allocation" and (
        result.get("forward_records") != 4
        or result.get("backward_calls") != 0
        or result.get("optimizer_creations") != 0
        or result.get("optimizer_steps") != 0
    ):
        raise V02QLoRAError("ALLOCATION_RESULT_INVALID")
    expected_shape = {
        "training-smoke-1": (2, 1, 1),
        "training-smoke-2": (32, 2, 2),
        "stability": (256, 16, 0),
    }.get(mode)
    if expected_shape is not None:
        micro, steps, validation = expected_shape
        if (
            result.get("micro_batches") != micro
            or result.get("optimizer_steps") != steps
            or result.get("validation_batches") != validation
            or result.get("stalled_batches") != 0
            or result.get("nonfinite_losses") != 0
            or result.get("nonfinite_gradients") != 0
            or result.get("cuda_oom") is not False
            or result.get("base_weights_changed") is not False
            or result.get("lora_weights_changed") is not True
        ):
            raise V02QLoRAError("TRAINING_STAGE_RESULT_INVALID")


def generation_verdict(generation: Mapping[str, object]) -> dict[str, object]:
    """Apply the immutable v0.1 baseline and v0.2 deployment targets."""
    samples = int(generation.get("samples", 0))
    if samples != 20:
        raise V02QLoRAError("GENERATION_SAMPLE_COUNT_INVALID")
    empty = int(generation.get("empty", 0))
    special = int(generation.get("special_token_exposure", 0))
    repetition = int(generation.get("repetition", 0)) / samples
    maximum = int(generation.get("maximum_length_reached", 0)) / samples
    eos = int(generation.get("eos_terminated", 0)) / samples
    incomplete = max(maximum, 1.0 - eos)
    character_f1 = float(generation.get("character_f1", 0.0))
    rouge_l = float(generation.get("rouge_l", 0.0))
    blockers = {
        "character_f1_below_v01_base": character_f1 < V01_BASELINE["character_f1"],
        "rouge_l_below_v01_base": rouge_l < V01_BASELINE["rouge_l"],
        "repetition_rate_over_50_percent": repetition > 0.5,
        "special_token_exposure": special > 0,
        "empty_output": empty > 0,
    }
    targets = {
        "eos_rate_at_least_80_percent": eos >= 0.8,
        "repetition_rate_below_15_percent": repetition < 0.15,
        "incomplete_rate_below_15_percent": incomplete < 0.15,
        "character_f1_above_0_48": character_f1 > 0.48,
        "rouge_l_above_0_32": rouge_l > 0.32,
    }
    return {
        "hard_blockers": blockers,
        "hard_blocker_clear": not any(blockers.values()),
        "targets": targets,
        "all_targets_met": all(targets.values()),
        "rates": {"eos": eos, "repetition": repetition, "incomplete": incomplete},
    }


def full_training_preflight(
    *, stage_results: Mapping[str, Mapping[str, object]], estimate: Mapping[str, object],
) -> dict[str, object]:
    for mode in ("allocation", "backward", "training-smoke-1", "training-smoke-2", "stability"):
        if mode not in stage_results:
            raise V02QLoRAError("PREREQUISITE_STAGE_MISSING")
        if mode != "backward":
            validate_stage_result(stage_results[mode], mode=mode)
    backward = stage_results["backward"]
    if (
        backward.get("status") != "passed"
        or backward.get("run_id") != BACKWARD_ID
        or backward.get("optimizer_steps") != 0
        or backward.get("lora_gradient_tensors") != 392
        or backward.get("base_gradient_tensors") != 0
    ):
        raise V02QLoRAError("BACKWARD_RESULT_INVALID")
    if estimate.get("acceptable") is not True or float(estimate.get("total_hours", 49)) > 48:
        raise V02QLoRAError("RUNTIME_ESTIMATE_EXCEEDED")
    return {
        "status": "passed", "expected_epochs": 2,
        "expected_optimizer_steps_per_epoch": 649,
        "expected_total_optimizer_steps": 1298,
        "automatic_retry": False, "automatic_resume": False,
    }


def sampler_metadata(context: WeightedContext) -> dict[str, object]:
    epochs: list[dict[str, object]] = []
    for epoch in range(2):
        sampler = EpochWeightedSampler(context.train_weights, num_samples=ROWS["train"], base_seed=42)
        sampler.set_epoch(epoch)
        indices = sampler.draw_order()
        epochs.append({
            "epoch": epoch, "seed": 42 + epoch,
            "draw_order_fingerprint": sampler.draw_order_fingerprint(),
            "unique_rows": len(set(indices)),
            "duplicate_draws": len(indices) - len(set(indices)),
            "maximum_single_record_draws": max(Counter(indices).values()),
        })
    if epochs[0]["draw_order_fingerprint"] != SIMULATION_EPOCH0_FINGERPRINT:
        raise V02QLoRAError("SIMULATION_FINGERPRINT_MISMATCH")
    return {
        "implementation": "WeightedRandomSampler", "replacement": True,
        "draws_per_epoch": ROWS["train"], "base_seed": 42,
        "validation_sampler": "SequentialSampler", "validation_weighted": False,
        "sampling_warning": "SAMPLING_MAX_RECORD_DRAWS_WARNING", "epochs": epochs,
    }


def write_full_contract_artifacts(
    root: Path, *, config: Mapping[str, object], result: Mapping[str, object],
    sampler: Mapping[str, object], generation: Mapping[str, object], environment: Mapping[str, object],
) -> None:
    """Write the required result bundle before the common atomic publisher step."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "training-config.yaml").write_text(
        yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (root / "training-result.yaml").write_text(
        yaml.safe_dump(dict(result), allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    for name, value in (
        ("sampler-metadata.json", sampler),
        ("generation-evaluation.json", generation),
        ("environment.json", environment),
    ):
        (root / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    common.write_checksums(root)


def validate_full_contract_artifact(root: Path) -> dict[str, object]:
    required = {
        "checkpoints", "final-adapter", "training-config.yaml", "training-result.yaml",
        "sampler-metadata.json", "generation-evaluation.json", "environment.json", "checksums.sha256",
    }
    if not root.is_dir() or not required.issubset({path.name for path in root.iterdir()}):
        raise V02QLoRAError("FULL_ARTIFACT_INCOMPLETE")
    if common.file_checksums(root) != common._parse_checksum_file(root):
        raise V02QLoRAError("FULL_ARTIFACT_CHECKSUM_MISMATCH")
    result = yaml.safe_load((root / "training-result.yaml").read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("run_id") != FULL_ID or result.get("status") != "completed":
        raise V02QLoRAError("FULL_RESULT_INVALID")
    return result


def _generation_prompts(sidecar_root: Path) -> tuple[list[Any], str]:
    from src.evaluation.qlora_sft import PromptRecord

    source = _jsonl(sidecar_root / "validation.jsonl")
    metadata = [row for row in _jsonl(sidecar_root / "quality-sidecar.jsonl") if row.get("split") == "validation"]
    if len(source) != ROWS["validation"] or len(metadata) != len(source):
        raise V02QLoRAError("EVALUATION_ALIGNMENT_INVALID")
    groups: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for record, sidecar in zip(source, metadata, strict=True):
        category = str(sidecar.get("category", ""))
        digest = str(sidecar.get("record_hash", ""))
        if not category or len(digest) != 64:
            raise V02QLoRAError("EVALUATION_METADATA_INVALID")
        groups[category].append((digest, record, sidecar))
    if len(groups) != 10 or any(len(values) < 2 for values in groups.values()):
        raise V02QLoRAError("EVALUATION_BALANCE_UNAVAILABLE")
    prompts: list[Any] = []
    for category in sorted(groups):
        ordered = sorted(groups[category], key=lambda value: (str(value[2].get("length_bucket")), value[0]))
        for digest, record, sidecar in (ordered[0], ordered[-1]):
            instruction = str(record.get("instruction", ""))
            input_value = str(record.get("input") or "")
            prompt = instruction if not input_value else f"{instruction}\n\n{input_value}"
            prompts.append(PromptRecord(
                sample_hash=digest, kind="held_out_validation", category=category,
                prompt=prompt, reference=str(record.get("output", "")),
                length_bucket=str(sidecar.get("length_bucket")),
            ))
    identity = checksum_value([
        {"sample_hash": item.sample_hash, "category": item.category, "length_bucket": item.length_bucket}
        for item in prompts
    ])
    return prompts, identity


def _token_weighted_validation_loss(model: Any, validation: Any, collator: Any) -> float:
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    with torch.inference_mode():
        for index in range(len(validation)):
            batch = common.move_batch(collator([validation[index]]))
            label_tokens = int((batch["labels"] != -100).sum().item())
            loss = model(**batch).loss
            if loss is None or not torch.isfinite(loss) or label_tokens <= 0:
                raise V02QLoRAError("VALIDATION_LOSS_INVALID")
            total_loss += float(loss.item()) * label_tokens
            total_tokens += label_tokens
    model.train()
    return total_loss / total_tokens


def _evaluate_adapter(
    *, config: Mapping[str, object], cache_root: Path, adapter_root: Path,
    validation: Any, prompts: Sequence[Any], tokenizer: Any,
) -> dict[str, object]:
    from peft import PeftModel
    from src.evaluation.qlora_sft import aggregate_generation, evaluate_generation

    _, base = common.load_tokenizer_and_model(config, cache_dir=cache_root)
    model = PeftModel.from_pretrained(base, adapter_root, is_trainable=False)
    model.eval()
    collator = common.DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    validation_loss = _token_weighted_validation_loss(model, validation, collator)
    generation = evaluate_generation(
        model, tokenizer, prompts, max_new_tokens=256, repetition_penalty=1.05,
        train_output_hashes=set(),
    )
    aggregate = aggregate_generation(generation)
    overall = aggregate["overall"]
    verdict = generation_verdict(overall)
    result = {
        "token_weighted_validation_loss": validation_loss,
        "generation": aggregate,
        "verdict": verdict,
        "raw_text_stored": False, "token_ids_stored": False,
    }
    del model, base
    common.release_cuda()
    return result


def run_full_training(
    *, paths: common.ArtifactPaths, config: Mapping[str, object], config_path: Path,
    cache_root: Path, context: WeightedContext, sidecar_root: Path,
    repository: Path, expected_head: str, environment: Mapping[str, object],
    git_identity: Mapping[str, object],
) -> dict[str, object]:
    """Execute exactly one fresh weighted two-epoch training run."""
    from transformers import Trainer

    class WeightedTrainer(SidecarWeightedTrainerMixin, Trainer):
        def training_step(self, model: Any, inputs: dict[str, Any], num_items_in_batch: Any = None) -> Any:
            started = time.perf_counter()
            loss = super().training_step(model, inputs, num_items_in_batch)
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            if time.perf_counter() - started > 300:
                raise V02QLoRAError("MICROBATCH_WATCHDOG_EXCEEDED")
            return loss

    paths.staging.mkdir(parents=True)
    started = time.perf_counter()
    try:
        tokenizer, model, model_meta = _load_runtime_model(config, cache_root)
        prompts, prompt_fingerprint = _generation_prompts(sidecar_root)
        checkpoints_root = paths.staging / "checkpoints"
        arguments = common.training_arguments(output_dir=checkpoints_root, config=config, run_name=FULL_ID)
        # Keep all scheduled checkpoints until their generation evaluation is durable.
        arguments.save_total_limit = None
        collator = common.DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        monitor = common.RuntimeMonitorCallback(
            repository=repository, expected_head=expected_head,
            dataset_root=sidecar_root, metrics_path=paths.staging / "metrics.jsonl",
        )
        trainer = WeightedTrainer(
            model=model, args=arguments, train_dataset=context.train,
            eval_dataset=context.validation, data_collator=collator, callbacks=[monitor],
            train_sampling_weights=context.train_weights, sampling_base_seed=42,
        )
        torch.cuda.reset_peak_memory_stats()
        output = trainer.train(resume_from_checkpoint=None)
        if int(trainer.state.global_step) != 1298:
            raise V02QLoRAError("OPTIMIZER_STEP_COUNT_MISMATCH")
        final_adapter = paths.staging / "final-adapter"
        model.save_pretrained(final_adapter, safe_serialization=True)
        trainer.state.save_to_json(str(final_adapter / "trainer_state.json"))
        shutil.copy2(config_path, final_adapter / "training-config.yaml")
        peak = torch.cuda.max_memory_allocated()
        del trainer, model
        common.release_cuda()

        checkpoint_dirs = sorted(
            (path for path in checkpoints_root.glob("checkpoint-*") if path.is_dir()),
            key=lambda path: int(path.name.rsplit("-", 1)[1]),
        )
        expected = [250, 500, 750, 1000, 1250]
        if [int(path.name.rsplit("-", 1)[1]) for path in checkpoint_dirs] != expected:
            raise V02QLoRAError("CHECKPOINT_SCHEDULE_INVALID")
        evaluations: dict[str, object] = {}
        for checkpoint in [*checkpoint_dirs, final_adapter]:
            common.validate_checkpoint(checkpoint)
            evaluations[checkpoint.name] = _evaluate_adapter(
                config=config, cache_root=cache_root, adapter_root=checkpoint,
                validation=context.validation, prompts=prompts, tokenizer=tokenizer,
            )
            (paths.staging / "generation-evaluation.json").write_text(
                json.dumps(evaluations, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
        retained = checkpoint_dirs[-2:]
        for checkpoint in checkpoint_dirs[:-2]:
            shutil.rmtree(checkpoint)
        eligible = [
            name for name, value in evaluations.items()
            if isinstance(value, dict) and value.get("verdict", {}).get("hard_blocker_clear") is True
            and (name == "final-adapter" or (checkpoints_root / name) in retained)
        ]
        selected = min(
            eligible,
            key=lambda name: float(evaluations[name]["token_weighted_validation_loss"]),
            default=None,
        )
        sampler = sampler_metadata(context)
        result: dict[str, object] = {
            "status": "completed", "run_id": FULL_ID, "git": dict(git_identity),
            "epochs_completed": 2, "optimizer_steps": 1298,
            "train_rows": ROWS["train"], "validation_rows": ROWS["validation"],
            "train_runtime_seconds": time.perf_counter() - started,
            "train_metrics": dict(output.metrics), "peak_allocated_bytes": peak,
            "prompt_selection_fingerprint": prompt_fingerprint,
            "checkpoint_evaluations_completed": True,
            "retained_checkpoints": [path.name for path in retained],
            "final_adapter_present": True, "selected_candidate": selected,
            "deployment_ready": selected is not None,
            "automatic_retry": False, "automatic_resume": False,
            "source_dataset_modified": False, "tokenization_modified": False,
            **model_meta,
        }
        (paths.staging / "training-config.yaml").write_text(
            yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        (paths.staging / "training-result.yaml").write_text(
            yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        (paths.staging / "sampler-metadata.json").write_text(
            json.dumps(sampler, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )
        (paths.staging / "environment.json").write_text(
            json.dumps(dict(environment), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )
        common.write_checksums(paths.staging)
        common.publish_staging(paths)
        return result
    except Exception:
        common.quarantine_staging(paths)
        raise
