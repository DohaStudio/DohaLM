from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

import pytest
import yaml

from src.training import TrainingError
from src.training.full_pretraining import FullPretrainingConfig
from src.training.full_pretraining_backend import (
    FullSafetyMonitor,
    SingleUseApprovalConsumer,
    _load_amp_numerical_diagnostic_policy,
    _write_json,
    candidate_a_execution_plan,
    dry_run_full_pretraining,
)
from src.training.metrics import AmpOverflowEvent, TrainingMetric


CONFIG_PATH = Path("configs/full-pretraining.example.yaml")
MANIFEST_PATH = Path("docs/training/full-pretraining-approval.manifest.yaml")


def metric(step: int, **changes) -> TrainingMetric:
    value = {
        "global_step": step,
        "loss": 1.0,
        "learning_rate": 3e-4,
        "gradient_norm": 1.0,
        "gradient_norm_before_clip": 1.0,
        "tokens_seen": step * 2_048,
        "records_seen": step * 8,
        "step_time": 0.1,
        "tokens_per_second": 20_480.0,
        "peak_memory_allocated": 1,
        "peak_memory_reserved": 1,
        "cpu_working_set_bytes": 1,
        "remaining_disk_bytes": 20 * 1024**3,
    }
    value.update(changes)
    return TrainingMetric(**value)


def amp_overflow(attempt: int) -> AmpOverflowEvent:
    return AmpOverflowEvent(
        global_step=10,
        next_optimizer_step=11,
        attempt=attempt,
        scale_before=1024.0 / (2 ** (attempt - 1)),
        scale_after=512.0 / (2 ** (attempt - 1)),
        pending_tokens=2_048,
        pending_records=8,
        sampler_cursor=88,
        model_parameters_finite=True,
        optimizer_state_finite=True,
        timestamp="2026-08-19T00:00:00+00:00",
    )


def test_candidate_a_plan_has_exact_limits_and_no_text() -> None:
    plan = candidate_a_execution_plan(FullPretrainingConfig.from_yaml(CONFIG_PATH))
    assert plan["optimizer_step_limit"] == 4_883
    assert plan["scheduled_token_limit"] == 10_000_384
    assert plan["checkpoint_steps"] == [2_442, 4_883]
    assert plan["evaluation_steps"] == [0, 4_883]
    assert plan["actual_text_values_stored"] is False
    assert plan["amp_numerical_diagnostics"]["mode"] == (
        "prospective_no_update_scale_probe"
    )
    assert plan["amp_numerical_diagnostics"]["scale_floor"] == 1_024
    assert not ({"text", "prompt", "continuation", "token_ids"} & set(plan))


@pytest.mark.parametrize(
    "value",
    [
        {},
        {
            "mode": "prospective_no_update_scale_probe",
            "scale_floor": 1000,
            "schema_version": 1,
        },
        {"mode": "training_policy", "scale_floor": 1024, "schema_version": 1},
    ],
)
def test_amp_diagnostic_policy_is_strict_and_fail_closed(
    tmp_path: Path, value: dict[str, object]
) -> None:
    path = tmp_path / "diagnostic.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(TrainingError, match="DIAGNOSTIC_EVIDENCE_FAILURE"):
        _load_amp_numerical_diagnostic_policy(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budget_candidate", "candidate_b_1epoch"),
        ("seed", 18),
        ("learning_rate", 1e-3),
        ("warmup_steps", 11),
    ],
)
def test_candidate_a_profile_rejects_mutation(
    tmp_path: Path, field: str, value
) -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config[field] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(
        TrainingError, match="FULL_PRETRAINING_CANDIDATE_A_PROFILE_MISMATCH"
    ):
        FullPretrainingConfig.from_yaml(path)


def test_pilot_checkpoint_and_unapproved_resume_are_rejected(tmp_path: Path) -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["initialization"]["mode"] = "pilot_checkpoint"
    path = tmp_path / "pilot.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_INITIALIZATION_MISMATCH"):
        FullPretrainingConfig.from_yaml(path)

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["resume_checkpoint"] = "analysis/pilot-pretraining/run/checkpoint-100"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_RESUME_NOT_APPROVED"):
        FullPretrainingConfig.from_yaml(path)


