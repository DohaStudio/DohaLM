"""Fail-closed execution-plan validation for Pilot Pretraining."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import checksum_value, file_checksum
from src.runtime.paths import repository_root

from .errors import TrainingError
from .pilot_config import PilotPretrainingConfig
from .pilot_readiness import validate_pilot_readiness
from .pilot_pretraining import _lineage, resolve_pilot_path


FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SMOKE_MAX_OPTIMIZER_STEPS = 5
PILOT_MAX_OPTIMIZER_STEPS = 100
MINIMUM_FREE_BYTES = 5 * 1024**3


def probe_pilot_output(config: PilotPretrainingConfig) -> dict[str, Any]:
    """Perform a small write/rename/read/checksum/delete probe outside Git."""
    output = resolve_pilot_path(config, config.output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise TrainingError("PILOT_OUTPUT_EXISTS", "Smoke output 경로가 이미 존재합니다.")
    free = shutil.disk_usage(output.parent).free
    if free < MINIMUM_FREE_BYTES:
        raise TrainingError("PILOT_STORAGE_NOT_VERIFIED", "가용 공간이 5 GiB 미만입니다.")
    temporary = output.parent / f".pilot-write-probe-{uuid.uuid4().hex}.tmp"
    published = temporary.with_suffix(".verified")
    payload = b"DohaLM-pilot-output-probe-v1\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, published)
        if published.read_bytes() != payload or file_checksum(published) != f"sha256:{hashlib.sha256(payload).hexdigest()}":
            raise TrainingError("PILOT_STORAGE_NOT_VERIFIED", "write probe checksum이 일치하지 않습니다.")
        digest = file_checksum(published)
    finally:
        temporary.unlink(missing_ok=True)
        published.unlink(missing_ok=True)
    return {
        "capacity_verified": True, "output_path_write_verified": True, "atomic_rename_verified": True,
        "read_checksum_verified": True, "probe_deleted": not temporary.exists() and not published.exists(),
        "git_managed_path": False, "available_bytes": free, "minimum_free_bytes": MINIMUM_FREE_BYTES,
        "probe_checksum": digest,
    }


def _fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_PATTERN.fullmatch(value) is not None


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrainingError("PILOT_EXECUTION_MANIFEST_INVALID", "Pilot 실행 manifest를 읽을 수 없습니다.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise TrainingError("PILOT_EXECUTION_MANIFEST_INVALID", "Pilot 실행 manifest schema가 유효하지 않습니다.")
    return value


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository_root(), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def inspect_pilot_execution(config_path: Path, manifest_path: Path, roadmap_path: Path | None = None) -> dict[str, Any]:
    """Inspect a plan without resolving data paths, loading a model, or starting training."""

    config = PilotPretrainingConfig.from_yaml(config_path)
    manifest = _load_manifest(manifest_path)
    identity = manifest.get("identity", {}) if isinstance(manifest.get("identity"), dict) else {}
    source = manifest.get("source", {}) if isinstance(manifest.get("source"), dict) else {}
    environment = manifest.get("environment", {}) if isinstance(manifest.get("environment"), dict) else {}
    approval = manifest.get("execution_approval", {}) if isinstance(manifest.get("execution_approval"), dict) else {}
    readiness = manifest.get("readiness", {}) if isinstance(manifest.get("readiness"), dict) else {}
    storage = manifest.get("storage", {}) if isinstance(manifest.get("storage"), dict) else {}
    blockers: list[str] = []
    actual_readiness = validate_pilot_readiness(config_path, roadmap_path) if roadmap_path is not None else None

    actual_config_fingerprint = file_checksum(config_path)
    actual_model_fingerprint = checksum_value(config.model.to_dict())
    if identity.get("config_fingerprint") != actual_config_fingerprint:
        blockers.append("CONFIG_FINGERPRINT_MISMATCH")
    if identity.get("model_fingerprint") != actual_model_fingerprint:
        blockers.append("MODEL_FINGERPRINT_MISMATCH")
    if not _fingerprint(identity.get("pilot_dataset_fingerprint")):
        blockers.append("PILOT_DATASET_FINGERPRINT_MISSING")
    if not _fingerprint(identity.get("tokenizer_fingerprint")):
        blockers.append("TOKENIZER_FINGERPRINT_MISSING")
    smoke_only = approval.get("status") == "approved_smoke_only"
    runtime_revalidation = approval.get("purpose") == "pilot_v2_runtime_revalidation"
    pilot_100 = (
        approval.get("status") == "approved_pilot_100_steps"
        and approval.get("purpose") == "canonical_pilot_v2_100_step"
        and approval.get("maximum_optimizer_steps") == PILOT_MAX_OPTIMIZER_STEPS
        and approval.get("pilot_100_step_status") == "approved"
        and approval.get("full_pretraining_status") == "not_approved"
        and config.max_steps == PILOT_MAX_OPTIMIZER_STEPS
    )
    valid_smoke = (
        smoke_only
        and approval.get("maximum_optimizer_steps") == SMOKE_MAX_OPTIMIZER_STEPS
        and config.max_steps <= SMOKE_MAX_OPTIMIZER_STEPS
        and approval.get("pilot_100_step_status") == "not_approved"
    )
    if not (valid_smoke or pilot_100) or not approval.get("approved_by") or not approval.get("approved_at"):
        blockers.append("PILOT_EXECUTION_NOT_APPROVED")
    if not (config.max_steps <= SMOKE_MAX_OPTIMIZER_STEPS or config.max_steps == PILOT_MAX_OPTIMIZER_STEPS):
        blockers.append("PILOT_SMOKE_SCOPE_EXCEEDED")
    if approval.get("execution_completed") is True:
        blockers.append("PILOT_EXECUTION_ALREADY_COMPLETED")
    readiness_codes = readiness.get("blocking_codes") or []
    allowed_readiness_codes = ["RUNTIME_REVALIDATION_REQUIRED"] if runtime_revalidation else []
    allowed_readiness_statuses = {"ready_for_smoke_execution", "ready_awaiting_final_execution_approval"}
    if readiness.get("status") not in allowed_readiness_statuses or readiness_codes != allowed_readiness_codes:
        blockers.append("PILOT_READINESS_NOT_SATISFIED")
    if actual_readiness is not None:
        if readiness.get("evidence_fingerprint") != actual_readiness.get("evidence_fingerprint"):
            blockers.append("READINESS_FINGERPRINT_MISMATCH")
        actual_codes = [item["code"] for item in actual_readiness.get("blocking_reasons", [])]
        if actual_readiness.get("eligible") is not True and not (runtime_revalidation and actual_codes == ["RUNTIME_REVALIDATION_REQUIRED"]):
            blockers.append("PILOT_READINESS_INPUT_BLOCKED")
    if storage.get("capacity_verified") is not True or storage.get("output_path_write_verified") is not True:
        blockers.append("PILOT_STORAGE_NOT_VERIFIED")
    if not isinstance(source.get("git_commit"), str) or COMMIT_PATTERN.fullmatch(source["git_commit"]) is None:
        blockers.append("GIT_COMMIT_MISSING")
    elif source["git_commit"] != _git_value("rev-parse", "HEAD"):
        blockers.append("GIT_COMMIT_MISMATCH")
    if not isinstance(source.get("git_branch"), str) or not source["git_branch"]:
        blockers.append("GIT_BRANCH_MISSING")
    elif source["git_branch"] != _git_value("branch", "--show-current"):
        blockers.append("GIT_BRANCH_MISMATCH")
    for key in ("python_version", "torch_version", "cuda_version", "gpu_name"):
        if not environment.get(key):
            blockers.append(f"ENVIRONMENT_{key.upper()}_MISSING")
    try:
        actual_lineage = _lineage(config)
        if identity.get("training_dataset_fingerprint") != actual_lineage["dataset_fingerprint"]:
            blockers.append("PILOT_DATASET_FINGERPRINT_MISMATCH")
        if identity.get("tokenizer_fingerprint") != actual_lineage["tokenizer_fingerprint"]:
            blockers.append("TOKENIZER_FINGERPRINT_MISMATCH")
        if pilot_100:
            identity_fields = {
                "dataset_version": "dataset_version",
                "pilot_dataset_fingerprint": "pilot_dataset_fingerprint",
                "split_fingerprint": "split_fingerprint",
                "pii_fingerprint": "pii_fingerprint",
                "canonical_selection_contract": "canonical_selection_contract",
                "contract_fingerprint": "canonical_contract_fingerprint",
                "source_lineage_fingerprint": "source_lineage_fingerprint",
                "tokenization_fingerprint": "tokenization_fingerprint",
                "packing_fingerprint": "packing_fingerprint",
                "tokenizer_model_checksum": "tokenizer_model_checksum",
                "tokenizer_vocab_checksum": "tokenizer_vocab_checksum",
            }
            for manifest_key, lineage_key in identity_fields.items():
                if identity.get(manifest_key) != actual_lineage.get(lineage_key):
                    blockers.append(f"{manifest_key.upper()}_MISMATCH")
        prepared_root = resolve_pilot_path(config, config.corpus_manifest).parent
        if not (prepared_root / "COMPLETE.json").is_file():
            blockers.append("PILOT_DATASET_INCOMPLETE")
    except (OSError, RuntimeError, ValueError):
        blockers.append("PILOT_ARTIFACT_VALIDATION_FAILED")
    output_path = resolve_pilot_path(config, config.output_dir)
    if output_path.exists():
        blockers.append("PILOT_OUTPUT_EXISTS")

    return {
        "schema_version": "1.0",
        "status": "ready_for_execution" if not blockers else "blocked",
        "execution_allowed": not blockers,
        "blocking_codes": blockers,
        "config_fingerprint": actual_config_fingerprint,
        "model_fingerprint": actual_model_fingerprint,
        "manifest_status": manifest.get("manifest_status"),
        "max_steps": config.max_steps,
        "effective_batch_size": config.effective_batch_size,
        "inspection_only": True,
        "training_started": False,
        "execution_profile": "resource_smoke_max_5_steps" if config.max_steps <= 5 else "canonical_pilot_v2_100_steps",
        "readiness_blocking_codes": [item["code"] for item in actual_readiness["blocking_reasons"]] if actual_readiness else [],
    }


def require_pilot_execution_approval(report: dict[str, Any]) -> None:
    if report.get("execution_allowed") is not True:
        codes = report.get("blocking_codes", [])
        raise TrainingError("PILOT_EXECUTION_BLOCKED", f"Pilot 실행 승인이 충족되지 않았습니다: {codes}")
