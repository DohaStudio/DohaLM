"""Fail-closed planning and readiness checks for Full Pretraining."""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.data.checksums import checksum_value, file_checksum
from src.model import ModelConfig
from src.runtime.paths import resolve_repository_path

from .errors import TrainingError
from .pilot_pretraining import _lineage
from .config import TrainingConfig
from .source_state import _SourceStateInspectionError, _inspect_source_state


TRAIN_TOKEN_COUNT = 71_307_940
PACKED_SEQUENCE_COUNT = 278_547
TOKENS_PER_OPTIMIZER_STEP = 2_048
MAXIMUM_PLANNING_EPOCHS = 3.0
MAXIMUM_PLANNING_TOKENS = TRAIN_TOKEN_COUNT * 3
FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class FullPretrainingConfig:
    """Validated candidate config; it is not an execution approval."""

    train_dataset: str
    validation_dataset: str
    tokenizer_model: str
    corpus_manifest: str
    split_manifest: str
    output_dir: str
    path_root: str = "configured_external"
    local_dataset_config: str = "configs/local-datasets.yaml"
    budget_candidate: str = "candidate_a_10m"
    token_budget: int = 10_000_000
    tokens_per_optimizer_step: int = TOKENS_PER_OPTIMIZER_STEP
    max_steps: int = 4_883
    maximum_epochs: float = 0.14025
    micro_batch_size: int = 2
    gradient_accumulation_steps: int = 4
    learning_rate: float = 3e-4
    weight_decay: float = 0.1
    scheduler_type: str = "cosine"
    warmup_steps: int = 10
    min_lr_ratio: float = 0.1
    max_grad_norm: float = 1.0
    log_every: int = 1
    seed: int = 17
    device: str = "cuda"
    use_amp: bool = True
    initialization: dict[str, Any] = field(default_factory=dict)
    evaluation_policy: dict[str, Any] = field(default_factory=dict)
    checkpoint_policy: dict[str, Any] = field(default_factory=dict)
    retention_policy: dict[str, Any] = field(default_factory=dict)
    disk_budget: dict[str, Any] = field(default_factory=dict)
    wall_clock_budget: dict[str, Any] = field(default_factory=dict)
    system_safety: dict[str, Any] = field(default_factory=dict)
    local_experiment_only: bool = True
    publish_allowed: bool = False
    redistribution_allowed: bool = False
    model_release_allowed: bool = False
    resume_checkpoint: str | None = None
    resume_approval_status: str = "not_approved"
    model: ModelConfig = field(default_factory=ModelConfig)

    def __post_init__(self) -> None:
        for name in (
            "train_dataset", "validation_dataset", "tokenizer_model", "corpus_manifest",
            "split_manifest", "output_dir", "local_dataset_config",
        ):
            self._validate_relative_path(name, getattr(self, name))
        if self.resume_checkpoint is not None:
            self._validate_relative_path("resume_checkpoint", self.resume_checkpoint)
        if self.path_root not in {"repository", "configured_external"}:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "path_root가 유효하지 않습니다.")
        if not self.local_experiment_only or self.publish_allowed or self.redistribution_allowed or self.model_release_allowed:
            raise TrainingError("FULL_PRETRAINING_LOCAL_ONLY_VIOLATION", "Full Pretraining 후보는 local-only여야 합니다.")
        integers = {
            "token_budget": self.token_budget,
            "tokens_per_optimizer_step": self.tokens_per_optimizer_step,
            "max_steps": self.max_steps,
            "micro_batch_size": self.micro_batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "warmup_steps": self.warmup_steps,
            "log_every": self.log_every,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in integers.values()):
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "token·step·batch 값은 양의 정수여야 합니다.")
        if self.tokens_per_optimizer_step != self.effective_batch_size * self.model.context_length:
            raise TrainingError("FULL_PRETRAINING_TOKEN_BUDGET_MISMATCH", "step당 token 수가 batch×context와 일치하지 않습니다.")
        expected_steps = math.ceil(self.token_budget / self.tokens_per_optimizer_step)
        if self.max_steps != expected_steps:
            raise TrainingError("FULL_PRETRAINING_STEP_BUDGET_MISMATCH", "max_steps가 token budget 상한과 일치하지 않습니다.")
        if self.token_budget > MAXIMUM_PLANNING_TOKENS or self.maximum_epochs > MAXIMUM_PLANNING_EPOCHS:
            raise TrainingError("FULL_PRETRAINING_BUDGET_LIMIT", "준비 패키지의 최대 비교 범위는 3 epoch입니다.")
        scheduled_epoch = self.scheduled_tokens / TRAIN_TOKEN_COUNT
        if self.maximum_epochs + 1e-9 < scheduled_epoch:
            raise TrainingError("FULL_PRETRAINING_EPOCH_LIMIT", "maximum_epochs가 scheduled token 범위보다 작습니다.")
        if self.scheduler_type != "cosine" or not 0 <= self.min_lr_ratio <= 1:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "cosine scheduler와 유효한 min_lr_ratio가 필요합니다.")
        if self.warmup_steps > self.max_steps:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "warmup_steps는 max_steps 이하여야 합니다.")
        for name in ("initialization", "evaluation_policy", "checkpoint_policy", "retention_policy", "disk_budget", "wall_clock_budget", "system_safety"):
            if not isinstance(getattr(self, name), dict):
                raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", f"{name}는 mapping이어야 합니다.")

        self._validate_candidate_a_profile()

    def _validate_candidate_a_profile(self) -> None:
        exact = {
            "budget_candidate": (self.budget_candidate, "candidate_a_10m"),
            "token_budget": (self.token_budget, 10_000_000),
            "tokens_per_optimizer_step": (self.tokens_per_optimizer_step, 2_048),
            "max_steps": (self.max_steps, 4_883),
            "micro_batch_size": (self.micro_batch_size, 2),
            "gradient_accumulation_steps": (self.gradient_accumulation_steps, 4),
            "learning_rate": (self.learning_rate, 3e-4),
            "weight_decay": (self.weight_decay, 0.1),
            "scheduler_type": (self.scheduler_type, "cosine"),
            "warmup_steps": (self.warmup_steps, 10),
            "min_lr_ratio": (self.min_lr_ratio, 0.1),
            "max_grad_norm": (self.max_grad_norm, 1.0),
            "log_every": (self.log_every, 1),
            "seed": (self.seed, 17),
            "use_amp": (self.use_amp, True),
            "context_length": (self.model.context_length, 256),
        }
        changed = [name for name, (actual, expected) in exact.items() if actual != expected]
        if changed:
            raise TrainingError(
                "FULL_PRETRAINING_CANDIDATE_A_PROFILE_MISMATCH",
                f"Candidate A fixed profile mismatch: {changed}",
            )
        if self.initialization.get("mode") != "fresh_seed_17" or self.initialization.get("pilot_checkpoint_used") is not False:
            raise TrainingError(
                "FULL_PRETRAINING_INITIALIZATION_MISMATCH",
                "Candidate A requires fresh seed-17 initialization.",
            )
        if self.resume_checkpoint is not None and self.resume_approval_status != "approved_full_run_resume":
            raise TrainingError(
                "FULL_PRETRAINING_RESUME_NOT_APPROVED",
                "Full Run resume requires separate user approval.",
            )

    @staticmethod
    def _validate_relative_path(name: str, value: str) -> None:
        raw = value.replace("\\", "/")
        if not raw or PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute() or ".." in PurePosixPath(raw).parts:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", f"{name}은 안전한 상대경로여야 합니다.")

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    @property
    def scheduled_tokens(self) -> int:
        return self.max_steps * self.tokens_per_optimizer_step

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effective_batch_size"] = self.effective_batch_size
        value["scheduled_tokens"] = self.scheduled_tokens
        value["equivalent_epoch"] = self.scheduled_tokens / TRAIN_TOKEN_COUNT
        return value

    def to_training_config(self) -> TrainingConfig:
        """Build the exact Trainer config for Candidate A."""
        return TrainingConfig(
            batch_size=self.effective_batch_size,
            micro_batch_size=self.micro_batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            max_steps=self.max_steps,
            learning_rate=self.learning_rate,
            weight_decay=self.weight_decay,
            warmup_steps=self.warmup_steps,
            scheduler_type=self.scheduler_type,
            min_lr_ratio=self.min_lr_ratio,
            max_grad_norm=self.max_grad_norm,
            use_amp=self.use_amp,
            seed=self.seed,
            log_every=self.log_every,
            save_every=int(self.checkpoint_policy.get("interval_steps", 0)),
            output_dir="experiments/full-pretraining-candidate-a",
            device=self.device,
            num_workers=0,
            pin_memory=self.device == "cuda",
        )

    @property
    def initialization_fingerprint(self) -> str:
        return checksum_value({
            "mode": self.initialization.get("mode"),
            "seed": self.seed,
            "model_fingerprint": checksum_value(self.model.to_dict()),
            "pilot_checkpoint_used": False,
        })

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FullPretrainingConfig":
        try:
            value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "Full Pretraining config를 읽을 수 없습니다.") from exc
        if not isinstance(value, dict):
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "config root는 mapping이어야 합니다.")
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", f"알 수 없는 config field: {sorted(unknown)}")
        model_value = value.get("model", {})
        if not isinstance(model_value, dict):
            raise TrainingError("INVALID_FULL_PRETRAINING_CONFIG", "model은 mapping이어야 합니다.")
        value["model"] = ModelConfig(**model_value)
        return cls(**value)


