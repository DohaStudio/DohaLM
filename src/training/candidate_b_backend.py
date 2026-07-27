"""Candidate B orchestration backend with fail-closed execution boundaries."""

from __future__ import annotations

import math
import os
import re
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import torch

from src.data.checksums import checksum_value, file_checksum
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny, ModelConfig
from src.tokenizer.operating import validate_operating_candidate

from .candidate_b import (
    CHECKPOINT_STEPS,
    MAX_STEPS,
    SCHEDULED_TOKENS,
    TOKENS_PER_STEP,
    candidate_b_backend_identity,
    candidate_b_checkpoint_contract,
    candidate_b_evaluation_hooks,
    require_candidate_b_execution,
    resolve_candidate_b_external_path,
    validate_candidate_b_approval,
    validate_candidate_b_scope,
)
from .checkpoint import CheckpointManager
from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .dataset import SyntheticTokenDataset
from .errors import TrainingError
from .full_pretraining_backend import _directory_bytes, _write_json
from .metrics import TrainingMetric
from .trainer import Trainer, seed_everything


CHECKPOINT_NAME_PATTERN = re.compile(r"checkpoint-([1-9][0-9]*)")


def parse_candidate_b_checkpoint_step(name: str, *, maximum_step: int = MAX_STEPS) -> int:
    """Parse a canonical positive checkpoint step without accepting aliases."""
    match = CHECKPOINT_NAME_PATTERN.fullmatch(name)
    if match is None:
        raise TrainingError("CANDIDATE_B_CHECKPOINT_NAME_INVALID", f"Invalid checkpoint name: {name}")
    step = int(match.group(1))
    if step > maximum_step:
        raise TrainingError("CANDIDATE_B_CHECKPOINT_NAME_INVALID", f"Checkpoint step exceeds {maximum_step}: {name}")
    return step


def analyze_candidate_b_checkpoint_schedule(
    names: list[str],
    *,
    metadata_steps: dict[str, int] | None = None,
    metadata_errors: dict[str, str] | None = None,
    expected_steps: tuple[int, ...] = CHECKPOINT_STEPS,
) -> dict[str, Any]:
    """Return an order-independent, diagnostic checkpoint schedule report."""
    parsed_pairs: list[tuple[str, int]] = []
    invalid_names: list[str] = []
    for name in names:
        try:
            parsed_pairs.append((name, parse_candidate_b_checkpoint_step(name, maximum_step=max(expected_steps))))
        except TrainingError:
            invalid_names.append(name)

    parsed_steps = sorted(step for _name, step in parsed_pairs)
    duplicate_steps = sorted({step for step in parsed_steps if parsed_steps.count(step) > 1})
    expected = sorted(expected_steps)
    missing_steps = sorted(set(expected) - set(parsed_steps))
    unexpected_steps = sorted(set(parsed_steps) - set(expected))
    mismatches: list[dict[str, Any]] = []
    metadata_steps = metadata_steps or {}
    for name, directory_step in parsed_pairs:
        metadata_step = metadata_steps.get(name)
        if metadata_step is not None and metadata_step != directory_step:
            mismatches.append({
                "checkpoint_name": name,
                "directory_step": directory_step,
                "metadata_step": metadata_step,
            })
    for name, code in sorted((metadata_errors or {}).items()):
        mismatches.append({"checkpoint_name": name, "error_code": code})

    final_step = max(expected)
    if invalid_names:
        status, failure_code = "checkpoint_name_invalid", "CANDIDATE_B_CHECKPOINT_NAME_INVALID"
    elif duplicate_steps:
        status, failure_code = "checkpoint_duplicate", "CANDIDATE_B_CHECKPOINT_DUPLICATE"
    elif mismatches:
        status, failure_code = "checkpoint_metadata_mismatch", "CANDIDATE_B_CHECKPOINT_METADATA_MISMATCH"
    elif unexpected_steps:
        status, failure_code = "checkpoint_unexpected", "CANDIDATE_B_CHECKPOINT_UNEXPECTED"
    elif final_step in missing_steps:
        status, failure_code = "final_checkpoint_missing", "CANDIDATE_B_FINAL_CHECKPOINT_MISSING"
    elif missing_steps:
        status, failure_code = "checkpoint_missing", "CANDIDATE_B_CHECKPOINT_MISSING"
    else:
        status, failure_code = "valid", None
    return {
        "status": status,
        "failure_code": failure_code,
        "expected_checkpoint_steps": expected,
        "discovered_checkpoint_names": sorted(names),
        "parsed_checkpoint_steps": parsed_steps,
        "invalid_checkpoint_names": sorted(invalid_names),
        "duplicate_checkpoint_steps": duplicate_steps,
        "missing_checkpoint_steps": missing_steps,
        "unexpected_checkpoint_steps": unexpected_steps,
        "checkpoint_metadata_mismatches": mismatches,
    }