def test_safety_monitor_enforces_step_token_amp_memory_and_disk(
    tmp_path: Path, monkeypatch
) -> None:
    config = FullPretrainingConfig.from_yaml(CONFIG_PATH)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "src.training.full_pretraining_backend.shutil.disk_usage",
        lambda _p: usage(30, 1, 20 * 1024**3),
    )
    monitor = FullSafetyMonitor(config, tmp_path)
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_STEP_LIMIT"):
        monitor.observe(metric(4_884))
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_VRAM_LIMIT"):
        FullSafetyMonitor(config, tmp_path).observe(
            metric(1, peak_memory_reserved=7 * 1024**3 + 1)
        )
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_CPU_MEMORY_LIMIT"):
        FullSafetyMonitor(config, tmp_path).observe(
            metric(1, cpu_working_set_bytes=4 * 1024**3 + 1)
        )
    amp = FullSafetyMonitor(config, tmp_path)
    amp.observe(metric(1, amp_step_skipped=True))
    amp.observe(metric(2, amp_step_skipped=True))
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_AMP_SKIP_LIMIT"):
        amp.observe(metric(3, amp_step_skipped=True))
    monkeypatch.setattr(
        "src.training.full_pretraining_backend.shutil.disk_usage",
        lambda _p: usage(30, 1, 5 * 1024**3 - 1),
    )
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_DISK_MINIMUM"):
        FullSafetyMonitor(config, tmp_path).observe(metric(1))


def test_safety_monitor_enforces_repeated_recoverable_amp_overflow_limit(
    tmp_path: Path,
) -> None:
    monitor = FullSafetyMonitor(FullPretrainingConfig.from_yaml(CONFIG_PATH), tmp_path)
    monitor.observe_amp_overflow(amp_overflow(1))
    monitor.observe_amp_overflow(amp_overflow(2))
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_AMP_SKIP_LIMIT"):
        monitor.observe_amp_overflow(amp_overflow(3))
    assert monitor.total_amp_overflows == 3
    assert monitor.last_amp_scale_before == 256.0
    assert monitor.last_amp_scale_after == 128.0


def test_safety_monitor_enforces_rolling_loss_and_gradient(
    tmp_path: Path, monkeypatch
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "src.training.full_pretraining_backend.shutil.disk_usage",
        lambda _p: usage(30, 1, 20 * 1024**3),
    )
    config = FullPretrainingConfig.from_yaml(CONFIG_PATH)
    loss_monitor = FullSafetyMonitor(config, tmp_path)
    for step in range(1, 11):
        loss_monitor.observe(metric(step))
    for step in range(11, 20):
        loss_monitor.observe(metric(step, loss=5.0))
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_LOSS_SPIKE"):
        loss_monitor.observe(metric(20, loss=5.0))

    grad_monitor = FullSafetyMonitor(config, tmp_path)
    for step in range(1, 11):
        grad_monitor.observe(metric(step))
    for step in range(11, 20):
        grad_monitor.observe(metric(step, gradient_norm_before_clip=5.0))
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_GRADIENT_SPIKE"):
        grad_monitor.observe(metric(20, gradient_norm_before_clip=5.0))


def test_single_use_artifact_write_rejects_reuse(tmp_path: Path) -> None:
    path = tmp_path / "approval-consumption.json"
    _write_json(path, {"status": "consumed", "actual_text_values_stored": False})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "consumed"
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_ARTIFACT_EXISTS"):
        _write_json(path, {"status": "consumed"})


def test_approval_is_consumed_only_after_optimizer_step_one(tmp_path: Path) -> None:
    manifest = tmp_path / "approval.yaml"
    manifest.write_text("status: approved\n", encoding="utf-8")
    path = tmp_path / "approval-consumption.json"
    consumer = SingleUseApprovalConsumer(
        path,
        run_id="FULL-A-10M-TEST-0001",
        manifest_path=manifest,
        readiness_fingerprint="sha256:" + "1" * 64,
    )
    assert consumer.consumed is False and not path.exists()
    consumer.observe(metric(2))
    assert consumer.consumed is False and not path.exists()
    consumer.observe(metric(1))
    value = json.loads(path.read_text(encoding="utf-8"))
    assert consumer.consumed is True
    assert value["consumed_at_optimizer_step"] == 1
    consumer.observe(metric(1))


def test_dry_run_never_starts_training(tmp_path: Path, monkeypatch) -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    identity = manifest["identity"]
    lineage = {
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
    monkeypatch.setattr(
        "src.training.full_pretraining._lineage", lambda _config: lineage
    )
    monkeypatch.setattr(
        "src.training.full_pretraining._inspect_source_state",
        lambda: type(
            "SourceState",
            (),
            {
                "commit": "c3b778df31b9888ca6539b1d2b3c09faca6ec0e9",
                "branch": "feat/pilot-pretraining",
                "clean": True,
            },
        )(),
    )
    monkeypatch.setattr(
        "src.training.full_pretraining.resolve_full_pretraining_path",
        lambda *_args: tmp_path / "new-run",
    )
    report = dry_run_full_pretraining(CONFIG_PATH, MANIFEST_PATH)
    assert report["mode"] == "dry_run"
    assert report["training_started"] is False
    assert report["execution_allowed"] is False
    assert "FULL_PRETRAINING_NOT_APPROVED" in report["blocking_codes"]
