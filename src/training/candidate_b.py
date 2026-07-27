"""Fail-closed Candidate B configuration, approval, and readiness contracts.

This module is inspection-first. Importing it never constructs a model, opens a
training dataset, consumes an approval, or starts an optimizer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

import yaml

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.data.checksums import checksum_value, file_checksum
from src.model import ModelConfig
from src.runtime.paths import repository_root, resolve_repository_path

from .errors import TrainingError


CANDIDATE_ID = "candidate-b"
TRAINING_STAGE = "full_pretraining_candidate"
TOKEN_BUDGET = 25_000_000
TOKENS_PER_STEP = 2_048
MAX_STEPS = 12_208
SCHEDULED_TOKENS = 25_001_984
SEED = 17
CHECKPOINT_STEPS = (4_883, 9_766, 12_208)
CHECKPOINT_TOKENS = (10_000_384, 20_000_768, 25_001_984)
QUICK_EVALUATION_STAGES = ("start", "step-4883", "final")
FULL_EVALUATION_STAGES = ("post-training-final",)
FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
PLACEHOLDER_PATTERN = re.compile(r"(?:YYYYMMDD|NNNN|<[^>]+>)")
APPROVED_ACTION = "candidate_b_full_pretraining"


def _load_yaml(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrainingError(code, f"YAML을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(value, dict):
        raise TrainingError(code, f"YAML root는 mapping이어야 합니다: {path.name}")
    return value


def _relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TrainingError("CANDIDATE_B_CONFIG_INVALID", f"{field}는 상대경로 문자열이어야 합니다.")
    normalized = value.replace("\\", "/")
    if (
        PureWindowsPath(normalized).is_absolute()
        or PurePosixPath(normalized).is_absolute()
        or ".." in PurePosixPath(normalized).parts
    ):
        raise TrainingError("CANDIDATE_B_ABSOLUTE_PATH_FORBIDDEN", f"{field}는 안전한 상대경로여야 합니다.")
    return normalized


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrainingError("CANDIDATE_B_CONFIG_INVALID", f"{field}는 mapping이어야 합니다.")
    return value


def _exact(actual: Any, expected: Any, *, field: str) -> None:
    if actual != expected:
        raise TrainingError("CANDIDATE_B_SCOPE_MISMATCH", f"Candidate B fixed scope mismatch: {field}")


def validate_candidate_b_scope(document: dict[str, Any], *, allow_placeholder_run_id: bool) -> None:
    """Reject every setting outside the approved Candidate B design envelope."""
    _exact(document.get("candidate_id"), CANDIDATE_ID, field="candidate_id")
    _exact(document.get("training_stage"), TRAINING_STAGE, field="training_stage")
    run_id = document.get("run_id")
    if not isinstance(run_id, str) or not run_id.startswith("FULL-PRETRAIN-CANDIDATE-B-"):
        raise TrainingError("CANDIDATE_B_RUN_ID_INVALID", "Candidate B run ID가 유효하지 않습니다.")
    if not allow_placeholder_run_id and PLACEHOLDER_PATTERN.search(run_id):
        raise TrainingError("CANDIDATE_B_RUN_ID_NOT_FROZEN", "실행 Run ID placeholder가 남아 있습니다.")

    budget = _mapping(document.get("budget"), field="budget")
    expected_budget = {
        "requested_tokens": TOKEN_BUDGET,
        "tokens_per_optimizer_step": TOKENS_PER_STEP,
        "optimizer_steps": MAX_STEPS,
        "scheduled_tokens": SCHEDULED_TOKENS,
    }
    for key, value in expected_budget.items():
        _exact(budget.get(key), value, field=f"budget.{key}")
    if math.ceil(TOKEN_BUDGET / TOKENS_PER_STEP) != MAX_STEPS:
        raise TrainingError("CANDIDATE_B_BUDGET_INTERNAL_ERROR", "Candidate B token/step 계산이 유효하지 않습니다.")

    initialization = _mapping(document.get("initialization"), field="initialization")
    expected_initialization = {
        "mode": "fresh",
        "seed": SEED,
        "parent_checkpoint": None,
        "candidate_a_checkpoint_used": False,
        "candidate_a_state_reused": False,
    }
    for key, value in expected_initialization.items():
        _exact(initialization.get(key), value, field=f"initialization.{key}")

    training = _mapping(document.get("training"), field="training")
    expected_training = {
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 4,
        "effective_batch_size": 8,
        "context_length": 256,
        "precision": "fp16_amp",
        "optimizer": "AdamW",
        "learning_rate": 0.0003,
        "weight_decay": 0.1,
        "scheduler": "cosine",
        "warmup_steps": 10,
        "min_lr_ratio": 0.1,
        "gradient_clip": 1.0,
    }
    for key, value in expected_training.items():
        _exact(training.get(key), value, field=f"training.{key}")
    _exact(training["effective_batch_size"] * training["context_length"], TOKENS_PER_STEP, field="effective_batch_tokens")

    checkpoints = _mapping(document.get("checkpoint_policy"), field="checkpoint_policy")
    _exact(checkpoints.get("steps"), list(CHECKPOINT_STEPS), field="checkpoint_policy.steps")
    _exact(checkpoints.get("scheduled_tokens"), list(CHECKPOINT_TOKENS), field="checkpoint_policy.scheduled_tokens")
    _exact(checkpoints.get("maximum_retained"), 3, field="checkpoint_policy.maximum_retained")

    evaluation = _mapping(document.get("evaluation_policy"), field="evaluation_policy")
    _exact(evaluation.get("quick_schedule"), list(QUICK_EVALUATION_STAGES), field="evaluation_policy.quick_schedule")
    _exact(evaluation.get("full_schedule"), list(FULL_EVALUATION_STAGES), field="evaluation_policy.full_schedule")
    _exact(evaluation.get("full_evaluation_during_training"), False, field="evaluation_policy.full_evaluation_during_training")

    resume = _mapping(document.get("resume_policy"), field="resume_policy")
    for key in ("resume_allowed", "automatic_resume", "automatic_retry", "cross_candidate_resume"):
        _exact(resume.get(key), False, field=f"resume_policy.{key}")
    approval = _mapping(document.get("approval_policy"), field="approval_policy")
    for key in ("retry_allowed", "extension_allowed", "publication_allowed"):
        _exact(approval.get(key), False, field=f"approval_policy.{key}")
    _exact(approval.get("single_use"), True, field="approval_policy.single_use")

    identities = _mapping(document.get("identity"), field="identity")
    _exact(identities.get("dataset_id"), "AIHUB-71748", field="identity.dataset_id")
    _exact(identities.get("tokenizer_id"), "operating-16k-v2/unigram-16k", field="identity.tokenizer_id")
    _exact(identities.get("model_name"), "DohaLM-Tiny", field="identity.model_name")
    for key in (
        "dataset_fingerprint", "split_fingerprint", "packing_fingerprint",
        "tokenizer_fingerprint", "model_fingerprint", "initialization_fingerprint",
    ):
        if not isinstance(identities.get(key), str) or FINGERPRINT_PATTERN.fullmatch(identities[key]) is None:
            raise TrainingError("CANDIDATE_B_IDENTITY_INVALID", f"identity.{key}가 유효하지 않습니다.")

    paths = _mapping(document.get("paths"), field="paths")
    for key in (
        "train_dataset", "evaluation_dataset", "tokenizer_model", "corpus_manifest",
        "split_manifest", "local_dataset_config", "output_logical_root",
        "readiness_logical_root", "failure_logical_root",
    ):
        _relative_path(paths.get(key), field=f"paths.{key}")
    _exact(paths.get("path_root"), "configured_external", field="paths.path_root")

    publication = _mapping(document.get("publication_policy"), field="publication_policy")
    if any(publication.get(key) is not False for key in ("checkpoint", "model", "dataset", "raw_log", "generated_sample")):
        raise TrainingError("CANDIDATE_B_PUBLICATION_FORBIDDEN", "Candidate B publication은 승인되지 않았습니다.")


def _identity_from_readiness(value: dict[str, Any]) -> dict[str, Any]:
    identity = _mapping(value.get("identity"), field="readiness.identity")
    initialization = _mapping(value.get("initialization"), field="readiness.initialization")
    required = {
        "dataset_id": identity.get("dataset_id"),
        "dataset_version": identity.get("dataset_version"),
        "source_split": identity.get("source_split"),
        "dataset_fingerprint": identity.get("training_lineage_fingerprint"),
        "source_lineage_fingerprint": identity.get("source_lineage_fingerprint"),
        "pii_fingerprint": identity.get("pii_fingerprint"),
        "split_fingerprint": identity.get("split_fingerprint"),
        "tokenization_fingerprint": identity.get("tokenization_fingerprint"),
        "packing_fingerprint": identity.get("packing_fingerprint"),
        "evaluation_fingerprint": identity.get("evaluation_fingerprint"),
        "tokenizer_id": identity.get("tokenizer_id"),
        "tokenizer_fingerprint": identity.get("tokenizer_fingerprint"),
        "model_name": identity.get("model_name"),
        "model_parameters": identity.get("model_parameters"),
        "model_fingerprint": identity.get("model_fingerprint"),
        "initialization_fingerprint": initialization.get("initialization_fingerprint"),
    }
    for key in (
        "dataset_fingerprint", "source_lineage_fingerprint", "pii_fingerprint",
        "split_fingerprint", "tokenization_fingerprint", "packing_fingerprint",
        "evaluation_fingerprint", "tokenizer_fingerprint", "model_fingerprint",
        "initialization_fingerprint",
    ):
        if not isinstance(required.get(key), str) or FINGERPRINT_PATTERN.fullmatch(required[key]) is None:
            raise TrainingError("CANDIDATE_B_IDENTITY_INVALID", f"Readiness identity {key}가 유효하지 않습니다.")
    return required


def validate_candidate_b_example(example: dict[str, Any]) -> None:
    """Validate every execution-relevant value in the versioned source config."""
    expected = {
        "schema_version": "1.0",
        "candidate_id": CANDIDATE_ID,
        "training_stage": TRAINING_STAGE,
        "execution_mode": "inspection_only",
        "budget_candidate": "candidate_b_25m",
        "token_budget": TOKEN_BUDGET,
        "tokens_per_optimizer_step": TOKENS_PER_STEP,
        "max_steps": MAX_STEPS,
        "scheduled_tokens": SCHEDULED_TOKENS,
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 4,
        "learning_rate": 0.0003,
        "weight_decay": 0.1,
        "scheduler_type": "cosine",
        "warmup_steps": 10,
        "min_lr_ratio": 0.1,
        "max_grad_norm": 1.0,
        "seed": SEED,
        "device": "cuda",
        "use_amp": True,
        "publish_allowed": False,
        "redistribution_allowed": False,
        "model_release_allowed": False,
    }
    for key, value in expected.items():
        _exact(example.get(key), value, field=f"example.{key}")
    initialization = _mapping(example.get("initialization"), field="example.initialization")
    for key, value in {
        "mode": "fresh_seed_17", "seed": SEED, "parent_checkpoint": None,
        "candidate_a_checkpoint_used": False, "optimizer_state_reused": False,
        "scheduler_state_reused": False, "sampler_state_reused": False,
    }.items():
        _exact(initialization.get(key), value, field=f"example.initialization.{key}")
    evaluation = _mapping(example.get("evaluation_policy"), field="example.evaluation_policy")
    _exact(evaluation.get("quick_schedule"), list(QUICK_EVALUATION_STAGES), field="example.evaluation_policy.quick_schedule")
    _exact(evaluation.get("full_schedule"), list(FULL_EVALUATION_STAGES), field="example.evaluation_policy.full_schedule")
    _exact(evaluation.get("full_evaluation_during_training"), False, field="example.evaluation_policy.full_evaluation_during_training")
    checkpoints = _mapping(example.get("checkpoint_policy"), field="example.checkpoint_policy")
    _exact(checkpoints.get("steps"), list(CHECKPOINT_STEPS), field="example.checkpoint_policy.steps")
    _exact(checkpoints.get("scheduled_tokens"), list(CHECKPOINT_TOKENS), field="example.checkpoint_policy.scheduled_tokens")
    resume = _mapping(example.get("resume_policy"), field="example.resume_policy")
    for key in ("resume_allowed", "automatic_resume", "automatic_retry", "cross_candidate_resume"):
        _exact(resume.get(key), False, field=f"example.resume_policy.{key}")
    approval = _mapping(example.get("approval"), field="example.approval")
    _exact(approval.get("status"), "not_approved", field="example.approval.status")
    _exact(approval.get("execution_allowed"), False, field="example.approval.execution_allowed")
    for key in ("automatic_extension", "automatic_retry"):
        _exact(approval.get(key), False, field=f"example.approval.{key}")


def resolve_candidate_b_config(
    example_path: Path,
    local_binding_path: Path,
    readiness_manifest_path: Path,
    *,
    allow_placeholder_run_id: bool = True,
) -> dict[str, Any]:
    """Resolve versioned policy and ignored local binding without exposing absolute paths."""
    example = _load_yaml(example_path, code="CANDIDATE_B_CONFIG_INVALID")
    binding = _load_yaml(local_binding_path, code="CANDIDATE_B_LOCAL_BINDING_MISSING")
    readiness = _load_yaml(readiness_manifest_path, code="CANDIDATE_B_READINESS_MANIFEST_INVALID")
    if binding.get("schema_version") != "1.0" or binding.get("binding_type") != "candidate_b_local_binding":
        raise TrainingError("CANDIDATE_B_LOCAL_BINDING_INVALID", "Candidate B local binding schema가 유효하지 않습니다.")
    validate_candidate_b_example(example)

    run_id = binding.get("run_id")
    if not isinstance(run_id, str):
        raise TrainingError("CANDIDATE_B_RUN_ID_INVALID", "local binding run_id가 필요합니다.")
    output_root = _relative_path(binding.get("output_logical_root"), field="local_binding.output_logical_root")
    readiness_root = _relative_path(binding.get("readiness_logical_root"), field="local_binding.readiness_logical_root")
    failure_root = _relative_path(binding.get("failure_logical_root"), field="local_binding.failure_logical_root")
    local_dataset_config = _relative_path(binding.get("local_dataset_config"), field="local_binding.local_dataset_config")

    model = ModelConfig()
    identity = _identity_from_readiness(readiness)
    readiness_identity_fingerprint = checksum_value({
        "identity": readiness.get("identity"),
        "baseline": readiness.get("baseline"),
        "budget": readiness.get("budget"),
        "initialization": readiness.get("initialization"),
    })
    document = {
        "schema_version": "1.0",
        "config_type": "candidate_b_resolved",
        "candidate_id": CANDIDATE_ID,
        "run_id": run_id,
        "training_stage": TRAINING_STAGE,
        "model": model.to_dict(),
        "identity": identity,
        "initialization": {
            "mode": "fresh",
            "seed": SEED,
            "parent_checkpoint": None,
            "candidate_a_checkpoint_used": False,
            "candidate_a_state_reused": False,
        },
        "budget": {
            "requested_tokens": TOKEN_BUDGET,
            "tokens_per_optimizer_step": TOKENS_PER_STEP,
            "optimizer_steps": MAX_STEPS,
            "scheduled_tokens": SCHEDULED_TOKENS,
            "equivalent_epoch": SCHEDULED_TOKENS / 71_307_940,
        },
        "training": {
            "micro_batch_size": 2,
            "gradient_accumulation_steps": 4,
            "effective_batch_size": 8,
            "context_length": 256,
            "precision": "fp16_amp",
            "optimizer": "AdamW",
            "learning_rate": 0.0003,
            "weight_decay": 0.1,
            "scheduler": "cosine",
            "warmup_steps": 10,
            "min_lr_ratio": 0.1,
            "gradient_clip": 1.0,
            "log_every": 1,
        },
        "checkpoint_policy": {
            "steps": list(CHECKPOINT_STEPS),
            "scheduled_tokens": list(CHECKPOINT_TOKENS),
            "maximum_retained": 3,
            "atomic_publish": True,
            "checksum_manifest": True,
        },
        "evaluation_policy": {
            "quick_schedule": list(QUICK_EVALUATION_STAGES),
            "full_schedule": list(FULL_EVALUATION_STAGES),
            "full_evaluation_during_training": False,
            "official_decision_profile": "full",
            "raw_text_storage": False,
            "token_id_storage": False,
        },
        "runtime_budget": dict(_mapping(example.get("wall_clock_budget"), field="example.wall_clock_budget")),
        "disk_budget": dict(_mapping(example.get("disk_budget"), field="example.disk_budget")),
        "system_safety": dict(_mapping(example.get("system_safety"), field="example.system_safety")),
        "resume_policy": {
            "resume_allowed": False,
            "automatic_resume": False,
            "automatic_retry": False,
            "cross_candidate_resume": False,
        },
        "approval_policy": {
            "single_use": True,
            "consume_before_optimizer_step": 1,
            "retry_allowed": False,
            "extension_allowed": False,
            "publication_allowed": False,
        },
        "paths": {
            "path_root": "configured_external",
            "local_dataset_config": local_dataset_config,
            "train_dataset": _relative_path(example.get("train_dataset"), field="example.train_dataset"),
            "evaluation_dataset": _relative_path(example.get("evaluation_dataset"), field="example.evaluation_dataset"),
            "tokenizer_model": _relative_path(example.get("tokenizer_model"), field="example.tokenizer_model"),
            "corpus_manifest": _relative_path(example.get("corpus_manifest"), field="example.corpus_manifest"),
            "split_manifest": _relative_path(example.get("split_manifest"), field="example.split_manifest"),
            "output_logical_root": output_root,
            "readiness_logical_root": readiness_root,
            "failure_logical_root": failure_root,
        },
        "publication_policy": {
            "checkpoint": False,
            "model": False,
            "dataset": False,
            "raw_log": False,
            "generated_sample": False,
        },
        "source_fingerprints": {
            "example_config": file_checksum(example_path),
            "local_binding": file_checksum(local_binding_path),
            "readiness_identity": readiness_identity_fingerprint,
        },
    }
    validate_candidate_b_scope(document, allow_placeholder_run_id=allow_placeholder_run_id)
    return {
        "document": document,
        "resolved_config_fingerprint": checksum_value(document),
        **document["source_fingerprints"],
    }


def write_resolved_candidate_b_config(path: Path, document: dict[str, Any]) -> None:
    """Atomically publish a text-only resolved config; existing files are never replaced."""
    if path.exists():
        raise TrainingError("CANDIDATE_B_RESOLVED_CONFIG_EXISTS", "Resolved config를 덮어쓸 수 없습니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise TrainingError("CANDIDATE_B_RESOLVED_CONFIG_WRITE_FAILED", "Resolved config publish에 실패했습니다.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_resolved_candidate_b_config(path: Path, *, allow_placeholder_run_id: bool = False) -> dict[str, Any]:
    document = _load_yaml(path, code="CANDIDATE_B_RESOLVED_CONFIG_INVALID")
    validate_candidate_b_scope(document, allow_placeholder_run_id=allow_placeholder_run_id)
    return document


def _git_command(root: Path, *args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    return result.returncode, result.stdout.rstrip(), result.stderr.rstrip()


def inspect_candidate_b_git(
    root: Path | None = None,
    *,
    command: Callable[..., tuple[int, str, str]] | None = None,
) -> dict[str, Any]:
    """Return immutable-commit evidence without mutating Git state."""
    base = repository_root() if root is None else root.resolve()
    invoke = command or (lambda *args: _git_command(base, *args))
    branch_code, branch, _ = invoke("symbolic-ref", "--quiet", "--short", "HEAD")
    head_code, head, _ = invoke("rev-parse", "HEAD")
    status_code, status, _ = invoke("status", "--porcelain=v1", "--untracked-files=all")
    upstream_code, upstream, _ = invoke("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    upstream_head_code, upstream_head, _ = invoke("rev-parse", "@{upstream}")
    remote_code, remote_url, _ = invoke("remote", "get-url", "origin")
    remote_contains_code, remote_contains, _ = invoke("branch", "-r", "--contains", head)

    status_lines = [line for line in status.splitlines() if line]
    staged = any(len(line) >= 2 and line[0] not in {" ", "?"} for line in status_lines)
    modified = any(len(line) >= 2 and line[1] not in {" ", "?"} for line in status_lines)
    untracked = any(line.startswith("??") for line in status_lines)
    sanitized_remote = re.sub(r"(https?://)[^/@]+@", r"\1", remote_url)
    repository_identity = checksum_value({"remote": sanitized_remote}) if remote_code == 0 and sanitized_remote else None
    remote_branches = [line.strip() for line in remote_contains.splitlines() if line.strip()]
    head_exists_remote = remote_contains_code == 0 and bool(remote_branches)
    upstream_matches = upstream_code == 0 and upstream_head_code == 0 and upstream_head == head
    clean = status_code == 0 and not status_lines
    blockers: list[str] = []
    if branch_code != 0 or not branch:
        blockers.append("CANDIDATE_B_DETACHED_HEAD")
    if head_code != 0 or COMMIT_PATTERN.fullmatch(head) is None:
        blockers.append("CANDIDATE_B_GIT_COMMIT_MISSING")
    if staged:
        blockers.append("CANDIDATE_B_STAGED_CHANGES")
    if modified:
        blockers.append("CANDIDATE_B_MODIFIED_WORKTREE")
    if untracked:
        blockers.append("CANDIDATE_B_UNTRACKED_FILES")
    if upstream_code != 0 or not upstream:
        blockers.append("CANDIDATE_B_UPSTREAM_MISSING")
    elif not upstream_matches:
        blockers.append("CANDIDATE_B_UPSTREAM_MISMATCH")
    if not head_exists_remote:
        blockers.append("CANDIDATE_B_HEAD_NOT_ON_REMOTE")
    if remote_code != 0 or not repository_identity:
        blockers.append("CANDIDATE_B_REMOTE_IDENTITY_MISSING")
    return {
        "branch": branch or None,
        "commit": head or None,
        "remote": "origin" if remote_code == 0 else None,
        "remote_branch": upstream or None,
        "repository_identity": repository_identity,
        "tree_clean": clean,
        "staged_changes": staged,
        "modified_changes": modified,
        "untracked_changes": untracked,
        "upstream_matches": upstream_matches,
        "head_exists_remote": head_exists_remote,
        "blocking_codes": blockers,
    }


APPROVAL_REQUIRED_FIELDS = (
    "approval_id", "approval_type", "candidate_id", "run_id", "approved_action",
    "approved_optimizer_steps", "approved_scheduled_tokens", "approved_token_budget",
    "resolved_config_fingerprint", "dataset_fingerprint", "split_fingerprint",
    "packing_fingerprint", "tokenizer_fingerprint", "model_fingerprint",
    "initialization_fingerprint", "git_branch", "git_commit", "git_remote",
    "git_remote_branch", "git_tree_clean", "repository_identity", "output_logical_root",
    "approval_status", "issued_at", "expiry_policy", "single_use", "consumed",
    "consumed_at", "consumed_step", "publication_allowed", "resume_allowed",
    "retry_allowed", "extension_allowed",
)


def validate_candidate_b_approval(
    approval: dict[str, Any],
    resolved: dict[str, Any],
    resolved_fingerprint: str,
    git: dict[str, Any],
    *,
    now: dt.datetime | None = None,
) -> list[str]:
    blockers: list[str] = []
    for field in APPROVAL_REQUIRED_FIELDS:
        if field not in approval:
            blockers.append(f"CANDIDATE_B_APPROVAL_FIELD_MISSING_{field.upper()}")
    if blockers:
        return blockers
    expected = {
        "approval_type": "candidate_b_execution",
        "candidate_id": CANDIDATE_ID,
        "run_id": resolved["run_id"],
        "approved_action": APPROVED_ACTION,
        "approved_optimizer_steps": MAX_STEPS,
        "approved_scheduled_tokens": SCHEDULED_TOKENS,
        "approved_token_budget": TOKEN_BUDGET,
        "resolved_config_fingerprint": resolved_fingerprint,
        "dataset_fingerprint": resolved["identity"]["dataset_fingerprint"],
        "split_fingerprint": resolved["identity"]["split_fingerprint"],
        "packing_fingerprint": resolved["identity"]["packing_fingerprint"],
        "tokenizer_fingerprint": resolved["identity"]["tokenizer_fingerprint"],
        "model_fingerprint": resolved["identity"]["model_fingerprint"],
        "initialization_fingerprint": resolved["identity"]["initialization_fingerprint"],
        "git_branch": git.get("branch"),
        "git_commit": git.get("commit"),
        "git_remote": git.get("remote"),
        "git_remote_branch": git.get("remote_branch"),
        "git_tree_clean": True,
        "repository_identity": git.get("repository_identity"),
        "output_logical_root": resolved["paths"]["output_logical_root"],
        "single_use": True,
        "consumed": False,
        "consumed_at": None,
        "consumed_step": None,
        "publication_allowed": False,
        "resume_allowed": False,
        "retry_allowed": False,
        "extension_allowed": False,
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            blockers.append(f"CANDIDATE_B_APPROVAL_{key.upper()}_MISMATCH")
    if approval.get("approval_status") != "approved":
        blockers.append("CANDIDATE_B_EXECUTION_APPROVAL_MISSING")
    if not approval.get("approval_id") or approval.get("issued_at") is None:
        blockers.append("CANDIDATE_B_APPROVAL_ISSUANCE_INCOMPLETE")
    expires_at = approval.get("expires_at")
    expiry_policy = approval.get("expiry_policy")
    if expires_at is None and expiry_policy != "invalidated_by_config_commit_or_run_change":
        blockers.append("CANDIDATE_B_APPROVAL_EXPIRY_POLICY_INVALID")
    if isinstance(expires_at, str):
        try:
            expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            current = now or dt.datetime.now(dt.timezone.utc)
            if expiry.tzinfo is None or expiry <= current:
                blockers.append("CANDIDATE_B_APPROVAL_EXPIRED")
        except ValueError:
            blockers.append("CANDIDATE_B_APPROVAL_EXPIRY_INVALID")
    return list(dict.fromkeys(blockers))


def resolve_candidate_b_external_path(resolved: dict[str, Any], logical: str) -> Path:
    paths = resolved["paths"]
    external_root, _ = resolve_local_paths(resolve_repository_path(paths["local_dataset_config"]))
    candidate = (external_root / _relative_path(logical, field="logical_path")).resolve()
    if candidate == external_root or external_root not in candidate.parents:
        raise TrainingError("CANDIDATE_B_OUTPUT_PATH_INVALID", "경로가 configured external root 밖입니다.")
    return candidate


def probe_candidate_b_output(resolved: dict[str, Any]) -> dict[str, Any]:
    """Verify write/fsync/rename/checksum/delete outside Git without creating a run."""
    validate_candidate_b_scope(resolved, allow_placeholder_run_id=False)
    repo = repository_root().resolve()
    output = resolve_candidate_b_external_path(resolved, resolved["paths"]["output_logical_root"])
    external_root, _ = resolve_local_paths(resolve_repository_path(resolved["paths"]["local_dataset_config"]))
    if output == repo or repo in output.parents:
        raise TrainingError("CANDIDATE_B_OUTPUT_INSIDE_GIT", "Candidate B output은 Git 저장소 밖이어야 합니다.")
    if str(output).startswith("\\\\"):
        raise TrainingError("CANDIDATE_B_NETWORK_OUTPUT_FORBIDDEN", "Network output path는 승인되지 않았습니다.")
    if output.exists():
        raise TrainingError("CANDIDATE_B_OUTPUT_COLLISION", "Candidate B run output이 이미 존재합니다.")
    output_parent = output.parent.resolve()
    if external_root != output_parent and external_root not in output_parent.parents:
        raise TrainingError("CANDIDATE_B_OUTPUT_SYMLINK_ESCAPE", "Output parent가 external root 밖으로 해석됩니다.")
    output_parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output_parent).free
    minimum = int(resolved["disk_budget"]["minimum_free_bytes_before_start"])
    if free < minimum:
        raise TrainingError("CANDIDATE_B_DISK_BUDGET_NOT_SATISFIED", "시작 free disk가 10GiB 미만입니다.")

    probe_dir = output_parent / f".candidate-b-output-probe-{uuid.uuid4().hex}"
    failure_probe = output_parent / f".candidate-b-failure-probe-{uuid.uuid4().hex}"
    temporary = probe_dir / "payload.tmp"
    published = probe_dir / "payload.verified"
    payload = b"DohaLM-candidate-b-output-probe-v1\n"
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    try:
        probe_dir.mkdir()
        failure_probe.mkdir()
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, published)
        if published.read_bytes() != payload or file_checksum(published) != digest:
            raise TrainingError("CANDIDATE_B_OUTPUT_PROBE_CHECKSUM", "Output probe checksum이 일치하지 않습니다.")
        published.unlink()
        failure_probe.rmdir()
        probe_dir.rmdir()
    finally:
        temporary.unlink(missing_ok=True)
        published.unlink(missing_ok=True)
        if failure_probe.exists():
            failure_probe.rmdir()
        if probe_dir.exists():
            probe_dir.rmdir()
    return {
        "status": "output_probe_passed",
        "write": True,
        "fsync": True,
        "atomic_rename": True,
        "checksum_readback": True,
        "delete": True,
        "failure_directory": True,
        "outside_git": True,
        "network_path": False,
        "run_id_collision": False,
        "probe_deleted": not probe_dir.exists() and not failure_probe.exists(),
        "available_bytes": free,
        "minimum_free_bytes": minimum,
        "probe_checksum": digest,
        "output_logical_root": resolved["paths"]["output_logical_root"],
    }


def candidate_b_checkpoint_contract(step: int, resolved: dict[str, Any]) -> dict[str, Any]:
    if step not in CHECKPOINT_STEPS:
        raise TrainingError("CANDIDATE_B_CHECKPOINT_STEP_FORBIDDEN", "승인된 Candidate B checkpoint step이 아닙니다.")
    required = [
        "model_state", "optimizer_state", "scheduler_state", "amp_scaler_state",
        "current_step", "consumed_tokens", "sampler_state", "rng_state",
        "config_fingerprint", "dataset_fingerprint", "tokenizer_fingerprint",
        "model_fingerprint", "git_commit", "approval_id", "run_id", "checksum_manifest",
    ]
    return {
        "schema_version": "1.0",
        "step": step,
        "scheduled_tokens": step * TOKENS_PER_STEP,
        "required_fields": required,
        "resume_allowed": False,
        "automatic_resume": False,
        "run_id": resolved["run_id"],
    }


def validate_candidate_b_checkpoint_metadata(metadata: dict[str, Any], resolved: dict[str, Any]) -> None:
    """Validate Candidate B checkpoint metadata without creating or loading a bundle."""
    if not isinstance(metadata, dict):
        raise TrainingError("CANDIDATE_B_CHECKPOINT_SCHEMA_INVALID", "Checkpoint metadata는 mapping이어야 합니다.")
    step = metadata.get("current_step")
    if step not in CHECKPOINT_STEPS:
        raise TrainingError("CANDIDATE_B_CHECKPOINT_STEP_FORBIDDEN", "Checkpoint step이 Candidate B schedule 밖입니다.")
    expected = {
        "consumed_tokens": step * TOKENS_PER_STEP,
        "config_fingerprint": checksum_value(resolved),
        "dataset_fingerprint": resolved["identity"]["dataset_fingerprint"],
        "tokenizer_fingerprint": resolved["identity"]["tokenizer_fingerprint"],
        "model_fingerprint": resolved["identity"]["model_fingerprint"],
        "run_id": resolved["run_id"],
        "resume_allowed": False,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise TrainingError("CANDIDATE_B_CHECKPOINT_SCHEMA_INVALID", f"Checkpoint metadata mismatch: {key}")
    for key in (
        "model_state", "optimizer_state", "scheduler_state", "amp_scaler_state",
        "sampler_state", "rng_state", "git_commit", "approval_id", "checksum_manifest",
    ):
        if not metadata.get(key):
            raise TrainingError("CANDIDATE_B_CHECKPOINT_SCHEMA_INVALID", f"Checkpoint metadata missing: {key}")


def candidate_b_evaluation_hooks() -> dict[str, Any]:
    return {
        "quick": list(QUICK_EVALUATION_STAGES),
        "full": list(FULL_EVALUATION_STAGES),
        "full_evaluation_during_training": False,
        "full_is_separate_evaluation_only_stage": True,
        "training_checkpoint_mutation_allowed": False,
    }


def candidate_b_backend_identity() -> str:
    root = repository_root()
    paths = [
        root / "src/training/candidate_b.py",
        root / "src/training/candidate_b_backend.py",
        root / "scripts/training/run_candidate_b.py",
    ]
    available = {str(path.relative_to(root)).replace("\\", "/"): file_checksum(path) for path in paths if path.is_file()}
    return checksum_value(available)


def inspect_candidate_b_runtime() -> dict[str, Any]:
    """Collect read-only runtime facts; physical acknowledgements remain pending."""
    packages: dict[str, str | None] = {}
    for name in ("torch", "sentencepiece", "yaml"):
        try:
            module = importlib.import_module(name)
            packages[name] = str(getattr(module, "__version__", "installed"))
        except Exception:
            packages[name] = None
    cuda: dict[str, Any] = {
        "available": False,
        "device_name": None,
        "capability": None,
        "total_vram_bytes": None,
        "free_vram_bytes": None,
        "allocation_smoke_run": False,
    }
    try:
        torch = importlib.import_module("torch")
        cuda["available"] = bool(torch.cuda.is_available())
        if cuda["available"]:
            properties = torch.cuda.get_device_properties(0)
            cuda.update({
                "device_name": str(properties.name),
                "capability": list(torch.cuda.get_device_capability(0)),
                "total_vram_bytes": int(properties.total_memory),
            })
            try:
                free, _total = torch.cuda.mem_get_info(0)
                cuda["free_vram_bytes"] = int(free)
            except Exception:
                cuda["free_vram_bytes"] = None
    except Exception:
        pass
    report = {
        "schema_version": "1.0",
        "status": "runtime_read_only_inspected",
        "python_version": platform.python_version(),
        "python_supported": (3, 10) <= sys.version_info[:2] < (3, 13),
        "virtual_environment": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "cuda": cuda,
        "timeout_support": True,
        "signal_handling": "windows_cooperative_hard_stop",
        "physical_preflight_passed": False,
        "gpu_training_started": False,
        "cuda_allocation_smoke_run": False,
    }
    return {**report, "runtime_fingerprint": checksum_value(report)}


def inspect_candidate_b_readiness(
    *,
    resolved_config_path: Path | None,
    approval_path: Path | None,
    cpu_validation: dict[str, Any] | None = None,
    output_probe: dict[str, Any] | None = None,
    physical_preflight: dict[str, Any] | None = None,
    git: dict[str, Any] | None = None,
    allow_placeholder_run_id: bool = False,
) -> dict[str, Any]:
    blockers: list[str] = []
    resolved: dict[str, Any] | None = None
    resolved_fingerprint: str | None = None
    if resolved_config_path is None or not resolved_config_path.is_file():
        blockers.append("CANDIDATE_B_RESOLVED_CONFIG_MISSING")
    else:
        try:
            resolved = load_resolved_candidate_b_config(
                resolved_config_path, allow_placeholder_run_id=allow_placeholder_run_id,
            )
            resolved_fingerprint = checksum_value(resolved)
        except TrainingError as exc:
            blockers.append(exc.code)

    git_report = git or inspect_candidate_b_git()
    blockers.extend(git_report.get("blocking_codes", []))
    if resolved is not None and approval_path is not None and approval_path.is_file():
        approval = _load_yaml(approval_path, code="CANDIDATE_B_APPROVAL_INVALID")
        blockers.extend(validate_candidate_b_approval(approval, resolved, resolved_fingerprint or "", git_report))
    else:
        blockers.append("CANDIDATE_B_EXECUTION_APPROVAL_MISSING")
    cpu_validation_passed = bool(
        cpu_validation
        and cpu_validation.get("status") == "passed"
        and cpu_validation.get("optimizer_steps") == 0
        and cpu_validation.get("actual_approval_consumed") is False
        and cpu_validation.get("checkpoint_created") is False
    )
    if not cpu_validation_passed:
        blockers.append("CANDIDATE_B_CPU_VALIDATION_MISSING")
    if output_probe is None or output_probe.get("status") != "output_probe_passed":
        blockers.append("CANDIDATE_B_OUTPUT_PROBE_MISSING")
    required_physical = (
        "plugged_power", "adequate_cooling_and_ventilation", "windows_sleep_disabled",
        "no_restart_or_update_scheduled", "no_other_long_gpu_task",
    )
    if physical_preflight is None or any(physical_preflight.get(key) is not True for key in required_physical):
        blockers.append("CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING")

    blockers = list(dict.fromkeys(blockers))
    evidence = {
        "resolved_config_fingerprint": resolved_fingerprint,
        "backend_identity": candidate_b_backend_identity(),
        "git_commit": git_report.get("commit"),
        "blocking_codes": blockers,
        "cpu_validation_fingerprint": checksum_value(cpu_validation) if cpu_validation else None,
        "output_probe_fingerprint": checksum_value(output_probe) if output_probe else None,
        "physical_preflight_fingerprint": checksum_value(physical_preflight) if physical_preflight else None,
    }
    unresolved_without_expected = [
        code for code in blockers
        if code not in {
            "CANDIDATE_B_EXECUTION_APPROVAL_MISSING",
            "CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING",
            "CANDIDATE_B_MODIFIED_WORKTREE",
            "CANDIDATE_B_UNTRACKED_FILES",
            "CANDIDATE_B_STAGED_CHANGES",
            "CANDIDATE_B_UPSTREAM_MISSING",
            "CANDIDATE_B_UPSTREAM_MISMATCH",
            "CANDIDATE_B_HEAD_NOT_ON_REMOTE",
        }
    ]
    status = (
        "ready_for_execution" if not blockers
        else "backend_ready_awaiting_commit_preflight_and_approval" if not unresolved_without_expected
        else "backend_blocked"
    )
    return {
        "schema_version": "1.0",
        "status": status,
        "backend_implemented": True,
        "cpu_validation_passed": cpu_validation_passed,
        "runtime_preflight_pending": "CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING" in blockers,
        "execution_approval_pending": "CANDIDATE_B_EXECUTION_APPROVAL_MISSING" in blockers,
        "execution_allowed": not blockers,
        "candidate_b_training": "not_approved" if blockers else "approved_single_use",
        "training_started": False,
        "blocking_codes": blockers,
        "resolved_config_fingerprint": resolved_fingerprint,
        "backend_identity": evidence["backend_identity"],
        "git": git_report,
        "output_probe": output_probe,
        "readiness_fingerprint": checksum_value(evidence),
    }


def require_candidate_b_execution(report: dict[str, Any]) -> None:
    if report.get("execution_allowed") is not True or report.get("status") != "ready_for_execution":
        raise TrainingError(
            "CANDIDATE_B_EXECUTION_BLOCKED",
            f"Candidate B 실행 조건이 충족되지 않았습니다: {report.get('blocking_codes', [])}",
        )