def inspect_candidate_b_checkpoint_schedule(staging: Path) -> dict[str, Any]:
    """Inspect Candidate B checkpoint directories, checksums, and metadata."""
    names = [path.name for path in staging.iterdir() if path.is_dir() and path.name.startswith("checkpoint")]
    metadata_steps: dict[str, int] = {}
    metadata_errors: dict[str, str] = {}
    complete_steps: list[int] = []
    preservable_names: list[str] = []
    for name in names:
        checkpoint_path = staging / name
        if (checkpoint_path / "manifest.json").is_file() or (checkpoint_path / "checksums.json").is_file():
            preservable_names.append(name)
        try:
            step = parse_candidate_b_checkpoint_step(name)
            inspection = CheckpointManager.inspect(checkpoint_path)
            metadata_steps[name] = inspection.global_step
            if inspection.global_step == step:
                complete_steps.append(step)
        except TrainingError as exc:
            metadata_errors[name] = exc.code
    report = analyze_candidate_b_checkpoint_schedule(
        names,
        metadata_steps=metadata_steps,
        metadata_errors=metadata_errors,
    )
    report["complete_checkpoint_steps"] = sorted(complete_steps)
    report["preservable_checkpoint_names"] = sorted(preservable_names)
    return report


def _write_quarantine_checksum_manifest(staging: Path) -> None:
    files = {
        path.relative_to(staging).as_posix(): file_checksum(path)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and path.name != "quarantine-checksums.json"
    }
    _write_json(staging / "quarantine-checksums.json", {"algorithm": "sha256", "files": files})


def _failure_document(
    *,
    resolved: dict[str, Any],
    approval: dict[str, Any],
    consumer: "CandidateBApprovalConsumer",
    exc: Exception,
    step: int,
    checkpoint_report: dict[str, Any] | None,
    quarantine_logical_path: str | None,
    quarantine_status: str,
    staging_preserved: bool,
) -> dict[str, Any]:
    report = checkpoint_report or {}
    failure_code = getattr(exc, "code", type(exc).__name__)
    checkpoint_failure_codes = {
        "CANDIDATE_B_CHECKPOINT_NAME_INVALID",
        "CANDIDATE_B_CHECKPOINT_DUPLICATE",
        "CANDIDATE_B_CHECKPOINT_METADATA_MISMATCH",
        "CANDIDATE_B_CHECKPOINT_UNEXPECTED",
        "CANDIDATE_B_FINAL_CHECKPOINT_MISSING",
        "CANDIDATE_B_CHECKPOINT_MISSING",
    }
    document = {
        "schema_version": "2.0",
        "status": "failed",
        "failure_stage": (
            "post_training_checkpoint_validation" if failure_code in checkpoint_failure_codes else "training"
        ),
        "failure_code": failure_code,
        "failure_message": str(exc),
        "run_id": resolved["run_id"],
        "approval_id": approval["approval_id"],
        "approval_consumed": consumer.consumed,
        "optimizer_steps_completed": step,
        "scheduled_tokens_completed": step * TOKENS_PER_STEP,
        "expected_checkpoint_steps": report.get("expected_checkpoint_steps", list(CHECKPOINT_STEPS)),
        "discovered_checkpoint_names": report.get("discovered_checkpoint_names", []),
        "discovered_checkpoint_steps": report.get("parsed_checkpoint_steps", []),
        "parsed_checkpoint_steps": report.get("parsed_checkpoint_steps", []),
        "invalid_checkpoint_names": report.get("invalid_checkpoint_names", []),
        "checkpoint_metadata_mismatches": report.get("checkpoint_metadata_mismatches", []),
        "staging_preserved": staging_preserved,
        "quarantine_path": quarantine_logical_path,
        "quarantine_status": quarantine_status,
        "retry_allowed": False,
        "resume_allowed": False,
        "evaluation_allowed": False,
        "publication_allowed": False,
        "immutable_git_commit": approval.get("git_commit"),
        "backend_identity": candidate_b_backend_identity(),
        "config_fingerprint": checksum_value(resolved),
        "actual_text_values_stored": False,
    }
    return {**document, "failure_fingerprint": checksum_value(document)}


