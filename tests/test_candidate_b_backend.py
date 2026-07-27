from __future__ import annotations

import datetime as dt
import json
from collections import namedtuple
from pathlib import Path

import pytest
import yaml

from src.data.checksums import checksum_value
from src.training.candidate_b import (
    CHECKPOINT_STEPS,
    inspect_candidate_b_git,
    inspect_candidate_b_readiness,
    load_resolved_candidate_b_config,
    probe_candidate_b_output,
    resolve_candidate_b_config,
    validate_candidate_b_approval,
    validate_candidate_b_checkpoint_metadata,
    validate_candidate_b_scope,
)
from src.training.candidate_b_backend import (
    CandidateBApprovalConsumer,
    CandidateBRuntimeMonitor,
    candidate_b_execution_plan,
    run_candidate_b_cpu_smoke,
)
from src.training.errors import TrainingError
from src.training.metrics import TrainingMetric

from tests._training_helpers import build_tiny_trainer, training_config


EXAMPLE_PATH = Path("configs/candidate-b.example.yaml")
LOCAL_EXAMPLE_PATH = Path("configs/candidate-b-local.example.yaml")
RESOLVED_EXAMPLE_PATH = Path("configs/candidate-b-resolved.example.yaml")
READINESS_PATH = Path("docs/training/candidate-b-readiness.manifest.yaml")
APPROVAL_EXAMPLE_PATH = Path("configs/candidate-b-approval.example.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolved() -> dict:
    return load_resolved_candidate_b_config(RESOLVED_EXAMPLE_PATH)


def clean_git() -> dict:
    return {
        "branch": "feat/candidate-b-design",
        "commit": "1" * 40,
        "remote": "origin",
        "remote_branch": "origin/feat/candidate-b-design",
        "repository_identity": "sha256:" + "2" * 64,
        "tree_clean": True,
        "staged_changes": False,
        "modified_changes": False,
        "untracked_changes": False,
        "upstream_matches": True,
        "head_exists_remote": True,
        "blocking_codes": [],
    }


def approved_fixture(document: dict, git: dict) -> dict:
    value = load_yaml(APPROVAL_EXAMPLE_PATH)
    value.update({
        "approval_id": "CANDIDATE-B-APPROVAL-TEST-0001",
        "approval_status": "approved",
        "issued_at": "2026-07-28T00:00:00+09:00",
        "git_commit": git["commit"],
        "git_tree_clean": True,
        "git_remote_branch": git["remote_branch"],
        "repository_identity": git["repository_identity"],
        "resolved_config_fingerprint": checksum_value(document),
    })
    return value


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


def test_resolver_reproduces_versioned_resolved_example() -> None:
    result = resolve_candidate_b_config(EXAMPLE_PATH, LOCAL_EXAMPLE_PATH, READINESS_PATH, allow_placeholder_run_id=False)
    expected = resolved()
    assert result["document"] == expected
    assert result["resolved_config_fingerprint"] == checksum_value(expected)
    assert result["resolved_config_fingerprint"] == "sha256:bd6f3f2401c676dc154493997406d2e50f8c8d09b89c69f6d0daebfb52b05bcc"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("candidate_id",), "candidate-a"),
        (("budget", "requested_tokens"), 25_000_001),
        (("budget", "optimizer_steps"), 12_209),
        (("initialization", "seed"), 18),
        (("initialization", "candidate_a_checkpoint_used"), True),
        (("resume_policy", "resume_allowed"), True),
        (("resume_policy", "automatic_retry"), True),
        (("approval_policy", "extension_allowed"), True),
        (("evaluation_policy", "full_evaluation_during_training"), True),
        (("checkpoint_policy", "steps"), [4_883, 12_208]),
        (("paths", "train_dataset"), "D:/private/train.jsonl"),
        (("publication_policy", "checkpoint"), True),
    ],
)
def test_scope_mutations_are_rejected(path: tuple[str, ...], value) -> None:
    document = load_yaml(RESOLVED_EXAMPLE_PATH)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(TrainingError):
        validate_candidate_b_scope(document, allow_placeholder_run_id=False)


