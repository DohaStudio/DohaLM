"""Bounded full-scale DohaLM-Tiny validation using synthetic tokens only."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import torch

from src.data.checksums import checksum_value
from src.model import DohaLMTiny, ModelConfig, ParameterCounter

from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .dataset import SyntheticTokenDataset
from .errors import TrainingError
from .memory_probe import CudaMemoryProbe, MemorySnapshot, module_gradient_bytes, module_parameter_bytes, optimizer_state_bytes
from .sampler_state import StatefulBatchSampler
from .throughput import summarize_throughput
from .trainer import Trainer, TrainingResult, seed_everything


SYNTHETIC_TOKENIZER_FINGERPRINT = checksum_value({"kind": "synthetic-token-range", "vocab_size": 16_000})


def tiny_model_config(*, context_length: int = 256, dropout: float = 0.0) -> ModelConfig:
    return ModelConfig(context_length=context_length, dropout=dropout)


def repeated_pattern(sequence_length: int, vocab_size: int = 16_000) -> list[int]:
    return [2, *[8 + (index % (vocab_size - 8)) for index in range(sequence_length - 2)], 3]


def build_synthetic_stream(
    *,
    mode: str,
    sequence_length: int,
    num_records: int,
    seed: int,
    vocab_size: int = 16_000,
) -> SyntheticTokenDataset:
    if mode not in {"repeated_pattern", "deterministic_random"}:
        raise TrainingError("INVALID_TRAINING_CONFIG", "synthetic mode가 유효하지 않습니다.")
    pattern = repeated_pattern(sequence_length, vocab_size) if mode == "repeated_pattern" else None
    return SyntheticTokenDataset(
        vocab_size=vocab_size,
        sequence_length=sequence_length,
        num_records=num_records,
        seed=seed,
        pattern=pattern,
    )


def dataset_metadata(dataset: SyntheticTokenDataset, mode: str) -> dict[str, Any]:
    return {
        "kind": "tiny-synthetic-token-stream-v1",
        "mode": mode,
        "vocab_size": dataset.vocab_size,
        "sequence_length": dataset.sequence_length,
        "num_records": dataset.num_records,
        "seed": dataset.seed,
        "bos_token_id": dataset.bos_token_id,
        "eos_token_id": dataset.eos_token_id,
        "pad_token_id": 0,
        "labels_equal_input_ids": True,
        "contains_source_text": False,
    }


def build_tiny_trainer(
    *,
    model_config: ModelConfig,
    training_config: TrainingConfig,
    dataset: SyntheticTokenDataset,
    mode: str,
    output_root: Path,
    resume: bool = False,
) -> Trainer:
    seed_everything(training_config.seed)
    collator = CausalLMCollator(context_length=model_config.context_length)
    loader = create_dataloader(
        dataset,
        collator,
        training_config,
        stateful=True,
        dataset_fingerprint=dataset.fingerprint,
    )
    return Trainer(
        model=DohaLMTiny(model_config),
        dataloader=loader,
        config=training_config,
        dataset_fingerprint=dataset.fingerprint,
        tokenizer_fingerprint=SYNTHETIC_TOKENIZER_FINGERPRINT,
        output_root=output_root,
        dataset_metadata=dataset_metadata(dataset, mode),
        resume=resume,
        metric_filename="training-metrics.jsonl",
    )


def sampler_next_batch_fingerprint(state: dict[str, Any], *, dataset_size: int, batch_size: int) -> str:
    sampler = StatefulBatchSampler(
        dataset_size=dataset_size,
        batch_size=batch_size,
        seed=int(state["permutation_seed"]),
        dataset_fingerprint=str(state["dataset_fingerprint"]),
    )
    sampler.load_state_dict(state)
    try:
        indices = next(iter(sampler))
    except StopIteration:
        indices = []
    return checksum_value({"indices": indices})


def model_parameter_checksum(model: DohaLMTiny) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(str(tuple(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _git_value(*args: str) -> str | None:
    result = subprocess.run(["git", *args], check=False, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() if result.returncode == 0 else None


def _run_id(prefix: str, payload: dict[str, Any]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = checksum_value(payload).split(":", 1)[-1]
    return f"{prefix}-{timestamp}-{digest[:10]}"


@dataclass(frozen=True)
class BatchCandidate:
    sequence_length: int
    micro_batch_size: int
    gradient_accumulation_steps: int

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    def to_dict(self) -> dict[str, int]:
        return {**asdict(self), "effective_batch_size": self.effective_batch_size}


DEFAULT_BATCH_CANDIDATES = (
    BatchCandidate(256, 1, 8),
    BatchCandidate(256, 2, 4),
    BatchCandidate(128, 4, 2),
)


def run_probe_candidate(candidate: BatchCandidate, *, device: str, use_amp: bool, output_root: Path, seed: int) -> dict[str, Any]:
    config = TrainingConfig(
        batch_size=candidate.effective_batch_size,
        micro_batch_size=candidate.micro_batch_size,
        gradient_accumulation_steps=candidate.gradient_accumulation_steps,
        max_steps=1,
        learning_rate=3e-4,
        warmup_steps=0,
        scheduler_type="cosine",
        min_lr_ratio=0.1,
        use_amp=use_amp,
        seed=seed,
        save_every=2,
        output_dir="tests/output/tiny-batch-probe",
        device=device,
        pin_memory=device == "cuda",
    )
    dataset = build_synthetic_stream(
        mode="deterministic_random",
        sequence_length=candidate.sequence_length,
        num_records=max(16, candidate.effective_batch_size * 2),
        seed=seed,
    )
    trainer = build_tiny_trainer(
        model_config=tiny_model_config(context_length=256),
        training_config=config,
        dataset=dataset,
        mode="deterministic_random",
        output_root=output_root,
    )
    probe = CudaMemoryProbe(device)
    probe.start()
    started = time.perf_counter()
    result = trainer.train(target_steps=1)
    duration = time.perf_counter() - started
    memory = probe.finish(model=trainer.model, optimizer=trainer.optimizer)
    metric = result.metrics[-1]
    return {
        **candidate.to_dict(),
        "status": "passed",
        "finite_loss": True,
        "finite_gradient": True,
        "loss": metric.loss,
        "gradient_norm": metric.gradient_norm,
        "step_time_seconds": duration,
        "tokens_per_second": metric.tokens_per_second,
        **memory.to_dict(),
    }


def probe_batch_candidates(
    candidates: Iterable[BatchCandidate],
    *,
    device: str,
    use_amp: bool,
    output_root: Path,
    seed: int = 17,
    runner: Callable[..., dict[str, Any]] = run_probe_candidate,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        candidate_root = output_root / f"candidate-{index + 1}"
        try:
            result = runner(candidate, device=device, use_amp=use_amp, output_root=candidate_root, seed=seed)
        except torch.OutOfMemoryError as exc:
            result = {**candidate.to_dict(), "status": "oom", "error": str(exc)}
        except TrainingError as exc:
            result = {
                **candidate.to_dict(),
                "status": "non_finite" if exc.code.startswith("NON_FINITE") else "failed_validation",
                "error_code": exc.code,
                "error": str(exc),
            }
        results.append(result)
        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    report = {
        "schema_version": "1.0",
        "synthetic_only": True,
        "device": device,
        "amp_enabled": use_amp,
        "candidate_count": len(results),
        "passed_count": sum(item["status"] == "passed" for item in results),
        "oom_count": sum(item["status"] == "oom" for item in results),
        "candidates": results,
    }
    _write_json(output_root / "batch-probe.json", report)
    return report


def run_tiny_validation(
    *,
    output_parent: Path,
    mode: str,
    device: str,
    use_amp: bool,
    steps: int,
    save_step: int,
    sequence_length: int,
    micro_batch_size: int,
    accumulation_steps: int,
    records: int,
    seed: int,
    learning_rate: float,
    warmup_steps: int,
    min_lr_ratio: float,
    compare_uninterrupted: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not 0 < save_step < steps:
        raise TrainingError("INVALID_TRAINING_CONFIG", "save_step은 0보다 크고 steps보다 작아야 합니다.")
    payload = {
        "mode": mode,
        "device": device,
        "steps": steps,
        "save_step": save_step,
        "sequence_length": sequence_length,
        "micro_batch_size": micro_batch_size,
        "accumulation_steps": accumulation_steps,
        "records": records,
        "seed": seed,
    }
    selected_run_id = run_id or _run_id("tiny", payload)
    run_dir = output_parent / selected_run_id
    config = TrainingConfig(
        batch_size=micro_batch_size * accumulation_steps,
        micro_batch_size=micro_batch_size,
        gradient_accumulation_steps=accumulation_steps,
        max_steps=steps,
        learning_rate=learning_rate,
        warmup_steps=warmup_steps,
        scheduler_type="cosine",
        min_lr_ratio=min_lr_ratio,
        max_grad_norm=1.0,
        use_amp=use_amp,
        seed=seed,
        log_every=1,
        save_every=save_step,
        output_dir="tests/output/tiny-validation",
        device=device,
        num_workers=0,
        pin_memory=device == "cuda",
    )
    model_config = tiny_model_config(context_length=256, dropout=0.0)
    dataset = build_synthetic_stream(
        mode=mode,
        sequence_length=sequence_length,
        num_records=records,
        seed=seed,
    )
    trainer = build_tiny_trainer(
        model_config=model_config,
        training_config=config,
        dataset=dataset,
        mode=mode,
        output_root=run_dir,
    )
    memory_probe = CudaMemoryProbe(device)
    memory_probe.start()
    first = trainer.train(target_steps=save_step)
    checkpoint = run_dir / f"checkpoint-{save_step}"
    sampler_before = first.state.sampler_state
    if sampler_before is None:
        raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint 전에 sampler state가 기록되지 않았습니다.")
    next_before = sampler_next_batch_fingerprint(
        sampler_before,
        dataset_size=len(dataset),
        batch_size=micro_batch_size,
    )
    resumed = build_tiny_trainer(
        model_config=model_config,
        training_config=config,
        dataset=dataset,
        mode=mode,
        output_root=run_dir,
        resume=True,
    )
    resumed.resume_from(checkpoint)
    sampler_after_load = resumed.state.sampler_state
    if sampler_after_load is None:
        raise TrainingError("RESUME_STATE_MISMATCH", "resume sampler state가 없습니다.")
    next_after = sampler_next_batch_fingerprint(
        sampler_after_load,
        dataset_size=len(dataset),
        batch_size=micro_batch_size,
    )
    second = resumed.train(target_steps=steps)
    all_metrics = (*first.metrics, *second.metrics)
    throughput = summarize_throughput(all_metrics, exclude_warmup_steps=min(warmup_steps, len(all_metrics) - 1))
    measured_memory = memory_probe.finish(model=resumed.model, optimizer=resumed.optimizer)
    memory = MemorySnapshot(
        supported=measured_memory.supported,
        peak_allocated_bytes=max([item.peak_memory_allocated for item in all_metrics] + [measured_memory.peak_allocated_bytes]),
        peak_reserved_bytes=max([item.peak_memory_reserved for item in all_metrics] + [measured_memory.peak_reserved_bytes]),
        allocated_after_step_bytes=measured_memory.allocated_after_step_bytes,
        reserved_after_step_bytes=measured_memory.reserved_after_step_bytes,
        model_parameter_bytes=module_parameter_bytes(resumed.model),
        optimizer_state_bytes=optimizer_state_bytes(resumed.optimizer),
        gradient_bytes=module_gradient_bytes(resumed.model),
    )
    resumed_checksum = model_parameter_checksum(resumed.model)
    continuity: dict[str, Any] = {
        "resumed_from_step": save_step,
        "final_global_step": second.state.global_step,
        "learning_rate_continuous": second.state.last_learning_rate == second.metrics[-1].learning_rate,
        "sampler_state_equal_at_load": sampler_before == sampler_after_load,
        "next_batch_fingerprint_equal": next_before == next_after,
        "next_batch_fingerprint": next_after,
        "scheduler_step": resumed.scheduler.current_step,
        "scaler_state_present": bool(resumed.scaler.state_dict()) if use_amp else True,
        "weight_tying_preserved": resumed.model.token_embedding.weight is resumed.model.lm_head.weight,
        "resumed_model_parameter_checksum": resumed_checksum,
    }
    if compare_uninterrupted:
        reference_config = replace(
            config,
            save_every=steps + 1,
            output_dir="tests/output/tiny-validation-reference",
        )
        reference = build_tiny_trainer(
            model_config=model_config,
            training_config=reference_config,
            dataset=dataset,
            mode=mode,
            output_root=run_dir / "continuity-reference",
        )
        reference_result = reference.train(target_steps=steps)
        reference_checksum = model_parameter_checksum(reference.model)
        logits_input = dataset[0]["input_ids"].unsqueeze(0).to(device)
        resumed.model.eval()
        reference.model.eval()
        with torch.no_grad():
            resumed_logits = resumed.model(logits_input).logits.detach().float().cpu()
            reference_logits = reference.model(logits_input).logits.detach().float().cpu()
        max_difference = float((resumed_logits - reference_logits).abs().max().item())
        continuity.update(
            {
                "reference_model_parameter_checksum": reference_checksum,
                "bitwise_model_equal": resumed_checksum == reference_checksum,
                "final_loss_difference": abs(second.final_loss - reference_result.final_loss),
                "logits_max_absolute_difference": max_difference,
                "logits_allclose": bool(torch.allclose(resumed_logits, reference_logits, atol=1e-4, rtol=1e-4)),
            }
        )
    sampler_final = second.state.sampler_state or {}
    _write_json(run_dir / "throughput.json", throughput.to_dict())
    _write_json(run_dir / "memory.json", memory.to_dict())
    _write_json(run_dir / "resume-validation.json", continuity)
    _write_json(run_dir / "sampler-state.json", sampler_final)
    _write_json(run_dir / "batch-probe.json", {"status": "not_run_in_validation_command"})
    run_summary = {
        "run_id": selected_run_id,
        "status": "passed",
        "synthetic_only": True,
        "actual_pretraining": False,
        "mode": mode,
        "device": device,
        "amp_enabled": use_amp,
        "model_parameter_count": ParameterCounter.count(resumed.model).total,
        "initial_loss": first.initial_loss,
        "checkpoint_loss": first.final_loss,
        "final_loss": second.final_loss,
        "global_step": second.state.global_step,
        "checkpoint": checkpoint.name,
        "final_checkpoint": f"checkpoint-{steps}" if steps % save_step == 0 else None,
        "scheduler_type": "cosine_candidate",
        "gate_6": "planned",
        "gate_7": "planned",
    }
    _write_json(run_dir / "run-summary.json", run_summary)
    manifest = {
        "schema_version": "1.0",
        "run_id": selected_run_id,
        "model_config": model_config.to_dict(),
        "training_config": config.to_dict(),
        "dataset_fingerprint": dataset.fingerprint,
        "tokenizer_fingerprint": SYNTHETIC_TOKENIZER_FINGERPRINT,
        "synthetic_only": True,
        "contains_source_text": False,
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_branch": _git_value("branch", "--show-current"),
        "working_tree_dirty": bool(_git_value("status", "--porcelain")),
        "artifacts": [
            "run-summary.json",
            "batch-probe.json",
            "throughput.json",
            "memory.json",
            "training-metrics.jsonl",
            "resume-validation.json",
            "sampler-state.json",
            "validation-manifest.json",
            checkpoint.name,
            *([f"checkpoint-{steps}"] if steps % save_step == 0 and steps != save_step else []),
        ],
    }
    _write_json(run_dir / "validation-manifest.json", manifest)
    return {**run_summary, "run_directory_name": selected_run_id, "throughput": throughput.to_dict(), "memory": memory.to_dict(), "resume": continuity}