def _preserve_or_cleanup_failed_staging(
    *,
    staging: Path,
    output: Path,
    resolved: dict[str, Any],
    approval: dict[str, Any],
    consumer: "CandidateBApprovalConsumer",
    exc: Exception,
    step: int,
    checkpoint_report: dict[str, Any] | None,
) -> dict[str, Any]:
    complete = (checkpoint_report or {}).get("complete_checkpoint_steps", [])
    preservable = (checkpoint_report or {}).get("preservable_checkpoint_names", [])
    quarantine = output.parent.parent / "quarantine" / resolved["run_id"]
    quarantine_logical = f"analysis/training/candidate-b/quarantine/{resolved['run_id']}"
    if staging.exists() and (complete or preservable):
        if quarantine.exists():
            return _failure_document(
                resolved=resolved, approval=approval, consumer=consumer, exc=exc, step=step,
                checkpoint_report=checkpoint_report, quarantine_logical_path=None,
                quarantine_status="collision_staging_retained", staging_preserved=True,
            )
        policy = {
            "schema_version": "1.0",
            "status": "quarantined",
            "run_id": resolved["run_id"],
            "not_for_resume": True,
            "not_for_evaluation": True,
            "not_for_publication": True,
            "manual_review_required": True,
            "approval_reuse_allowed": False,
        }
        preliminary = _failure_document(
            resolved=resolved, approval=approval, consumer=consumer, exc=exc, step=step,
            checkpoint_report=checkpoint_report, quarantine_logical_path=quarantine_logical,
            quarantine_status="quarantined", staging_preserved=True,
        )
        try:
            _write_json(staging / "checkpoint-validation-report.json", checkpoint_report)
            _write_json(staging / "quarantine-policy.json", policy)
            _write_json(staging / "failure-manifest.json", preliminary)
            _write_quarantine_checksum_manifest(staging)
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, quarantine)
            return preliminary
        except (OSError, TrainingError):
            return _failure_document(
                resolved=resolved, approval=approval, consumer=consumer, exc=exc, step=step,
                checkpoint_report=checkpoint_report, quarantine_logical_path=None,
                quarantine_status="preservation_failed_staging_retained", staging_preserved=True,
            )
    _safe_remove_staging(staging, output.parent)
    return _failure_document(
        resolved=resolved, approval=approval, consumer=consumer, exc=exc, step=step,
        checkpoint_report=checkpoint_report, quarantine_logical_path=None,
        quarantine_status="not_applicable", staging_preserved=False,
    )