def estimate_training_budget(token_target: int) -> dict[str, int | float]:
    """Return deterministic estimates based on the approved Pilot evidence."""
    if isinstance(token_target, bool) or not isinstance(token_target, int) or token_target <= 0:
        raise TrainingError("INVALID_FULL_PRETRAINING_BUDGET", "token target은 양의 정수여야 합니다.")
    steps = math.ceil(token_target / TOKENS_PER_OPTIMIZER_STEP)
    scheduled_tokens = steps * TOKENS_PER_OPTIMIZER_STEP
    return {
        "requested_tokens": token_target,
        "optimizer_steps": steps,
        "scheduled_tokens": scheduled_tokens,
        "equivalent_epoch": scheduled_tokens / TRAIN_TOKEN_COUNT,
        "packed_sequences": steps * 8,
    }


def resolve_full_pretraining_path(config: FullPretrainingConfig, value: str) -> Path:
    if config.path_root == "repository":
        return resolve_repository_path(value)
    external_root, _ = resolve_local_paths(resolve_repository_path(config.local_dataset_config))
    resolved = (external_root / value).resolve()
    if external_root not in resolved.parents:
        raise TrainingError("FULL_PRETRAINING_PATH_INVALID", "경로가 configured external root 밖입니다.")
    return resolved


