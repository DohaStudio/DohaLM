from __future__ import annotations

import math
from collections import namedtuple
from pathlib import Path

import pytest
import yaml

from src.data.checksums import file_checksum
from src.training import TrainingError
from src.training.full_pretraining import (
    MAXIMUM_PLANNING_TOKENS,
    FullPretrainingConfig,
    estimate_training_budget,
    inspect_full_pretraining_readiness,
    probe_full_pretraining_output,
    require_full_pretraining_approval,
)


CONFIG_PATH = Path("configs/full-pretraining.example.yaml")
MANIFEST_PATH = Path("docs/training/full-pretraining-approval.manifest.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def lineage_from_manifest(value: dict) -> dict:
    identity = value["identity"]
    return {
        "dataset_version": identity["dataset_version"],
        "canonical_selection_contract": identity["canonical_selection_contract"],
        "source_record_count": identity["source_record_count"],
        "pilot_dataset_fingerprint": identity["pilot_dataset_fingerprint"],
        "dataset_fingerprint": identity["training_lineage_fingerprint"],
        "source_lineage_fingerprint": identity["source_lineage_fingerprint"],
        "pii_fingerprint": identity["pii_fingerprint"],
        "split_fingerprint": identity["split_fingerprint"],
        "tokenization_fingerprint": identity["tokenization_fingerprint"],
        "packing_fingerprint": identity["packing_fingerprint"],
        "tokenizer_fingerprint": identity["tokenizer_fingerprint"],
        "tokenizer_model_checksum": identity["tokenizer_model_checksum"],
        "tokenizer_vocab_checksum": identity["tokenizer_vocab_checksum"],
    }


def approved_manifest() -> dict:
    value = load_yaml(MANIFEST_PATH)
    for name in (
        "budget", "initialization", "training_config", "evaluation_policy", "checkpoint_policy",
        "retention_policy", "disk_budget", "wall_clock_budget", "system_safety",
    ):
        value[name]["approval_status"] = "approved"
    value["storage"].update({
        "disk_budget_verified": True,
        "output_path_write_verified": True,
        "atomic_rename_verified": True,
        "read_checksum_verified": True,
        "probe_deleted": True,
        "available_bytes": 20 * 1024**3,
    })
    value["execution_approval"].update({
        "status": "approved_full_pretraining",
        "execution_allowed": True,
        "approved_by": "user",
        "approved_at": "2026-07-27T00:00:00+09:00",
        "execution_preflight": {
            "windows_sleep_disabled": True,
            "no_restart_or_update_scheduled": True,
            "plugged_power": True,
            "adequate_cooling_and_ventilation": True,
            "nvidia_gpu_recognized": True,
            "cuda_available": True,
            "no_other_long_gpu_task": True,
        },
        "consumed": False,
        "execution_started": False,
        "execution_completed": False,
    })
    return value


def inspect_with_mocks(tmp_path: Path, monkeypatch, value: dict) -> dict:
    manifest_path = tmp_path / "manifest.yaml"
    write_yaml(manifest_path, value)
    monkeypatch.setattr("src.training.full_pretraining._lineage", lambda _config: lineage_from_manifest(load_yaml(MANIFEST_PATH)))
    monkeypatch.setattr(
        "src.training.full_pretraining._git_value",
        lambda *args: "c3b778df31b9888ca6539b1d2b3c09faca6ec0e9" if args[0] == "rev-parse" else "feat/pilot-pretraining",
    )
    monkeypatch.setattr("src.training.full_pretraining.resolve_full_pretraining_path", lambda *_args: tmp_path / "new-run")
    return inspect_full_pretraining_readiness(CONFIG_PATH, manifest_path)


def test_budget_estimates_use_exact_step_ceiling() -> None:
    value = estimate_training_budget(10_000_000)
    assert value == {
        "requested_tokens": 10_000_000,
        "optimizer_steps": 4_883,
        "scheduled_tokens": 10_000_384,
        "equivalent_epoch": pytest.approx(0.14024222267534303),
        "packed_sequences": 39_064,
    }


def test_config_rejects_token_budget_above_three_epochs(tmp_path: Path) -> None:
    value = load_yaml(CONFIG_PATH)
    value["token_budget"] = MAXIMUM_PLANNING_TOKENS + 1
    value["max_steps"] = math.ceil(value["token_budget"] / 2_048)
    value["maximum_epochs"] = 3.1
    path = tmp_path / "config.yaml"
    write_yaml(path, value)
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_BUDGET_LIMIT"):
        FullPretrainingConfig.from_yaml(path)


def test_config_rejects_maximum_step_mismatch(tmp_path: Path) -> None:
    value = load_yaml(CONFIG_PATH)
    value["max_steps"] += 1
    path = tmp_path / "config.yaml"
    write_yaml(path, value)
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_STEP_BUDGET_MISMATCH"):
        FullPretrainingConfig.from_yaml(path)


def test_unapproved_package_and_pilot_only_approval_are_blocked(tmp_path: Path, monkeypatch) -> None:
    value = load_yaml(MANIFEST_PATH)
    value["execution_approval"].update({"status": "approved_pilot_100_steps", "execution_allowed": True, "approved_by": "user", "approved_at": "2026-07-27"})
    report = inspect_with_mocks(tmp_path, monkeypatch, value)
    assert report["execution_allowed"] is False and report["training_started"] is False
    assert "FULL_PRETRAINING_NOT_APPROVED" in report["blocking_codes"]
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_EXECUTION_BLOCKED"):
        require_full_pretraining_approval(report)


@pytest.mark.parametrize(
    ("section", "key", "code"),
    [
        ("identity", "pilot_dataset_fingerprint", "FULL_PRETRAINING_PILOT_DATASET_FINGERPRINT_MISMATCH"),
        ("identity", "tokenizer_fingerprint", "FULL_PRETRAINING_TOKENIZER_FINGERPRINT_MISMATCH"),
        ("identity", "model_fingerprint", "FULL_PRETRAINING_MODEL_MISMATCH"),
        ("identity", "config_fingerprint", "FULL_PRETRAINING_CONFIG_MISMATCH"),
        ("initialization", "mode", "FULL_PRETRAINING_INITIALIZATION_MISMATCH"),
    ],
)
def test_identity_and_initialization_mismatch_are_blocked(tmp_path: Path, monkeypatch, section: str, key: str, code: str) -> None:
    value = approved_manifest()
    value[section][key] = "changed"
    report = inspect_with_mocks(tmp_path, monkeypatch, value)
    assert code in report["blocking_codes"]


@pytest.mark.parametrize(
    ("section", "code"),
    [
        ("retention_policy", "FULL_PRETRAINING_RETENTION_NOT_APPROVED"),
        ("disk_budget", "FULL_PRETRAINING_DISK_BUDGET_NOT_APPROVED"),
        ("evaluation_policy", "FULL_PRETRAINING_EVALUATION_NOT_APPROVED"),
    ],
)
def test_required_policy_approval_is_fail_closed(tmp_path: Path, monkeypatch, section: str, code: str) -> None:
    value = approved_manifest()
    value[section]["approval_status"] = "not_approved"
    assert code in inspect_with_mocks(tmp_path, monkeypatch, value)["blocking_codes"]


def test_policy_value_mismatch_is_blocked(tmp_path: Path, monkeypatch) -> None:
    value = approved_manifest()
    value["checkpoint_policy"]["interval_steps"] += 1
    report = inspect_with_mocks(tmp_path, monkeypatch, value)
    assert "FULL_PRETRAINING_CHECKPOINT_POLICY_MISMATCH" in report["blocking_codes"]


def test_approval_consumption_and_reexecution_are_blocked(tmp_path: Path, monkeypatch) -> None:
    value = approved_manifest()
    value["execution_approval"]["consumed"] = True
    value["execution_approval"]["execution_started"] = True
    report = inspect_with_mocks(tmp_path, monkeypatch, value)
    assert "FULL_PRETRAINING_APPROVAL_CONSUMED" in report["blocking_codes"]
    assert "FULL_PRETRAINING_REEXECUTION_BLOCKED" in report["blocking_codes"]


def test_approved_execution_without_preflight_acknowledgement_is_blocked(tmp_path: Path, monkeypatch) -> None:
    value = approved_manifest()
    value["execution_approval"]["execution_preflight"]["plugged_power"] = False
    report = inspect_with_mocks(tmp_path, monkeypatch, value)
    assert "FULL_PRETRAINING_PREFLIGHT_NOT_ACKNOWLEDGED" in report["blocking_codes"]


def test_fully_approved_package_can_only_reach_readiness_not_training(tmp_path: Path, monkeypatch) -> None:
    report = inspect_with_mocks(tmp_path, monkeypatch, approved_manifest())
    assert report["execution_allowed"] is True
    assert report["execution_backend_implemented"] is True
    assert report["training_started"] is False
    require_full_pretraining_approval(report)


def test_existing_output_blocks_reexecution(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "existing-run"
    output.mkdir()
    value = approved_manifest()
    manifest_path = tmp_path / "manifest.yaml"
    write_yaml(manifest_path, value)
    monkeypatch.setattr("src.training.full_pretraining._lineage", lambda _config: lineage_from_manifest(value))
    monkeypatch.setattr(
        "src.training.full_pretraining._git_value",
        lambda *args: "c3b778df31b9888ca6539b1d2b3c09faca6ec0e9" if args[0] == "rev-parse" else "feat/pilot-pretraining",
    )
    monkeypatch.setattr("src.training.full_pretraining.resolve_full_pretraining_path", lambda *_args: output)
    assert "FULL_PRETRAINING_OUTPUT_EXISTS" in inspect_full_pretraining_readiness(CONFIG_PATH, manifest_path)["blocking_codes"]


def test_output_probe_is_atomic_verified_and_deleted(tmp_path: Path, monkeypatch) -> None:
    config = FullPretrainingConfig.from_yaml(CONFIG_PATH)
    output = tmp_path / "new-run"
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("src.training.full_pretraining.resolve_full_pretraining_path", lambda *_args: output)
    monkeypatch.setattr("src.training.full_pretraining.shutil.disk_usage", lambda _path: usage(30 * 1024**3, 1, 20 * 1024**3))
    report = probe_full_pretraining_output(config)
    assert report["output_path_write_verified"] is True
    assert report["atomic_rename_verified"] is True and report["probe_deleted"] is True
    assert not output.exists() and not list(tmp_path.glob(".full-pretraining-probe-*"))


def test_manifest_config_fingerprint_matches_candidate() -> None:
    assert load_yaml(MANIFEST_PATH)["identity"]["config_fingerprint"] == file_checksum(CONFIG_PATH)