class CandidateBApprovalConsumer:
    """Publish a separate atomic consumption record immediately before step 1."""

    def __init__(
        self,
        *,
        approval: dict[str, Any],
        approval_path: Path,
        consumption_path: Path,
        readiness_fingerprint: str,
        fixture_mode: bool = False,
    ):
        if fixture_mode:
            if approval.get("approval_type") != "synthetic_test_fixture" or not str(approval.get("run_id", "")).startswith("SYNTHETIC-TEST-"):
                raise TrainingError("CANDIDATE_B_APPROVAL_FIXTURE_INVALID", "Synthetic approval fixture가 유효하지 않습니다.")
        elif approval.get("approval_type") != "candidate_b_execution" or approval.get("approval_status") != "approved":
            raise TrainingError("CANDIDATE_B_EXECUTION_APPROVAL_MISSING", "실제 Candidate B 승인이 유효하지 않습니다.")
        self.approval = approval
        self.approval_path = approval_path
        self.consumption_path = consumption_path
        self.readiness_fingerprint = readiness_fingerprint
        self.fixture_mode = fixture_mode
        self.consumed = False

    def consume_before_optimizer_step(self, next_step: int) -> None:
        if self.consumed:
            return
        if next_step != 1:
            raise TrainingError("CANDIDATE_B_APPROVAL_CONSUMPTION_ORDER", "승인은 optimizer step 1 직전에만 소비할 수 있습니다.")
        if self.approval.get("consumed") is not False or self.approval.get("single_use") is not True:
            raise TrainingError("CANDIDATE_B_APPROVAL_ALREADY_CONSUMED", "승인이 이미 소비됐거나 single-use가 아닙니다.")
        _write_json(self.consumption_path, {
            "schema_version": "1.0",
            "status": "consumed",
            "approval_id": self.approval["approval_id"],
            "approval_type": self.approval["approval_type"],
            "run_id": self.approval["run_id"],
            "single_use": True,
            "consumed_at_optimizer_step": 1,
            "approval_manifest_sha256": file_checksum(self.approval_path),
            "readiness_fingerprint": self.readiness_fingerprint,
            "synthetic_fixture": self.fixture_mode,
            "automatic_retry": False,
            "resume_allowed": False,
        })
        self.consumed = True


class CandidateBRuntimeMonitor:
    """Enforce Candidate B step/token/time/disk/memory and finite-value limits."""

    def __init__(self, resolved: dict[str, Any], output_root: Path, *, started_at: float | None = None):
        self.resolved = resolved
        self.output_root = output_root
        self.started_at = time.perf_counter() if started_at is None else started_at
        window = int(resolved["system_safety"]["rolling_window_steps"])
        self.losses: deque[float] = deque(maxlen=window)
        self.gradients: deque[float] = deque(maxlen=window)
        self.loss_spikes = 0
        self.gradient_spikes = 0
        self.amp_skips = 0

    @staticmethod
    def _baseline(values: deque[float]) -> float | None:
        return sum(values) / len(values) if len(values) >= 10 else None

    def observe(self, metric: TrainingMetric) -> None:
        if metric.global_step > MAX_STEPS:
            raise TrainingError("CANDIDATE_B_STEP_LIMIT", "Candidate B optimizer step limit exceeded.")
        if metric.global_step * TOKENS_PER_STEP > SCHEDULED_TOKENS:
            raise TrainingError("CANDIDATE_B_TOKEN_LIMIT", "Candidate B scheduled token limit exceeded.")
        if not math.isfinite(metric.loss) or not math.isfinite(metric.gradient_norm_before_clip):
            raise TrainingError("CANDIDATE_B_NON_FINITE", "Candidate B metric is NaN or Inf.")
        if time.perf_counter() - self.started_at >= int(self.resolved["runtime_budget"]["hard_stop_seconds"]):
            raise TrainingError("CANDIDATE_B_WALL_CLOCK_LIMIT", "Candidate B wall-clock hard stop reached.")
        if metric.peak_memory_reserved > int(self.resolved["system_safety"]["maximum_reserved_vram_bytes"]):
            raise TrainingError("CANDIDATE_B_VRAM_LIMIT", "Candidate B reserved VRAM limit exceeded.")
        if metric.cpu_working_set_bytes is None:
            raise TrainingError("CANDIDATE_B_CPU_MEMORY_UNAVAILABLE", "CPU RSS measurement is unavailable.")
        if metric.cpu_working_set_bytes > int(self.resolved["system_safety"]["maximum_cpu_working_set_bytes"]):
            raise TrainingError("CANDIDATE_B_CPU_MEMORY_LIMIT", "Candidate B CPU RSS limit exceeded.")
        if shutil.disk_usage(self.output_root).free < int(self.resolved["disk_budget"]["minimum_free_bytes_during_run"]):
            raise TrainingError("CANDIDATE_B_DISK_MINIMUM", "Candidate B runtime free disk is below 5GiB.")
        if _directory_bytes(self.output_root) > int(self.resolved["disk_budget"]["run_budget_bytes"]):
            raise TrainingError("CANDIDATE_B_OUTPUT_BUDGET", "Candidate B output exceeded 2GiB.")

        self.amp_skips = self.amp_skips + 1 if metric.amp_step_skipped else 0
        if self.amp_skips >= int(self.resolved["system_safety"]["repeated_amp_skip_limit"]):
            raise TrainingError("CANDIDATE_B_AMP_SKIP_LIMIT", "Candidate B AMP skipped three consecutive steps.")
        loss_baseline = self._baseline(self.losses)
        grad_baseline = self._baseline(self.gradients)
        loss_spike = bool(loss_baseline and metric.loss >= loss_baseline * float(self.resolved["system_safety"]["loss_spike_multiplier"]))
        grad_spike = bool(grad_baseline and metric.gradient_norm_before_clip >= grad_baseline * float(self.resolved["system_safety"]["gradient_norm_spike_multiplier"]))
        self.loss_spikes = self.loss_spikes + 1 if loss_spike else 0
        self.gradient_spikes = self.gradient_spikes + 1 if grad_spike else 0
        if not loss_spike:
            self.losses.append(metric.loss)
        if not grad_spike:
            self.gradients.append(metric.gradient_norm_before_clip)
        if self.loss_spikes >= int(self.resolved["system_safety"]["loss_spike_consecutive_steps"]):
            raise TrainingError("CANDIDATE_B_LOSS_SPIKE", "Candidate B loss spike limit reached.")
        if self.gradient_spikes >= int(self.resolved["system_safety"]["gradient_norm_spike_consecutive_steps"]):
            raise TrainingError("CANDIDATE_B_GRADIENT_SPIKE", "Candidate B gradient spike limit reached.")