def probe_full_pretraining_output(config: FullPretrainingConfig) -> dict[str, Any]:
    """Write, atomically publish, verify, and remove a small non-training probe."""
    output = resolve_full_pretraining_path(config, config.output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise TrainingError("FULL_PRETRAINING_OUTPUT_EXISTS", "Full Pretraining output 경로가 이미 존재합니다.")
    minimum_free = int(config.disk_budget.get("minimum_free_bytes_before_start", 0))
    free = shutil.disk_usage(output.parent).free
    if minimum_free <= 0 or free < minimum_free:
        raise TrainingError("FULL_PRETRAINING_DISK_BUDGET_NOT_SATISFIED", "가용 공간이 최소 예산보다 작습니다.")
    temporary = output.parent / f".full-pretraining-probe-{uuid.uuid4().hex}.tmp"
    published = temporary.with_suffix(".verified")
    payload = b"DohaLM-full-pretraining-output-probe-v1\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, published)
        digest = file_checksum(published)
        if published.read_bytes() != payload or digest != f"sha256:{hashlib.sha256(payload).hexdigest()}":
            raise TrainingError("FULL_PRETRAINING_OUTPUT_PROBE_FAILED", "output probe checksum이 일치하지 않습니다.")
    finally:
        temporary.unlink(missing_ok=True)
        published.unlink(missing_ok=True)
    return {
        "output_path_write_verified": True,
        "atomic_rename_verified": True,
        "read_checksum_verified": True,
        "probe_deleted": not temporary.exists() and not published.exists(),
        "available_bytes": free,
        "minimum_free_bytes": minimum_free,
        "probe_checksum": digest,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrainingError("FULL_PRETRAINING_MANIFEST_INVALID", "approval manifest를 읽을 수 없습니다.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise TrainingError("FULL_PRETRAINING_MANIFEST_INVALID", "approval manifest schema가 유효하지 않습니다.")
    return value


def _approved(section: dict[str, Any]) -> bool:
    return section.get("approval_status") == "approved"


def inspect_full_pretraining_readiness(
    config_path: Path,
    manifest_path: Path,
    *,
    probe_output: bool = False,
) -> dict[str, Any]:
    """Inspect all final-approval conditions without starting training."""
    config = FullPretrainingConfig.from_yaml(config_path)
    manifest = _load_manifest(manifest_path)
    identity = manifest.get("identity", {}) if isinstance(manifest.get("identity"), dict) else {}
    approval = manifest.get("execution_approval", {}) if isinstance(manifest.get("execution_approval"), dict) else {}
    source = manifest.get("source", {}) if isinstance(manifest.get("source"), dict) else {}
    storage = manifest.get("storage", {}) if isinstance(manifest.get("storage"), dict) else {}
    blockers: list[str] = []
    actual_config_fingerprint = file_checksum(config_path)
    actual_model_fingerprint = checksum_value(config.model.to_dict())

    if identity.get("config_fingerprint") != actual_config_fingerprint:
        blockers.append("FULL_PRETRAINING_CONFIG_MISMATCH")
    if identity.get("model_fingerprint") != actual_model_fingerprint:
        blockers.append("FULL_PRETRAINING_MODEL_MISMATCH")
    for key in (
        "pilot_dataset_fingerprint", "training_lineage_fingerprint", "source_lineage_fingerprint",
        "pii_fingerprint", "split_fingerprint", "tokenization_fingerprint", "packing_fingerprint",
        "tokenizer_fingerprint", "tokenizer_model_checksum", "tokenizer_vocab_checksum",
    ):
        if not isinstance(identity.get(key), str) or FINGERPRINT_PATTERN.fullmatch(identity[key]) is None:
            blockers.append(f"{key.upper()}_MISSING")

    gates = manifest.get("gates", {}) if isinstance(manifest.get("gates"), dict) else {}
    expected_gates = {"0": "approved", **{str(value): "passed" for value in range(1, 8)}}
    if gates != expected_gates:
        blockers.append("FULL_PRETRAINING_GATES_NOT_SATISFIED")
    pilot = manifest.get("pilot_evidence", {}) if isinstance(manifest.get("pilot_evidence"), dict) else {}
    if not (
        pilot.get("run_id") == "PILOT-100-V2-20260727-0001"
        and pilot.get("status") == "completed_pilot_100_steps"
        and pilot.get("runtime_validation") == "passed"
        and pilot.get("checkpoint_resume") == "passed"
        and pilot.get("execution_approval") == "consumed"
    ):
        blockers.append("PILOT_SUCCESS_EVIDENCE_MISSING")

    try:
        lineage = _lineage(config)  # Full config intentionally shares the canonical artifact path contract.
        comparisons = {
            "dataset_version": "dataset_version",
            "canonical_selection_contract": "canonical_selection_contract",
            "pilot_dataset_fingerprint": "pilot_dataset_fingerprint",
            "training_lineage_fingerprint": "dataset_fingerprint",
            "source_lineage_fingerprint": "source_lineage_fingerprint",
            "pii_fingerprint": "pii_fingerprint",
            "split_fingerprint": "split_fingerprint",
            "tokenization_fingerprint": "tokenization_fingerprint",
            "packing_fingerprint": "packing_fingerprint",
            "tokenizer_fingerprint": "tokenizer_fingerprint",
            "tokenizer_model_checksum": "tokenizer_model_checksum",
            "tokenizer_vocab_checksum": "tokenizer_vocab_checksum",
        }
        for manifest_key, lineage_key in comparisons.items():
            if identity.get(manifest_key) != lineage.get(lineage_key):
                blockers.append(f"FULL_PRETRAINING_{manifest_key.upper()}_MISMATCH")
        if identity.get("source_record_count") != lineage.get("source_record_count"):
            blockers.append("FULL_PRETRAINING_SOURCE_RECORD_COUNT_MISMATCH")
        if identity.get("vocabulary_size") != 16_000 or identity.get("special_token_ids") != list(range(8)):
            blockers.append("FULL_PRETRAINING_TOKENIZER_CONTRACT_MISMATCH")
    except (OSError, RuntimeError, ValueError):
        blockers.append("FULL_PRETRAINING_ARTIFACT_VALIDATION_FAILED")

    policy_codes = {
        "budget": "FULL_PRETRAINING_BUDGET_NOT_APPROVED",
        "initialization": "FULL_PRETRAINING_INITIALIZATION_NOT_APPROVED",
        "training_config": "FULL_PRETRAINING_CONFIG_NOT_APPROVED",
        "evaluation_policy": "FULL_PRETRAINING_EVALUATION_NOT_APPROVED",
        "checkpoint_policy": "FULL_PRETRAINING_CHECKPOINT_NOT_APPROVED",
        "retention_policy": "FULL_PRETRAINING_RETENTION_NOT_APPROVED",
        "disk_budget": "FULL_PRETRAINING_DISK_BUDGET_NOT_APPROVED",
        "wall_clock_budget": "FULL_PRETRAINING_WALL_CLOCK_NOT_APPROVED",
        "system_safety": "FULL_PRETRAINING_SYSTEM_SAFETY_NOT_APPROVED",
    }
    for section_name, code in policy_codes.items():
        section = manifest.get(section_name, {})
        if not isinstance(section, dict) or not _approved(section):
            blockers.append(code)

    budget = manifest.get("budget", {}) if isinstance(manifest.get("budget"), dict) else {}
    if (
        budget.get("token_budget") != config.token_budget
        or budget.get("maximum_steps") != config.max_steps
        or budget.get("scheduled_tokens") != config.scheduled_tokens
        or budget.get("maximum_epochs") != config.maximum_epochs
    ):
        blockers.append("FULL_PRETRAINING_BUDGET_MISMATCH")
    initialization = manifest.get("initialization", {}) if isinstance(manifest.get("initialization"), dict) else {}
    if any(initialization.get(key) != config.initialization.get(key) for key in ("mode", "seed", "pilot_checkpoint_used")):
        blockers.append("FULL_PRETRAINING_INITIALIZATION_MISMATCH")
    if initialization.get("mode") == "pilot_checkpoint" and not isinstance(initialization.get("artifact_fingerprint"), str):
        blockers.append("FULL_PRETRAINING_INITIALIZATION_ARTIFACT_MISSING")
    if initialization.get("initialization_fingerprint") != config.initialization_fingerprint:
        blockers.append("FULL_PRETRAINING_INITIALIZATION_FINGERPRINT_MISMATCH")

    training_config = manifest.get("training_config", {}) if isinstance(manifest.get("training_config"), dict) else {}
    expected_training = {
        "optimizer": "AdamW",
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "scheduler": config.scheduler_type,
        "warmup_steps": config.warmup_steps,
        "min_lr_ratio": config.min_lr_ratio,
        "micro_batch_size": config.micro_batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "effective_batch_size": config.effective_batch_size,
        "context_length": config.model.context_length,
        "max_grad_norm": config.max_grad_norm,
        "precision": "fp16_amp" if config.use_amp else "fp32",
        "seed": config.seed,
    }
    if any(training_config.get(key) != value for key, value in expected_training.items()):
        blockers.append("FULL_PRETRAINING_TRAINING_CONFIG_MISMATCH")
    policy_pairs = {
        "evaluation_policy": config.evaluation_policy,
        "checkpoint_policy": config.checkpoint_policy,
        "retention_policy": config.retention_policy,
        "disk_budget": config.disk_budget,
        "wall_clock_budget": config.wall_clock_budget,
        "system_safety": config.system_safety,
    }
    for section_name, expected in policy_pairs.items():
        actual = manifest.get(section_name, {}) if isinstance(manifest.get(section_name), dict) else {}
        comparable = {key: value for key, value in expected.items() if key != "approval_status"}
        if any(actual.get(key) != value for key, value in comparable.items()):
            blockers.append(f"FULL_PRETRAINING_{section_name.upper()}_MISMATCH")

    if probe_output:
        storage = {**storage, **probe_full_pretraining_output(config)}
    required_storage = (
        storage.get("disk_budget_verified") is True
        and storage.get("output_path_write_verified") is True
        and storage.get("atomic_rename_verified") is True
        and storage.get("read_checksum_verified") is True
        and storage.get("probe_deleted") is True
        and int(storage.get("available_bytes", 0)) >= int(config.disk_budget.get("minimum_free_bytes_before_start", 0))
    )
    if not required_storage:
        blockers.append("FULL_PRETRAINING_STORAGE_NOT_VERIFIED")
    output = resolve_full_pretraining_path(config, config.output_dir)
    if output.exists():
        blockers.append("FULL_PRETRAINING_OUTPUT_EXISTS")

    source_state = None
    try:
        source_state = _inspect_source_state()
    except _SourceStateInspectionError:
        blockers.append("FULL_PRETRAINING_GIT_SOURCE_UNAVAILABLE")
    if not isinstance(source.get("git_commit"), str) or COMMIT_PATTERN.fullmatch(source["git_commit"]) is None:
        blockers.append("FULL_PRETRAINING_GIT_COMMIT_MISSING")
    elif source_state is None or source["git_commit"] != source_state.commit:
        blockers.append("FULL_PRETRAINING_GIT_COMMIT_MISMATCH")
    if source_state is None or source.get("git_branch") != source_state.branch:
        blockers.append("FULL_PRETRAINING_GIT_BRANCH_MISMATCH")
    if source_state is None or not source_state.clean:
        blockers.append("FULL_PRETRAINING_GIT_WORKTREE_DIRTY")
    source_verified = (
        source_state is not None
        and isinstance(source.get("git_commit"), str)
        and COMMIT_PATTERN.fullmatch(source["git_commit"]) is not None
        and source["git_commit"] == source_state.commit
        and source.get("git_branch") == source_state.branch
        and source_state.clean
    )
    environment = manifest.get("environment", {}) if isinstance(manifest.get("environment"), dict) else {}
    if any(not environment.get(key) for key in ("python_version", "torch_version", "cuda_version", "gpu_name")):
        blockers.append("FULL_PRETRAINING_ENVIRONMENT_INCOMPLETE")

    backend = manifest.get("execution_backend", {}) if isinstance(manifest.get("execution_backend"), dict) else {}
    if backend.get("status") != "implemented_and_validated":
        blockers.append("FULL_PRETRAINING_BACKEND_NOT_VALIDATED")

    final_approval_present = (
        approval.get("status") == "approved_full_pretraining"
        and approval.get("approved_by")
        and approval.get("approved_at")
        and approval.get("execution_allowed") is True
    )
    if not final_approval_present:
        blockers.append("FULL_PRETRAINING_NOT_APPROVED")
    else:
        preflight = approval.get("execution_preflight", {}) if isinstance(approval.get("execution_preflight"), dict) else {}
        required_preflight = (
            "windows_sleep_disabled", "no_restart_or_update_scheduled", "plugged_power",
            "adequate_cooling_and_ventilation", "nvidia_gpu_recognized", "cuda_available",
            "no_other_long_gpu_task",
        )
        if any(preflight.get(key) is not True for key in required_preflight):
            blockers.append("FULL_PRETRAINING_PREFLIGHT_NOT_ACKNOWLEDGED")
    if approval.get("consumed") is True:
        blockers.append("FULL_PRETRAINING_APPROVAL_CONSUMED")
    if approval.get("execution_started") is True or approval.get("execution_completed") is True:
        blockers.append("FULL_PRETRAINING_REEXECUTION_BLOCKED")

    blockers = list(dict.fromkeys(blockers))
    evidence = {
        "config_fingerprint": actual_config_fingerprint,
        "model_fingerprint": actual_model_fingerprint,
        "blocking_codes": blockers,
        "token_budget": config.token_budget,
        "maximum_steps": config.max_steps,
        "scheduled_tokens": config.scheduled_tokens,
        "source_commit": source["git_commit"] if source_verified else None,
        "source_worktree_clean": source_verified,
    }
    return {
        "schema_version": "1.0",
        "status": "ready_awaiting_final_execution_approval" if blockers == ["FULL_PRETRAINING_NOT_APPROVED"] else ("ready_for_execution" if not blockers else "blocked"),
        "execution_allowed": not blockers,
        "inspection_only": True,
        "training_started": False,
        "blocking_codes": blockers,
        "config_fingerprint": actual_config_fingerprint,
        "model_fingerprint": actual_model_fingerprint,
        "source_commit": source["git_commit"] if source_verified else None,
        "source_worktree_clean": source_verified,
        "readiness_fingerprint": checksum_value(evidence),
        "budget": estimate_training_budget(config.token_budget),
        "storage_probe": storage,
        "execution_backend_implemented": manifest.get("execution_backend", {}).get("status") == "implemented_and_validated",
    }


def require_full_pretraining_technical_readiness(report: dict[str, Any]) -> None:
    """Accept material readiness without turning it into execution approval."""

    if not isinstance(report, dict):
        raise TrainingError(
            "FULL_PRETRAINING_TECHNICAL_READINESS_BLOCKED",
            "A technical Full Pretraining readiness report is required.",
        )
    blockers = report.get("blocking_codes")
    approval_pending = blockers == ["FULL_PRETRAINING_NOT_APPROVED"]
    fully_approved = blockers == [] and report.get("execution_allowed") is True
    if fully_approved:
        # Preserve the established execution-approved report contract. Older
        # callers do not materialize the presentation-only status fields.
        return
    if (
        not approval_pending
        or report.get("status") != "ready_awaiting_final_execution_approval"
        or report.get("inspection_only") is not True
        or report.get("training_started") is not False
        or report.get("execution_allowed") is not False
    ):
        raise TrainingError(
            "FULL_PRETRAINING_TECHNICAL_READINESS_BLOCKED",
            "The material and configuration are not technically ready.",
        )


def require_full_pretraining_approval(report: dict[str, Any]) -> None:
    if report.get("execution_allowed") is not True:
        raise TrainingError(
            "FULL_PRETRAINING_EXECUTION_BLOCKED",
            f"Full Pretraining 실행 조건이 충족되지 않았습니다: {report.get('blocking_codes', [])}",
        )