def test_plan_has_no_resume_full_auto_eval_or_text() -> None:
    plan = candidate_b_execution_plan(resolved())
    assert plan["optimizer_step_limit"] == 12_208
    assert plan["scheduled_token_limit"] == 25_001_984
    assert plan["checkpoint_steps"] == list(CHECKPOINT_STEPS)
    assert plan["full_evaluation_automatic"] is False
    assert plan["resume_allowed"] is False
    assert plan["actual_text_values_stored"] is False
    assert plan["full_token_ids_stored"] is False


def test_git_inspection_enforces_clean_upstream_remote_identity() -> None:
    mapping = {
        ("symbolic-ref", "--quiet", "--short", "HEAD"): (0, "feat/candidate-b-design", ""),
        ("rev-parse", "HEAD"): (0, "1" * 40, ""),
        ("status", "--porcelain=v1", "--untracked-files=all"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): (0, "origin/feat/candidate-b-design", ""),
        ("rev-parse", "@{upstream}"): (0, "1" * 40, ""),
        ("remote", "get-url", "origin"): (0, "https://example.invalid/doha/DohaLM.git", ""),
        ("branch", "-r", "--contains", "1" * 40): (0, "origin/feat/candidate-b-design", ""),
    }
    report = inspect_candidate_b_git(Path.cwd(), command=lambda *args: mapping[args])
    assert report["tree_clean"] is True
    assert report["upstream_matches"] is True
    assert report["head_exists_remote"] is True
    assert report["blocking_codes"] == []


def test_git_inspection_separates_dirty_untracked_detached_and_upstream() -> None:
    def command(*args):
        if args[0] == "symbolic-ref":
            return 1, "", "detached"
        if args == ("rev-parse", "HEAD"):
            return 0, "1" * 40, ""
        if args[0] == "status":
            return 0, " M tracked.py\n?? new.py", ""
        if args == ("remote", "get-url", "origin"):
            return 0, "https://token@example.invalid/repo.git", ""
        if args[0:2] == ("branch", "-r"):
            return 0, "", ""
        return 1, "", "missing"
    report = inspect_candidate_b_git(Path.cwd(), command=command)
    assert "CANDIDATE_B_DETACHED_HEAD" in report["blocking_codes"]
    assert "CANDIDATE_B_MODIFIED_WORKTREE" in report["blocking_codes"]
    assert "CANDIDATE_B_UNTRACKED_FILES" in report["blocking_codes"]
    assert "CANDIDATE_B_UPSTREAM_MISSING" in report["blocking_codes"]
    assert "CANDIDATE_B_HEAD_NOT_ON_REMOTE" in report["blocking_codes"]


def test_approval_exact_match_and_expiry_policy() -> None:
    document = resolved()
    git = clean_git()
    approval = approved_fixture(document, git)
    assert validate_candidate_b_approval(approval, document, checksum_value(document), git) == []
    approval["approved_token_budget"] += 1
    assert "CANDIDATE_B_APPROVAL_APPROVED_TOKEN_BUDGET_MISMATCH" in validate_candidate_b_approval(
        approval, document, checksum_value(document), git,
    )


def test_expired_consumed_and_wrong_run_approval_are_blocked() -> None:
    document = resolved()
    git = clean_git()
    approval = approved_fixture(document, git)
    approval.update({"expires_at": "2026-07-01T00:00:00+00:00", "consumed": True, "run_id": "wrong"})
    blockers = validate_candidate_b_approval(
        approval, document, checksum_value(document), git,
        now=dt.datetime(2026, 7, 28, tzinfo=dt.timezone.utc),
    )
    assert "CANDIDATE_B_APPROVAL_EXPIRED" in blockers
    assert "CANDIDATE_B_APPROVAL_CONSUMED_MISMATCH" in blockers
    assert "CANDIDATE_B_APPROVAL_RUN_ID_MISMATCH" in blockers


def test_single_use_fixture_consumes_atomically_only_before_step_one(tmp_path: Path) -> None:
    approval_path = tmp_path / "fixture.yaml"
    approval_path.write_text("approval_type: synthetic_test_fixture\n", encoding="utf-8")
    approval = {
        "approval_id": "fixture-1",
        "approval_type": "synthetic_test_fixture",
        "run_id": "SYNTHETIC-TEST-CANDIDATE-B",
        "single_use": True,
        "consumed": False,
    }
    consumer = CandidateBApprovalConsumer(
        approval=approval,
        approval_path=approval_path,
        consumption_path=tmp_path / "consumed.json",
        readiness_fingerprint="sha256:" + "1" * 64,
        fixture_mode=True,
    )
    with pytest.raises(TrainingError, match="CANDIDATE_B_APPROVAL_CONSUMPTION_ORDER"):
        consumer.consume_before_optimizer_step(2)
    consumer.consume_before_optimizer_step(1)
    value = json.loads((tmp_path / "consumed.json").read_text(encoding="utf-8"))
    assert value["consumed_at_optimizer_step"] == 1
    assert value["synthetic_fixture"] is True
    consumer.consume_before_optimizer_step(2)


