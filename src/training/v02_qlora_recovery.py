"""Fail-closed evaluation-only recovery for the completed DohaLM v0.2 run."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import checksum_value
from src.training import qlora_training as common
from src.training.v02_qlora_training import (
    FULL_ID,
    MODEL_ID,
    MODEL_REVISION,
    V02QLoRAError,
    _evaluate_adapter,
    _generation_prompts,
    expected_checkpoint_steps,
    validate_checkpoint_steps,
)

RECOVERY_ID = "DOHALM-V0.2-EVALUATION-RECOVERY-20260802-0001"
TRAINING_EXECUTION_SOURCE = "a4d3ab5e5adf1e4d41789c297bdb28f6ece9810f"
RECOVERABLE_FAILURE = "CHECKPOINT_SCHEDULE_INVALID"
EXPECTED_FINAL_ADAPTER_SHA256 = "b44220ce4a7c66e4ffdb53de73164c3eb347754f38b4a9c2af08b8474d5b73cc"
EXPECTED_EPOCHS = 2.0
EXPECTED_OPTIMIZER_STEPS = 1298
EXPECTED_SAVE_STEPS = 250


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V02QLoRAError("RECOVERY_ARTIFACT_INVALID") from None
    if not isinstance(value, dict):
        raise V02QLoRAError("RECOVERY_ARTIFACT_INVALID")
    return value


def _canonical_file_fingerprint(path: Path) -> str:
    return checksum_value(_read_json(path))


def _metrics(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise V02QLoRAError("TRAINING_COMPLETION_EVIDENCE_INVALID") from None
    if not lines:
        raise V02QLoRAError("TRAINING_COMPLETION_EVIDENCE_INVALID")
    try:
        values = [json.loads(line) for line in lines]
    except json.JSONDecodeError:
        raise V02QLoRAError("TRAINING_COMPLETION_EVIDENCE_INVALID") from None
    if any(not isinstance(value, dict) for value in values):
        raise V02QLoRAError("TRAINING_COMPLETION_EVIDENCE_INVALID")
    return values


def _tree_fingerprint(root: Path) -> str:
    if not root.is_dir():
        raise V02QLoRAError("FAILED_TRAINING_ARTIFACT_MISSING")
    values = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        values.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        })
    return checksum_value(values)


def training_process_absent() -> bool:
    """Return false when another v0.2 training command is visible in /proc."""
    proc = Path("/proc")
    if not proc.is_dir():
        return True
    current = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == current:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "ignore")
        except OSError:
            continue
        if "train_dohalm_v02_qlora" in command and "--mode full" in command:
            return False
    return True


def validate_training_completion(
    failed_root: Path, *, failure_code: str = RECOVERABLE_FAILURE,
) -> dict[str, object]:
    """Validate the immutable evidence that training ended before postprocessing."""
    if failure_code != RECOVERABLE_FAILURE:
        raise V02QLoRAError("RECOVERY_FAILURE_NOT_ELIGIBLE")
    final_adapter = failed_root / "final-adapter"
    metrics = _metrics(failed_root / "metrics.jsonl")
    metric = metrics[-1]
    state = _read_json(final_adapter / "trainer_state.json")
    unsafe_runtime = any(
        value.get("cuda_oom") is True
        or any(
            key in value and not math.isfinite(float(value[key]))
            for key in ("loss", "eval_loss", "train_loss")
        )
        for value in metrics
    )
    if (
        int(metric.get("global_step", -1)) != EXPECTED_OPTIMIZER_STEPS
        or not math.isclose(float(metric.get("epoch", -1)), EXPECTED_EPOCHS)
        or int(state.get("global_step", -1)) != EXPECTED_OPTIMIZER_STEPS
        or not math.isclose(float(state.get("epoch", -1)), EXPECTED_EPOCHS)
        or not math.isfinite(float(metric.get("train_loss", math.nan)))
        or unsafe_runtime
    ):
        raise V02QLoRAError("TRAINING_COMPLETION_EVIDENCE_INVALID")
    return {
        "training_completed": True,
        "epochs_completed": EXPECTED_EPOCHS,
        "optimizer_steps": EXPECTED_OPTIMIZER_STEPS,
        "training_runtime_seconds": float(metric.get("train_runtime", 0.0)),
        "train_loss": float(metric["train_loss"]),
        "failure_code": failure_code,
    }


def validate_checkpoint_inventory(
    failed_root: Path,
    *,
    expected_final_sha256: str = EXPECTED_FINAL_ADAPTER_SHA256,
) -> dict[str, object]:
    """Validate scheduled and terminal checkpoints without modifying any artifact."""
    checkpoints_root = failed_root / "checkpoints"
    if not checkpoints_root.is_dir():
        raise V02QLoRAError("CHECKPOINT_INVENTORY_INCOMPLETE")
    candidates = sorted(
        (path for path in checkpoints_root.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")),
        key=lambda path: int(path.name.rsplit("-", 1)[1]),
    )
    steps = [int(path.name.rsplit("-", 1)[1]) for path in candidates]
    validate_checkpoint_steps(
        steps, save_steps=EXPECTED_SAVE_STEPS, total_optimizer_steps=EXPECTED_OPTIMIZER_STEPS,
    )
    expected_names = {f"checkpoint-{step}" for step in expected_checkpoint_steps(
        save_steps=EXPECTED_SAVE_STEPS, total_optimizer_steps=EXPECTED_OPTIMIZER_STEPS,
    )}
    actual_names = {path.name for path in checkpoints_root.iterdir() if path.is_dir()}
    if actual_names != expected_names:
        raise V02QLoRAError("CHECKPOINT_INVENTORY_INCOMPLETE")

    inventory: list[dict[str, object]] = []
    for path, step in zip(candidates, steps, strict=True):
        validated = common.validate_checkpoint(path)
        state = _read_json(path / "trainer_state.json")
        adapter_config = _read_json(path / "adapter_config.json")
        if (
            int(state.get("global_step", -1)) != step
            or adapter_config.get("base_model_name_or_path") != MODEL_ID
        ):
            raise V02QLoRAError("CHECKPOINT_STEP_MISMATCH")
        model_sha = str(validated["checksums"]["adapter_model.safetensors"])
        inventory.append({
            "candidate": path.name,
            "step": step,
            "type": "terminal" if step == EXPECTED_OPTIMIZER_STEPS else "scheduled",
            "adapter_sha256": model_sha,
            "adapter_config_fingerprint": _canonical_file_fingerprint(path / "adapter_config.json"),
            "lora_parameter_fingerprint": f"sha256:{model_sha}",
            "base_model": MODEL_ID,
            "base_model_revision": MODEL_REVISION,
            "trainer_state_sha256": validated["checksums"]["trainer_state.json"],
            "total_bytes": validated["total_bytes"],
            "reload_validated": False,
        })

    final_root = failed_root / "final-adapter"
    final = common.validate_checkpoint(final_root)
    final_state = _read_json(final_root / "trainer_state.json")
    final_adapter_config = _read_json(final_root / "adapter_config.json")
    if (
        int(final_state.get("global_step", -1)) != EXPECTED_OPTIMIZER_STEPS
        or final_adapter_config.get("base_model_name_or_path") != MODEL_ID
    ):
        raise V02QLoRAError("FINAL_ADAPTER_STEP_MISMATCH")
    final_sha = str(final["checksums"]["adapter_model.safetensors"])
    if final_sha != expected_final_sha256:
        raise V02QLoRAError("FINAL_ADAPTER_CHECKSUM_MISMATCH")
    terminal = inventory[-1]
    final_config_fingerprint = _canonical_file_fingerprint(final_root / "adapter_config.json")
    equivalent = (
        terminal["step"] == EXPECTED_OPTIMIZER_STEPS
        and terminal["adapter_sha256"] == final_sha
        and terminal["adapter_config_fingerprint"] == final_config_fingerprint
        and terminal["lora_parameter_fingerprint"] == f"sha256:{final_sha}"
    )
    if not equivalent:
        raise V02QLoRAError("FINAL_ADAPTER_EQUIVALENCE_FAILED")
    inventory.append({
        "candidate": "final-adapter",
        "step": EXPECTED_OPTIMIZER_STEPS,
        "type": "final_adapter",
        "adapter_sha256": final_sha,
        "adapter_config_fingerprint": final_config_fingerprint,
        "lora_parameter_fingerprint": f"sha256:{final_sha}",
        "base_model": MODEL_ID,
        "base_model_revision": MODEL_REVISION,
        "trainer_state_sha256": final["checksums"]["trainer_state.json"],
        "total_bytes": final["total_bytes"],
        "reload_validated": False,
        "equivalent_to": f"checkpoint-{EXPECTED_OPTIMIZER_STEPS}",
    })
    return {
        "status": "valid",
        "save_steps": EXPECTED_SAVE_STEPS,
        "total_optimizer_steps": EXPECTED_OPTIMIZER_STEPS,
        "maximum_terminal_checkpoint_count": 1,
        "terminal_checkpoint_equivalent_to_final_adapter": True,
        "training_config_sha256": common.sha256_file(final_root / "training-config.yaml"),
        "candidates": inventory,
    }


def _selection_key(value: Mapping[str, object]) -> tuple[float, ...]:
    generation = value["generation"]
    assert isinstance(generation, Mapping)
    overall = generation["overall"]
    verdict = value["verdict"]
    assert isinstance(overall, Mapping) and isinstance(verdict, Mapping)
    rates = verdict["rates"]
    assert isinstance(rates, Mapping)
    return (
        -float(overall.get("character_f1", 0.0)),
        -float(overall.get("rouge_l", 0.0)),
        -float(rates.get("eos", 0.0)),
        float(rates.get("repetition", 1.0)),
        float(rates.get("incomplete", 1.0)),
        float(value["token_weighted_validation_loss"]),
    )


def select_candidate(evaluations: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    eligible = [
        name for name, value in evaluations.items()
        if value.get("verdict", {}).get("hard_blocker_clear") is True
    ]
    selected = min(eligible, key=lambda name: _selection_key(evaluations[name]), default=None)
    return {
        "selected_candidate": selected,
        "deployment_ready": selected is not None,
        "verdict": "READY" if selected is not None else "NEEDS_MODEL_IMPROVEMENT",
        "eligible_candidates": eligible,
        "selection_order": [
            "hard_blocker", "character_f1", "rouge_l", "eos",
            "repetition", "incomplete", "validation_loss",
        ],
    }


def _validate_recovery_package(root: Path) -> None:
    required = {
        "recovery-manifest.yaml", "checkpoint-inventory.json",
        "validation-loss-results.json", "generation-evaluation.json",
        "candidate-selection.json", "environment.json",
        "training-recovery-result.yaml", "checksums.sha256",
    }
    if not root.is_dir() or {path.name for path in root.iterdir()} != required:
        raise V02QLoRAError("RECOVERY_ARTIFACT_INVALID")
    for name in required - {"checksums.sha256"}:
        path = root / name
        try:
            value = (
                yaml.safe_load(path.read_text(encoding="utf-8"))
                if name.endswith((".yaml", ".yml"))
                else json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError):
            raise V02QLoRAError("RECOVERY_ARTIFACT_INVALID") from None
        if not isinstance(value, dict):
            raise V02QLoRAError("RECOVERY_ARTIFACT_INVALID")


def _write_recovery_package(
    output_root: Path,
    files: Mapping[str, object],
    *,
    before_publish: Callable[[], None] | None = None,
) -> Path:
    paths = common.ensure_unused_output(output_root / RECOVERY_ID)
    paths.staging.mkdir()
    try:
        for name, value in files.items():
            payload = (
                yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode("utf-8")
                if name.endswith((".yaml", ".yml"))
                else json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
            )
            with (paths.staging / name).open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        common.write_checksums(paths.staging)
        with (paths.staging / "checksums.sha256").open("rb") as handle:
            os.fsync(handle.fileno())
        if os.name != "nt":
            descriptor = os.open(paths.staging, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if before_publish is not None:
            before_publish()
        common.publish_staging(paths)
        if common.file_checksums(paths.final) != common._parse_checksum_file(paths.final):
            raise V02QLoRAError("RECOVERY_CHECKSUM_MISMATCH")
        _validate_recovery_package(paths.final)
        return paths.final
    except Exception:
        common.quarantine_stability_publication(paths)
        raise


def recover_dohalm_v02_training_evaluation(
    *,
    failed_root: Path,
    output_root: Path,
    config_path: Path,
    cache_root: Path,
    context: Any,
    sidecar_root: Path,
    repository: Path,
    evaluation_governance_head: str,
    environment: Mapping[str, object],
    evaluator: Callable[..., dict[str, object]] = _evaluate_adapter,
    process_absent: Callable[[], bool] = training_process_absent,
) -> dict[str, object]:
    """Evaluate a completed failed artifact without entering any training surface."""
    if failed_root.name != f"{FULL_ID}.failed":
        raise V02QLoRAError("FAILED_TRAINING_ARTIFACT_ID_MISMATCH")
    if not process_absent():
        raise V02QLoRAError("TRAINING_PROCESS_ACTIVE")
    recovery_paths = common.artifact_paths(output_root / RECOVERY_ID)
    if any(path.exists() for path in (recovery_paths.final, recovery_paths.staging, recovery_paths.failed)):
        raise V02QLoRAError("RECOVERY_OUTPUT_CONFLICT")
    git = common.verify_git_identity(repository, expected_head=evaluation_governance_head)
    before = _tree_fingerprint(failed_root)
    completion = validate_training_completion(failed_root)
    inventory = validate_checkpoint_inventory(failed_root)
    if common.sha256_file(config_path) != common.sha256_file(failed_root / "final-adapter" / "training-config.yaml"):
        raise V02QLoRAError("TRAINING_CONFIG_MISMATCH")
    resolved_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    tokenizer, base = common.load_tokenizer_and_model(resolved_config, cache_dir=cache_root)
    del base
    common.release_cuda()
    if int(tokenizer.eos_token_id) != 151645 or int(tokenizer.pad_token_id) != 151643:
        raise V02QLoRAError("EVALUATION_SPECIAL_TOKEN_MISMATCH")
    prompts, prompt_fingerprint = _generation_prompts(sidecar_root)
    prompt_identities = [{
        "sample_hash": prompt.sample_hash,
        "category": prompt.category,
        "length_bucket": prompt.length_bucket,
        "prompt_sha256": hashlib.sha256(prompt.prompt.encode("utf-8")).hexdigest(),
        "reference_sha256": hashlib.sha256(prompt.reference.encode("utf-8")).hexdigest(),
    } for prompt in prompts]

    evaluations: dict[str, dict[str, object]] = {}
    candidate_roots = [failed_root / "checkpoints" / f"checkpoint-{step}" for step in expected_checkpoint_steps(
        save_steps=EXPECTED_SAVE_STEPS, total_optimizer_steps=EXPECTED_OPTIMIZER_STEPS,
    )]
    for adapter_root in candidate_roots:
        result = evaluator(
            config=resolved_config,
            cache_root=cache_root,
            adapter_root=adapter_root,
            validation=context.validation,
            prompts=prompts,
            tokenizer=tokenizer,
        )
        result["reload_validated"] = True
        evaluations[adapter_root.name] = result
    terminal_name = f"checkpoint-{EXPECTED_OPTIMIZER_STEPS}"
    evaluations["final-adapter"] = {
        **evaluations[terminal_name],
        "generation_evaluation_reused_for_equivalent_artifact": True,
        "source_candidate": terminal_name,
        "equivalent_candidate": "final-adapter",
    }
    selection = select_candidate(evaluations)
    after = _tree_fingerprint(failed_root)
    if before != after:
        raise V02QLoRAError("FAILED_TRAINING_ARTIFACT_MODIFIED")

    for item in inventory["candidates"]:
        item["reload_validated"] = True
        if item["candidate"] == "final-adapter":
            item["reload_validation_reused_for_equivalent_artifact"] = True
    recovery_manifest = {
        "schema_version": 1,
        "recovery_id": RECOVERY_ID,
        "run_id": FULL_ID,
        "training_execution_source": TRAINING_EXECUTION_SOURCE,
        "evaluation_governance_head": evaluation_governance_head,
        "original_failure_code": RECOVERABLE_FAILURE,
        "original_failure_preserved": True,
        "failed_artifact_fingerprint_before": before,
        "failed_artifact_fingerprint_after": after,
        "training_calls": 0,
        "backward_calls": 0,
        "optimizer_steps_added": 0,
        "scheduler_steps": 0,
        "checkpoint_writes": 0,
        "adapter_writes": 0,
        "checkpoint_deletion": False,
        "retention_policy_application": False,
        "prompt_selection_fingerprint": prompt_fingerprint,
        "evaluation_subset": {
            "count": len(prompt_identities),
            "fingerprint": checksum_value(prompt_identities),
            "records": prompt_identities,
            "category_balanced": True,
            "length_balanced": True,
            "raw_text_stored": False,
        },
        "source_identity": dict(context.dataset_identity),
        "git": git,
    }
    manifest_fingerprint = checksum_value(recovery_manifest)
    recovery_manifest["manifest_fingerprint"] = manifest_fingerprint
    lifecycle = {
        **completion,
        "training_status": "completed",
        "postprocessing_status": "recovered",
        "deployment_status": "evaluated",
        "original_failure_preserved": True,
        **selection,
    }
    artifact = _write_recovery_package(output_root, {
        "recovery-manifest.yaml": recovery_manifest,
        "checkpoint-inventory.json": inventory,
        "validation-loss-results.json": {
            name: value["validation"] for name, value in evaluations.items()
        },
        "generation-evaluation.json": evaluations,
        "candidate-selection.json": selection,
        "environment.json": dict(environment),
        "training-recovery-result.yaml": lifecycle,
    })
    return {
        "status": "completed",
        "recovery_id": RECOVERY_ID,
        "artifact": str(artifact),
        "inventory": inventory,
        "evaluations": evaluations,
        "selection": selection,
        "manifest_fingerprint": manifest_fingerprint,
        "checksum_manifest_sha256": common.sha256_file(artifact / "checksums.sha256"),
        "training_reexecution": False,
        "optimizer_steps_added": 0,
    }
