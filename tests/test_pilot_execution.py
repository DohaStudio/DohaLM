from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.data.checksums import checksum_value, file_checksum
from src.model import ModelConfig
from src.training import TrainingError
from src.training.pilot_execution import inspect_pilot_execution, require_pilot_execution_approval


FINGERPRINT = "sha256:" + "a" * 64


def manifest(config_path: Path, *, approved: bool = False) -> dict:
    return {
        "schema_version": "1.0",
        "manifest_status": "review",
        "identity": {
            "config_fingerprint": file_checksum(config_path),
            "model_fingerprint": checksum_value(ModelConfig().to_dict()),
            "pilot_dataset_fingerprint": FINGERPRINT if approved else None,
            "tokenizer_fingerprint": FINGERPRINT,
        },
        "source": {"git_commit": "a" * 40, "git_branch": "feat/pilot-pretraining"},
        "environment": {
            "python_version": "3.12.5", "torch_version": "2.7.1+cu118",
            "cuda_version": "11.8", "gpu_name": "NVIDIA GeForce RTX 3060 Ti",
        },
        "execution_approval": {
            "status": "approved" if approved else "not_approved",
            "approved_by": "user" if approved else None,
            "approved_at": "2026-07-27T00:00:00+09:00" if approved else None,
        },
        "readiness": {"status": "ready_for_execution" if approved else "blocked", "blocking_codes": [] if approved else ["PII_NOT_CLEARED"]},
        "storage": {"capacity_verified": True, "output_path_write_verified": approved},
    }


def write_manifest(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_plan_is_blocked_without_dataset_and_execution_approval(tmp_path: Path) -> None:
    config_path = Path("configs/pilot-pretraining.example.yaml")
    manifest_path = tmp_path / "manifest.yaml"
    write_manifest(manifest_path, manifest(config_path))
    report = inspect_pilot_execution(config_path, manifest_path)
    assert report["training_started"] is False
    assert {"PILOT_DATASET_FINGERPRINT_MISSING", "PILOT_EXECUTION_NOT_APPROVED", "PILOT_READINESS_NOT_SATISFIED"}.issubset(report["blocking_codes"])
    with pytest.raises(TrainingError, match="PILOT_EXECUTION_BLOCKED"):
        require_pilot_execution_approval(report)


def test_100_step_config_remains_blocked_even_with_generic_approval(tmp_path: Path) -> None:
    config_path = Path("configs/pilot-pretraining.example.yaml")
    manifest_path = tmp_path / "manifest.yaml"
    write_manifest(manifest_path, manifest(config_path, approved=True))
    report = inspect_pilot_execution(config_path, manifest_path)
    assert report["status"] == "blocked"
    assert report["execution_allowed"] is False
    assert "PILOT_SMOKE_SCOPE_EXCEEDED" in report["blocking_codes"]
    assert report["inspection_only"] is True and report["training_started"] is False
    with pytest.raises(TrainingError, match="PILOT_EXECUTION_BLOCKED"):
        require_pilot_execution_approval(report)


def test_changed_config_is_detected(tmp_path: Path) -> None:
    config_path = Path("configs/pilot-pretraining.example.yaml")
    value = manifest(config_path, approved=True)
    value["identity"]["config_fingerprint"] = FINGERPRINT
    manifest_path = tmp_path / "manifest.yaml"
    write_manifest(manifest_path, value)
    assert "CONFIG_FINGERPRINT_MISMATCH" in inspect_pilot_execution(config_path, manifest_path)["blocking_codes"]