def test_real_approval_cannot_be_consumed_as_fixture(tmp_path: Path) -> None:
    with pytest.raises(TrainingError, match="CANDIDATE_B_APPROVAL_FIXTURE_INVALID"):
        CandidateBApprovalConsumer(
            approval={"approval_type": "candidate_b_execution", "run_id": "FULL-PRETRAIN"},
            approval_path=tmp_path / "approval.yaml",
            consumption_path=tmp_path / "consumed.json",
            readiness_fingerprint="sha256:" + "1" * 64,
            fixture_mode=True,
        )


def test_trainer_pre_optimizer_hook_runs_before_step_and_failure_keeps_step_zero(tmp_path: Path) -> None:
    trainer, _ = build_tiny_trainer(tmp_path / "ok", config=training_config(max_steps=1, save_every=1))
    observed: list[tuple[int, int]] = []
    trainer.train(target_steps=1, before_optimizer_step=lambda next_step: observed.append((next_step, trainer.state.global_step)))
    assert observed == [(1, 0)]

    failed, _ = build_tiny_trainer(tmp_path / "failed", config=training_config(max_steps=1, save_every=1))
    def stop(_next_step: int) -> None:
        raise TrainingError("SYNTHETIC_APPROVAL_FAILURE", "stop before optimizer")
    with pytest.raises(TrainingError, match="SYNTHETIC_APPROVAL_FAILURE"):
        failed.train(target_steps=1, before_optimizer_step=stop)
    assert failed.state.global_step == 0
    assert not list((tmp_path / "failed").glob("checkpoint-*"))


def test_cpu_smoke_has_no_optimizer_backward_approval_checkpoint_or_output() -> None:
    report = run_candidate_b_cpu_smoke(resolved())
    assert report["status"] == "passed"
    assert report["optimizer_steps"] == 0
    assert report["backward_calls"] == 0
    assert report["actual_approval_consumed"] is False
    assert report["checkpoint_created"] is False
    assert report["external_output_published"] is False


def test_output_probe_fsync_checksum_delete_and_outside_git(tmp_path: Path, monkeypatch) -> None:
    document = resolved()
    external = tmp_path / "external"
    output = external / "analysis/training/candidate-b/runs/test"
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("src.training.candidate_b.repository_root", lambda: tmp_path / "repo")
    monkeypatch.setattr("src.training.candidate_b.resolve_local_paths", lambda _path: (external.resolve(), {}))
    monkeypatch.setattr("src.training.candidate_b.resolve_candidate_b_external_path", lambda *_args: output.resolve())
    monkeypatch.setattr("src.training.candidate_b.shutil.disk_usage", lambda _path: usage(30 * 1024**3, 1, 20 * 1024**3))
    report = probe_candidate_b_output(document)
    assert report["status"] == "output_probe_passed"
    assert report["fsync"] and report["atomic_rename"] and report["checksum_readback"] and report["delete"]
    assert report["probe_deleted"] is True
    assert not list(output.parent.glob(".candidate-b-*-probe-*"))


def test_output_probe_rejects_git_internal_path(tmp_path: Path, monkeypatch) -> None:
    document = resolved()
    output = tmp_path / "repo" / "run"
    monkeypatch.setattr("src.training.candidate_b.repository_root", lambda: tmp_path / "repo")
    monkeypatch.setattr("src.training.candidate_b.resolve_candidate_b_external_path", lambda *_args: output.resolve())
    monkeypatch.setattr("src.training.candidate_b.resolve_local_paths", lambda _path: ((tmp_path / "repo").resolve(), {}))
    with pytest.raises(TrainingError, match="CANDIDATE_B_OUTPUT_INSIDE_GIT"):
        probe_candidate_b_output(document)