def candidate_b_execution_plan(resolved: dict[str, Any]) -> dict[str, Any]:
    validate_candidate_b_scope(resolved, allow_placeholder_run_id=True)
    return {
        "candidate_id": "candidate-b",
        "run_id": resolved["run_id"],
        "optimizer_step_limit": MAX_STEPS,
        "scheduled_token_limit": SCHEDULED_TOKENS,
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "evaluation_hooks": candidate_b_evaluation_hooks(),
        "full_evaluation_automatic": False,
        "resume_allowed": False,
        "automatic_retry": False,
        "automatic_extension": False,
        "publication_allowed": False,
        "actual_text_values_stored": False,
        "full_token_ids_stored": False,
    }


def run_candidate_b_cpu_smoke(resolved: dict[str, Any]) -> dict[str, Any]:
    """Run two synthetic CPU forward batches with gradients and optimizer disabled."""
    validate_candidate_b_scope(resolved, allow_placeholder_run_id=True)
    model_config = ModelConfig(
        vocab_size=128,
        context_length=16,
        num_layers=2,
        hidden_size=32,
        num_heads=4,
        head_dim=8,
        ffn_size=64,
        dropout=0.0,
    )
    dataset = SyntheticTokenDataset(vocab_size=128, sequence_length=16, num_records=4, seed=17)
    training = TrainingConfig(
        batch_size=2,
        micro_batch_size=2,
        gradient_accumulation_steps=1,
        max_steps=1,
        learning_rate=3e-4,
        weight_decay=0.1,
        warmup_steps=1,
        scheduler_type="cosine",
        min_lr_ratio=0.1,
        max_grad_norm=1.0,
        use_amp=False,
        seed=17,
        log_every=1,
        save_every=1,
        output_dir="tests/output/candidate-b-synthetic-smoke",
        device="cpu",
    )
    loader = create_dataloader(dataset, CausalLMCollator(context_length=16), training, shuffle=False)
    model = DohaLMTiny(model_config).eval()
    losses: list[float] = []
    finite_logits = True
    with torch.inference_mode():
        for index, batch in enumerate(loader):
            output = model(batch["input_ids"], attention_mask=batch["attention_mask"], labels=batch["labels"])
            if output.loss is None:
                raise TrainingError("CANDIDATE_B_CPU_SMOKE_LOSS_MISSING", "Synthetic forward loss가 없습니다.")
            losses.append(float(output.loss.item()))
            finite_logits = finite_logits and bool(torch.isfinite(output.logits).all().item())
            if index == 1:
                break
    if len(losses) != 2 or not all(math.isfinite(value) for value in losses) or not finite_logits:
        raise TrainingError("CANDIDATE_B_CPU_SMOKE_FAILED", "Synthetic CPU forward가 finite하지 않습니다.")
    result = {
        "schema_version": "1.0",
        "status": "passed",
        "synthetic_test": True,
        "device": "cpu",
        "micro_batches": 2,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_calls": 0,
        "gradient_enabled": False,
        "finite_loss": True,
        "finite_logits": True,
        "actual_candidate_b_run_id_used": False,
        "actual_approval_consumed": False,
        "checkpoint_created": False,
        "external_output_published": False,
        "actual_text_values_stored": False,
        "full_token_ids_stored": False,
    }
    return {**result, "result_fingerprint": checksum_value(result)}


