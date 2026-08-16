"""Candidate A-only Full Pretraining execution backend.

Importing and inspecting this module never starts training. The Host path
requires technical readiness plus an explicit production-issued Training
Execution Approval. The public standalone entry has no capability injection
surface and therefore remains fail closed.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any

from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny
from src.runtime.environment import collect_environment
from src.runtime.paths import repository_root
from src.tokenizer.operating import validate_operating_candidate

from .collator import CausalLMCollator
from .dataloader import create_dataloader
from .dataset_training_entry import (
    DatasetTrainingPermission,
    require_dataset_training_activation,
)
from .errors import TrainingError
from .execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    consume_training_execution_approval,
    require_training_execution_request,
)
from .full_pretraining import (
    FullPretrainingConfig,
    inspect_full_pretraining_readiness,
    require_full_pretraining_technical_readiness,
    resolve_full_pretraining_path,
)
from .metrics import TrainingMetric
from .pilot_pretraining import _lineage
from .trainer import Trainer, seed_everything
from .validation import evaluate_language_model

MID_CHECKPOINT_STEP = 2_442
FINAL_CHECKPOINT_STEP = 4_883
ALLOWED_CHECKPOINTS = ("checkpoint-2442", "checkpoint-4883")
SCHEDULED_TOKEN_LIMIT = 10_000_384


def _enter_execution_boundary() -> None:
    """Explicit post-consumption seam used by tests before any content access."""


def _write_json(path: Path, value: Any, *, replace: bool = False) -> None:
    """Atomically write primitive JSON without storing model input text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists() and not replace:
        raise TrainingError(
            "FULL_PRETRAINING_ARTIFACT_EXISTS", f"Artifact already exists: {path.name}"
        )
    try:
        with temporary.open("xb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except TrainingError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise TrainingError(
            "FULL_PRETRAINING_ARTIFACT_WRITE_FAILED", f"Failed to publish {path.name}."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def candidate_a_execution_plan(config: FullPretrainingConfig) -> dict[str, Any]:
    """Return a deterministic, text-free execution plan."""
    return {
        "candidate": "A",
        "token_target": config.token_budget,
        "scheduled_token_limit": config.scheduled_tokens,
        "optimizer_step_limit": config.max_steps,
        "equivalent_epoch_limit": config.scheduled_tokens / 71_307_940,
        "evaluation_steps": [0, FINAL_CHECKPOINT_STEP],
        "checkpoint_steps": [MID_CHECKPOINT_STEP, FINAL_CHECKPOINT_STEP],
        "maximum_checkpoint_count": 2,
        "wall_clock_hard_stop_seconds": config.wall_clock_budget["hard_stop_seconds"],
        "output_budget_bytes": config.disk_budget["run_budget_bytes"],
        "start_free_bytes": config.disk_budget["minimum_free_bytes_before_start"],
        "runtime_free_bytes": config.disk_budget["minimum_free_bytes_during_run"],
        "initialization_fingerprint": config.initialization_fingerprint,
        "resume_requested": config.resume_checkpoint is not None,
        "automatic_extension_allowed": False,
        "actual_text_values_stored": False,
    }


def dry_run_full_pretraining(
    config_path: Path,
    manifest_path: Path,
    *,
    probe_output: bool = False,
) -> dict[str, Any]:
    """Validate orchestration without creating a run or constructing a model."""
    report = inspect_full_pretraining_readiness(
        config_path, manifest_path, probe_output=probe_output
    )
    config = FullPretrainingConfig.from_yaml(config_path)
    return {
        "schema_version": "1.0",
        "status": report["status"],
        "mode": "dry_run",
        "execution_allowed": report["execution_allowed"],
        "training_started": False,
        "blocking_codes": report["blocking_codes"],
        "plan": candidate_a_execution_plan(config),
        "config_fingerprint": report["config_fingerprint"],
        "readiness_fingerprint": report["readiness_fingerprint"],
    }


class FullSafetyMonitor:
    """Fail-closed per-optimizer-step Candidate A safety monitor."""

    def __init__(
        self,
        config: FullPretrainingConfig,
        output_root: Path,
        *,
        started_at: float | None = None,
    ):
        self.config = config
        self.output_root = output_root
        self.started_at = time.perf_counter() if started_at is None else started_at
        window = int(config.system_safety["rolling_window_steps"])
        self.losses: deque[float] = deque(maxlen=window)
        self.gradients: deque[float] = deque(maxlen=window)
        self.loss_spikes = 0
        self.gradient_spikes = 0
        self.amp_skips = 0

    @staticmethod
    def _baseline(values: deque[float]) -> float | None:
        return sum(values) / len(values) if len(values) >= 10 else None

    def observe(self, metric: TrainingMetric) -> None:
        if metric.global_step > FINAL_CHECKPOINT_STEP:
            raise TrainingError(
                "FULL_PRETRAINING_STEP_LIMIT", "Optimizer step limit exceeded."
            )
        if metric.global_step * 2_048 > SCHEDULED_TOKEN_LIMIT:
            raise TrainingError(
                "FULL_PRETRAINING_TOKEN_LIMIT", "Scheduled token limit exceeded."
            )
        if not math.isfinite(metric.loss) or not math.isfinite(
            metric.gradient_norm_before_clip
        ):
            raise TrainingError(
                "NON_FINITE_LOSS", "Non-finite training metric detected."
            )
        if time.perf_counter() - self.started_at >= int(
            self.config.wall_clock_budget["hard_stop_seconds"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_WALL_CLOCK_LIMIT", "Wall-clock hard stop reached."
            )
        if metric.peak_memory_reserved > int(
            self.config.system_safety["maximum_reserved_vram_bytes"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_VRAM_LIMIT", "Reserved VRAM limit exceeded."
            )
        if metric.cpu_working_set_bytes is None:
            raise TrainingError(
                "FULL_PRETRAINING_CPU_MEMORY_UNAVAILABLE",
                "CPU working-set measurement is unavailable.",
            )
        if metric.cpu_working_set_bytes > int(
            self.config.system_safety["maximum_cpu_working_set_bytes"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_CPU_MEMORY_LIMIT", "CPU working-set limit exceeded."
            )
        free = shutil.disk_usage(self.output_root).free
        if free < int(self.config.disk_budget["minimum_free_bytes_during_run"]):
            raise TrainingError(
                "FULL_PRETRAINING_DISK_MINIMUM", "Runtime free disk is below 5 GiB."
            )
        if _directory_bytes(self.output_root) > int(
            self.config.disk_budget["run_budget_bytes"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_OUTPUT_BUDGET", "Run output exceeded 2 GiB."
            )

        self.amp_skips = self.amp_skips + 1 if metric.amp_step_skipped else 0
        if self.amp_skips >= int(self.config.system_safety["repeated_amp_skip_limit"]):
            raise TrainingError(
                "FULL_PRETRAINING_AMP_SKIP_LIMIT",
                "AMP skipped three consecutive optimizer steps.",
            )

        loss_baseline = self._baseline(self.losses)
        grad_baseline = self._baseline(self.gradients)
        loss_limit = float(self.config.system_safety["loss_spike_multiplier"])
        grad_limit = float(self.config.system_safety["gradient_norm_spike_multiplier"])
        loss_is_spike = bool(
            loss_baseline and metric.loss >= loss_baseline * loss_limit
        )
        gradient_is_spike = bool(
            grad_baseline
            and metric.gradient_norm_before_clip >= grad_baseline * grad_limit
        )
        self.loss_spikes = self.loss_spikes + 1 if loss_is_spike else 0
        self.gradient_spikes = self.gradient_spikes + 1 if gradient_is_spike else 0
        if not loss_is_spike:
            self.losses.append(metric.loss)
        if not gradient_is_spike:
            self.gradients.append(metric.gradient_norm_before_clip)
        if self.loss_spikes >= int(
            self.config.system_safety["loss_spike_consecutive_steps"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_LOSS_SPIKE",
                "Loss exceeded the rolling threshold for ten steps.",
            )
        if self.gradient_spikes >= int(
            self.config.system_safety["gradient_norm_spike_consecutive_steps"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_GRADIENT_SPIKE",
                "Gradient norm exceeded the rolling threshold for ten steps.",
            )


class SingleUseApprovalConsumer:
    """Atomically consume approval only after optimizer step 1 succeeds."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        manifest_path: Path,
        readiness_fingerprint: str,
    ):
        self.path = path
        self.run_id = run_id
        self.manifest_path = manifest_path
        self.readiness_fingerprint = readiness_fingerprint
        self.consumed = False

    def observe(self, metric: TrainingMetric) -> None:
        if metric.global_step != 1 or self.consumed:
            return
        _write_json(
            self.path,
            {
                "schema_version": "1.0",
                "status": "consumed",
                "single_use": True,
                "consumed_at_optimizer_step": 1,
                "run_id": self.run_id,
                "approval_manifest_sha256": file_checksum(self.manifest_path),
                "readiness_fingerprint": self.readiness_fingerprint,
            },
        )
        self.consumed = True


def _checkpoint_manifest(output_root: Path) -> dict[str, Any]:
    checkpoints = sorted(
        path for path in output_root.glob("checkpoint-*") if path.is_dir()
    )
    if tuple(path.name for path in checkpoints) != ALLOWED_CHECKPOINTS:
        raise TrainingError(
            "FULL_PRETRAINING_CHECKPOINT_POLICY_MISMATCH",
            "Only mid and final checkpoints are allowed.",
        )
    return {
        "schema_version": "1.0",
        "checkpoints": {
            path.name: {
                "bundle_bytes": _directory_bytes(path),
                "checksums_manifest_sha256": file_checksum(path / "checksums.json"),
            }
            for path in checkpoints
        },
    }


def _run_full_pretraining(
    config_path: Path,
    manifest_path: Path,
    readiness_report: dict[str, Any],
    *,
    dataset_permission: DatasetTrainingPermission | None = None,
    dataset_version_id: str = "",
    dataset_manifest_id: str = "",
    dataset_pair_fingerprint: str = "",
    execution_request: TrainingExecutionRequest | None = None,
    execution_approval: TrainingExecutionApproval | None = None,
    _lifecycle: object | None = None,
) -> dict[str, Any]:
    """Shared package-private implementation for public and future Host paths."""
    if _lifecycle is not None:
        from .production_orchestration_seams import (
            _HostFullPretrainingBackendLifecycle,
        )

        if type(_lifecycle) is not _HostFullPretrainingBackendLifecycle:
            raise TrainingError(
                "TRAINING_HOST_LIFECYCLE_INVALID",
                "A valid internal training backend lifecycle is required.",
            )
    require_dataset_training_activation(
        dataset_permission,
        dataset_version_id=dataset_version_id,
        dataset_manifest_id=dataset_manifest_id,
        pair_fingerprint=dataset_pair_fingerprint,
    )
    require_full_pretraining_technical_readiness(readiness_report)
    config = FullPretrainingConfig.from_yaml(config_path)
    if config.resume_checkpoint is not None:
        raise TrainingError(
            "FULL_PRETRAINING_RESUME_NOT_APPROVED",
            "Fresh Candidate A execution cannot resume.",
        )
    output_root = resolve_full_pretraining_path(config, config.output_dir)
    if output_root.exists():
        raise TrainingError(
            "FULL_PRETRAINING_OUTPUT_EXISTS", "Existing run/output reuse is blocked."
        )
    if shutil.disk_usage(output_root.parent).free < int(
        config.disk_budget["minimum_free_bytes_before_start"]
    ):
        raise TrainingError(
            "FULL_PRETRAINING_DISK_BUDGET_NOT_SATISFIED",
            "Start free disk is below 10 GiB.",
        )

    require_training_execution_request(
        execution_request,
        config_path,
        readiness_report,
        dataset_permission=dataset_permission,
        dataset_version_id=dataset_version_id,
        dataset_manifest_id=dataset_manifest_id,
        dataset_pair_fingerprint=dataset_pair_fingerprint,
    )
    consume_training_execution_approval(
        execution_approval,
        execution_request,
        dataset_permission=dataset_permission,
        dataset_version_id=dataset_version_id,
        dataset_manifest_id=dataset_manifest_id,
        dataset_pair_fingerprint=dataset_pair_fingerprint,
    )
    if _lifecycle is not None:
        _lifecycle._approval_was_consumed()
    _enter_execution_boundary()
    if _lifecycle is not None:
        _lifecycle._backend_was_entered()

    started = time.perf_counter()
    lineage = _lineage(config)
    training = config.to_training_config()
    seed_everything(config.seed)
    train_dataset = TokenizedJsonlDataset(
        resolve_full_pretraining_path(config, config.train_dataset),
        context_length=config.model.context_length,
        vocab_size=config.model.vocab_size,
    )
    evaluation_dataset = TokenizedJsonlDataset(
        resolve_full_pretraining_path(config, config.validation_dataset),
        context_length=config.model.context_length,
        vocab_size=config.model.vocab_size,
    )
    collator = CausalLMCollator(context_length=config.model.context_length)
    train_loader = create_dataloader(
        train_dataset,
        collator,
        training,
        shuffle=True,
        stateful=True,
        dataset_fingerprint=lineage["dataset_fingerprint"],
    )
    evaluation_loader = create_dataloader(
        evaluation_dataset, collator, training, shuffle=False
    )
    tokenizer_report = validate_operating_candidate(
        resolve_full_pretraining_path(config, config.tokenizer_model).parent
    )
    if (
        tokenizer_report.get("tokenizer_fingerprint")
        != lineage["tokenizer_fingerprint"]
    ):
        raise TrainingError(
            "FULL_PRETRAINING_TOKENIZER_MISMATCH",
            "Operating tokenizer identity mismatch.",
        )
    run_identity = {
        "run_id": output_root.name,
        "source_lineage_fingerprint": lineage["source_lineage_fingerprint"],
        "pii_fingerprint": lineage["pii_fingerprint"],
        "split_fingerprint": lineage["split_fingerprint"],
        "tokenization_fingerprint": lineage["tokenization_fingerprint"],
        "packing_fingerprint": lineage["packing_fingerprint"],
        "initialization_fingerprint": config.initialization_fingerprint,
        "full_config_fingerprint": file_checksum(config_path),
        "token_budget": config.token_budget,
        "scheduled_token_limit": config.scheduled_tokens,
    }
    trainer = Trainer(
        model=DohaLMTiny(config.model),
        dataloader=train_loader,
        config=training,
        dataset_fingerprint=lineage["dataset_fingerprint"],
        tokenizer_fingerprint=lineage["tokenizer_fingerprint"],
        output_root=output_root,
        dataset_metadata={
            "kind": "full-pretraining-candidate-a-v1",
            **lineage,
            **run_identity,
        },
        metric_filename="full-training-metrics.jsonl",
    )
    approval = json.loads(json.dumps(readiness_report))
    _write_json(
        output_root / "full-execution-manifest.json",
        {
            "schema_version": "1.0",
            "status": "running",
            "run_id": output_root.name,
            "plan": candidate_a_execution_plan(config),
            "actual_text_values_stored": False,
        },
    )
    monitor = FullSafetyMonitor(config, output_root, started_at=started)
    approval_consumer = SingleUseApprovalConsumer(
        output_root / "approval-consumption.json",
        run_id=output_root.name,
        manifest_path=manifest_path,
        readiness_fingerprint=approval["readiness_fingerprint"],
    )

    def observe_and_consume(metric: TrainingMetric) -> None:
        approval_consumer.observe(metric)
        monitor.observe(metric)

    try:
        initial_evaluation = evaluate_language_model(
            trainer.model,
            evaluation_loader,
            device=trainer.device,
            use_amp=trainer.amp_enabled,
        )
        result = trainer.train(
            target_steps=config.max_steps, metric_observer=observe_and_consume
        )
        final_path = trainer.checkpoints.save(
            model=trainer.model,
            model_config=trainer.model.config,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            training_config=trainer.config,
            state=trainer.state,
            dataset_metadata=trainer.dataset_metadata,
        )
        final_evaluation = evaluate_language_model(
            trainer.model,
            evaluation_loader,
            device=trainer.device,
            use_amp=trainer.amp_enabled,
        )
        if time.perf_counter() - started >= int(
            config.wall_clock_budget["hard_stop_seconds"]
        ):
            raise TrainingError(
                "FULL_PRETRAINING_WALL_CLOCK_LIMIT", "Wall-clock hard stop reached."
            )
        checkpoint_manifest = _checkpoint_manifest(output_root)
        evaluation = {
            "schema_version": "1.0",
            "fingerprint": config.evaluation_policy["fingerprint"],
            "evaluations": [
                {"stage": "start", **initial_evaluation.to_dict()},
                {"stage": "final", **final_evaluation.to_dict()},
            ],
            "generated_samples": False,
        }
        summary = {
            "schema_version": "1.0",
            "status": "completed",
            "global_step": trainer.state.global_step,
            "scheduled_tokens": trainer.state.global_step
            * config.tokens_per_optimizer_step,
            "actual_target_tokens_seen": trainer.state.tokens_seen,
            "checkpoints": [*result.checkpoints, final_path.name],
            "elapsed_seconds": time.perf_counter() - started,
            "dataset_fingerprint": lineage["dataset_fingerprint"],
            "tokenizer_fingerprint": lineage["tokenizer_fingerprint"],
            "model_fingerprint": checksum_value(config.model.to_dict()),
            "initialization_fingerprint": config.initialization_fingerprint,
            "config_fingerprint": file_checksum(config_path),
            "best_reference": {
                "checkpoint": final_path.name,
                "basis": "final_full_internal_evaluation",
            },
            "actual_text_values_stored": False,
            "approval_consumed": approval_consumer.consumed,
        }
        resolved = config.to_dict()
        _write_json(output_root / "full-config-resolved.json", resolved)
        _write_json(
            output_root / "full-environment-manifest.json",
            collect_environment(repository_root()),
        )
        _write_json(output_root / "full-dataset-reference-manifest.json", lineage)
        _write_json(output_root / "full-evaluation-metrics.json", evaluation)
        _write_json(
            output_root / "full-checkpoint-checksum-manifest.json", checkpoint_manifest
        )
        _write_json(
            output_root / "full-resource-report.json",
            {
                "schema_version": "1.0",
                "elapsed_seconds": summary["elapsed_seconds"],
                "output_bytes": _directory_bytes(output_root),
                "remaining_disk_bytes": shutil.disk_usage(output_root).free,
            },
        )
        _write_json(output_root / "full-run-summary.json", summary)
        _write_json(
            output_root / "full-completion-report.json",
            {
                "schema_version": "1.0",
                "status": "completed",
                "global_step": trainer.state.global_step,
                "checkpoint_count": 2,
                "automatic_extension": False,
            },
        )
        _write_json(
            output_root / "full-execution-manifest.json",
            {
                "schema_version": "1.0",
                "status": "completed",
                "run_id": output_root.name,
                "plan": candidate_a_execution_plan(config),
                "actual_text_values_stored": False,
            },
            replace=True,
        )
        return summary
    except Exception as exc:
        _write_json(
            output_root / "full-failure-report.json",
            {
                "schema_version": "1.0",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", None),
                "global_step": trainer.state.global_step,
                "automatic_retry": False,
                "actual_text_values_stored": False,
            },
            replace=(output_root / "full-failure-report.json").exists(),
        )
        raise


def run_full_pretraining(
    config_path: Path,
    manifest_path: Path,
    readiness_report: dict[str, Any],
    *,
    dataset_permission: DatasetTrainingPermission | None = None,
    dataset_version_id: str = "",
    dataset_manifest_id: str = "",
    dataset_pair_fingerprint: str = "",
    execution_request: TrainingExecutionRequest | None = None,
) -> dict[str, Any]:
    """Execute Candidate A after all prerequisites and a production decision."""
    return _run_full_pretraining(
        config_path,
        manifest_path,
        readiness_report,
        dataset_permission=dataset_permission,
        dataset_version_id=dataset_version_id,
        dataset_manifest_id=dataset_manifest_id,
        dataset_pair_fingerprint=dataset_pair_fingerprint,
        execution_request=execution_request,
    )