def test_runtime_monitor_enforces_limits(tmp_path: Path, monkeypatch) -> None:
    document = resolved()
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("src.training.candidate_b_backend.shutil.disk_usage", lambda _p: usage(30, 1, 20 * 1024**3))
    with pytest.raises(TrainingError, match="CANDIDATE_B_STEP_LIMIT"):
        CandidateBRuntimeMonitor(document, tmp_path).observe(metric(12_209))
    with pytest.raises(TrainingError, match="CANDIDATE_B_VRAM_LIMIT"):
        CandidateBRuntimeMonitor(document, tmp_path).observe(metric(1, peak_memory_reserved=7 * 1024**3 + 1))
    with pytest.raises(TrainingError, match="CANDIDATE_B_CPU_MEMORY_LIMIT"):
        CandidateBRuntimeMonitor(document, tmp_path).observe(metric(1, cpu_working_set_bytes=4 * 1024**3 + 1))
    with pytest.raises(TrainingError, match="CANDIDATE_B_NON_FINITE"):
        CandidateBRuntimeMonitor(document, tmp_path).observe(metric(1, loss=float("nan")))


def test_checkpoint_metadata_schema_and_resume_denial() -> None:
    document = resolved()
    metadata = {
        "model_state": "model.pt",
        "optimizer_state": "optimizer.pt",
        "scheduler_state": "scheduler.pt",
        "amp_scaler_state": "scaler.pt",
        "current_step": 4_883,
        "consumed_tokens": 10_000_384,
        "sampler_state": {"sample_offset": 1},
        "rng_state": {"torch": "present"},
        "config_fingerprint": checksum_value(document),
        "dataset_fingerprint": document["identity"]["dataset_fingerprint"],
        "tokenizer_fingerprint": document["identity"]["tokenizer_fingerprint"],
        "model_fingerprint": document["identity"]["model_fingerprint"],
        "git_commit": "1" * 40,
        "approval_id": "approval-1",
        "run_id": document["run_id"],
        "checksum_manifest": "checksums.json",
        "resume_allowed": False,
    }
    validate_candidate_b_checkpoint_metadata(metadata, document)
    metadata["resume_allowed"] = True
    with pytest.raises(TrainingError, match="CANDIDATE_B_CHECKPOINT_SCHEMA_INVALID"):
        validate_candidate_b_checkpoint_metadata(metadata, document)


def test_readiness_can_only_be_true_for_complete_test_fixture(tmp_path: Path) -> None:
    document = resolved()
    git = clean_git()
    approval = approved_fixture(document, git)
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval, sort_keys=False), encoding="utf-8")
    physical = {
        "plugged_power": True,
        "adequate_cooling_and_ventilation": True,
        "windows_sleep_disabled": True,
        "no_restart_or_update_scheduled": True,
        "no_other_long_gpu_task": True,
    }
    report = inspect_candidate_b_readiness(
        resolved_config_path=RESOLVED_EXAMPLE_PATH,
        approval_path=approval_path,
        cpu_validation={
            "status": "passed", "optimizer_steps": 0,
            "actual_approval_consumed": False, "checkpoint_created": False,
        },
        output_probe={"status": "output_probe_passed"},
        physical_preflight=physical,
        git=git,
    )
    assert report["status"] == "ready_for_execution"
    assert report["execution_allowed"] is True
    blocked = inspect_candidate_b_readiness(
        resolved_config_path=RESOLVED_EXAMPLE_PATH,
        approval_path=None,
        cpu_validation={
            "status": "passed", "optimizer_steps": 0,
            "actual_approval_consumed": False, "checkpoint_created": False,
        },
        output_probe=None,
        physical_preflight=None,
        git=git,
    )
    assert blocked["execution_allowed"] is False
    assert "CANDIDATE_B_EXECUTION_APPROVAL_MISSING" in blocked["blocking_codes"]


@pytest.mark.parametrize(
    ("path", "fingerprint_key"),
    [
        (Path("docs/training/candidate-b-output-probe.manifest.yaml"), "result_fingerprint"),
        (Path("docs/training/candidate-b-runtime-preflight.manifest.yaml"), "manifest_fingerprint"),
        (Path("docs/training/candidate-b-final-readiness.manifest.yaml"), "readiness_fingerprint"),
    ],
)
def test_readiness_artifact_fingerprints_are_consistent(path: Path, fingerprint_key: str) -> None:
    value = load_yaml(path)
    expected = value.pop(fingerprint_key)
    assert checksum_value(value) == expected