def _training_config(resolved: dict[str, Any]) -> TrainingConfig:
    training = resolved["training"]
    return TrainingConfig(
        batch_size=training["effective_batch_size"],
        micro_batch_size=training["micro_batch_size"],
        gradient_accumulation_steps=training["gradient_accumulation_steps"],
        max_steps=MAX_STEPS,
        learning_rate=training["learning_rate"],
        weight_decay=training["weight_decay"],
        warmup_steps=training["warmup_steps"],
        scheduler_type=training["scheduler"],
        min_lr_ratio=training["min_lr_ratio"],
        max_grad_norm=training["gradient_clip"],
        use_amp=True,
        seed=17,
        log_every=training["log_every"],
        save_every=CHECKPOINT_STEPS[0],
        output_dir="experiments/candidate-b-external-only",
        device="cuda",
        num_workers=0,
        pin_memory=True,
    )


def _safe_remove_staging(staging: Path, parent: Path) -> None:
    resolved = staging.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(".candidate-b-staging-"):
        raise TrainingError("CANDIDATE_B_STAGING_PATH_INVALID", "Refusing unexpected staging cleanup target.")
    if resolved.exists():
        shutil.rmtree(resolved)


def run_candidate_b(
    *,
    resolved: dict[str, Any],
    resolved_config_path: Path,
    approval: dict[str, Any],
    approval_path: Path,
    readiness_report: dict[str, Any],
) -> dict[str, Any]:
    """Execute Candidate B only after every immutable single-use condition passes."""
    require_candidate_b_execution(readiness_report)
    validate_candidate_b_scope(resolved, allow_placeholder_run_id=False)
    approval_blockers = validate_candidate_b_approval(
        approval, resolved, checksum_value(resolved), readiness_report["git"],
    )
    if approval_blockers:
        raise TrainingError("CANDIDATE_B_EXECUTION_BLOCKED", f"Approval mismatch: {approval_blockers}")

    output = resolve_candidate_b_external_path(resolved, resolved["paths"]["output_logical_root"])
    if output.exists():
        raise TrainingError("CANDIDATE_B_OUTPUT_COLLISION", "Candidate B output already exists.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".candidate-b-staging-{uuid.uuid4().hex}"
    failure_root = resolve_candidate_b_external_path(resolved, resolved["paths"]["failure_logical_root"])
    readiness_root = resolve_candidate_b_external_path(resolved, resolved["paths"]["readiness_logical_root"])
    failure_root.mkdir(parents=True, exist_ok=True)
    readiness_root.mkdir(parents=True, exist_ok=True)
    consumption_path = readiness_root / f"approval-consumption-{approval['approval_id']}.json"
    failure_path = failure_root / f"{resolved['run_id']}-failure.json"
    if staging.exists() or consumption_path.exists() or failure_path.exists():
        raise TrainingError("CANDIDATE_B_REEXECUTION_BLOCKED", "Candidate B staging/consumption/failure identity already exists.")

    started = time.perf_counter()
    trainer: Trainer | None = None
    checkpoint_report: dict[str, Any] | None = None
    consumer = CandidateBApprovalConsumer(
        approval=approval,
        approval_path=approval_path,
        consumption_path=consumption_path,
        readiness_fingerprint=readiness_report["readiness_fingerprint"],
    )
    try:
        model_config = ModelConfig(**resolved["model"])
        training = _training_config(resolved)
        seed_everything(17)
        train_dataset = TokenizedJsonlDataset(
            resolve_candidate_b_external_path(resolved, resolved["paths"]["train_dataset"]),
            context_length=model_config.context_length,
            vocab_size=model_config.vocab_size,
        )
        loader = create_dataloader(
            train_dataset,
            CausalLMCollator(context_length=model_config.context_length),
            training,
            shuffle=True,
            stateful=True,
            dataset_fingerprint=resolved["identity"]["dataset_fingerprint"],
        )
        tokenizer = validate_operating_candidate(
            resolve_candidate_b_external_path(resolved, resolved["paths"]["tokenizer_model"]).parent,
        )
        if tokenizer.get("tokenizer_fingerprint") != resolved["identity"]["tokenizer_fingerprint"]:
            raise TrainingError("CANDIDATE_B_TOKENIZER_MISMATCH", "Operating tokenizer fingerprint mismatch.")
        trainer = Trainer(
            model=DohaLMTiny(model_config),
            dataloader=loader,
            config=training,
            dataset_fingerprint=resolved["identity"]["dataset_fingerprint"],
            tokenizer_fingerprint=resolved["identity"]["tokenizer_fingerprint"],
            output_root=staging,
            dataset_metadata={
                "kind": "full-pretraining-candidate-b-v1",
                "run_id": resolved["run_id"],
                "approval_id": approval["approval_id"],
                **resolved["identity"],
            },
            metric_filename="candidate-b-training-metrics.jsonl",
        )
        monitor = CandidateBRuntimeMonitor(resolved, staging, started_at=started)
        result = trainer.train(
            target_steps=MAX_STEPS,
            metric_observer=monitor.observe,
            before_optimizer_step=consumer.consume_before_optimizer_step,
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
        checkpoint_report = inspect_candidate_b_checkpoint_schedule(staging)
        if checkpoint_report["status"] != "valid":
            raise TrainingError(
                checkpoint_report["failure_code"],
                f"Candidate B checkpoint validation failed: {checkpoint_report['status']}",
            )
        contracts = [candidate_b_checkpoint_contract(step, resolved) for step in CHECKPOINT_STEPS]
        _write_json(staging / "candidate-b-evaluation-hooks.json", candidate_b_evaluation_hooks())
        _write_json(staging / "candidate-b-checkpoint-contracts.json", {"contracts": contracts})
        summary = {
            "schema_version": "1.0",
            "status": "completed_training_awaiting_full_evaluation",
            "run_id": resolved["run_id"],
            "global_step": trainer.state.global_step,
            "scheduled_tokens": trainer.state.global_step * TOKENS_PER_STEP,
            "checkpoints": [*result.checkpoints, final_path.name],
            "resolved_config_fingerprint": checksum_value(resolved),
            "approval_id": approval["approval_id"],
            "approval_consumed": consumer.consumed,
            "elapsed_seconds": time.perf_counter() - started,
            "full_evaluation_completed": False,
            "actual_text_values_stored": False,
            "full_token_ids_stored": False,
            "automatic_retry": False,
            "automatic_resume": False,
            "automatic_extension": False,
        }
        _write_json(staging / "candidate-b-resolved-config.json", resolved)
        _write_json(staging / "candidate-b-run-summary.json", summary)
        os.replace(staging, output)
        return summary
    except Exception as exc:
        step = trainer.state.global_step if trainer is not None else 0
        if checkpoint_report is None and staging.exists():
            checkpoint_report = inspect_candidate_b_checkpoint_schedule(staging)
        failure = _preserve_or_cleanup_failed_staging(
            staging=staging,
            output=output,
            resolved=resolved,
            approval=approval,
            consumer=consumer,
            exc=exc,
            step=step,
            checkpoint_report=checkpoint_report,
        )
        _write_json(failure_path, failure)
        raise
