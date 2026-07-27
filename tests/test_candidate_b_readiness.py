from __future__ import annotations

import math
from pathlib import Path

import yaml

from src.data.checksums import file_checksum


CONFIG_PATH = Path("configs/candidate-b.example.yaml")
MANIFEST_PATH = Path("docs/training/candidate-b-readiness.manifest.yaml")
CANDIDATE_A_MANIFEST_PATH = Path("docs/training/full-pretraining-approval.manifest.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def iter_strings(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, str):
        yield value


def test_candidate_b_budget_is_exact_25m_design() -> None:
    config = load_yaml(CONFIG_PATH)
    manifest = load_yaml(MANIFEST_PATH)
    expected_steps = math.ceil(25_000_000 / 2_048)
    expected_scheduled = expected_steps * 2_048

    assert expected_steps == 12_208
    assert expected_scheduled == 25_001_984
    assert config["token_budget"] == manifest["budget"]["requested_tokens"] == 25_000_000
    assert config["max_steps"] == manifest["budget"]["optimizer_steps"] == expected_steps
    assert config["scheduled_tokens"] == manifest["budget"]["scheduled_tokens"] == expected_scheduled
    assert manifest["budget"]["packed_sequences"] == expected_steps * 8


def test_candidate_b_is_fresh_controlled_comparison() -> None:
    config = load_yaml(CONFIG_PATH)
    manifest = load_yaml(MANIFEST_PATH)

    assert config["initialization"] == {
        "mode": "fresh_seed_17",
        "seed": 17,
        "parent_checkpoint": None,
        "candidate_a_checkpoint_used": False,
        "optimizer_state_reused": False,
        "scheduler_state_reused": False,
        "sampler_state_reused": False,
    }
    assert manifest["initialization"]["comparison_variable"] == "token_budget_only"
    assert manifest["initialization"]["candidate_a_state_reused"] is False
    assert manifest["baseline"]["checkpoint_checksum"] == (
        "sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8"
    )


def test_candidate_b_lineage_matches_candidate_a() -> None:
    candidate_b = load_yaml(MANIFEST_PATH)["identity"]
    candidate_a = load_yaml(CANDIDATE_A_MANIFEST_PATH)["identity"]
    for key in (
        "dataset_id",
        "dataset_version",
        "source_split",
        "source_record_count",
        "training_lineage_fingerprint",
        "source_lineage_fingerprint",
        "pii_fingerprint",
        "split_fingerprint",
        "tokenization_fingerprint",
        "packing_fingerprint",
        "tokenizer_id",
        "tokenizer_fingerprint",
        "model_name",
        "model_parameters",
        "model_fingerprint",
    ):
        assert candidate_b[key] == candidate_a[key]


def test_candidate_b_uses_approved_evaluation_contract() -> None:
    contract = load_yaml(MANIFEST_PATH)["evaluation_contract"]
    config = load_yaml(CONFIG_PATH)["evaluation_policy"]

    assert contract["approval_status"] == "approved"
    assert contract["official_decision_profile"] == config["official_decision_profile"] == "full"
    assert contract["quick_schedule"] == config["quick_schedule"] == ["start", "step-4883", "final"]
    assert contract["full_schedule"] == config["full_schedule"] == ["post-training-final"]
    assert contract["eos_top1_minimum"] == 0.122334
    assert contract["eos_top5_minimum"] == 0.863028
    assert contract["eos_top10_minimum"] == 0.894814
    assert contract["greedy_eos_rate_minimum_exclusive"] == 0.0
    assert contract["greedy_maximum_length_rate_maximum_exclusive"] == 1.0
    assert contract["aggregate_score_allowed"] is False


def test_checkpoint_and_resume_are_bounded_and_fail_closed() -> None:
    manifest = load_yaml(MANIFEST_PATH)
    checkpoints = manifest["checkpoint_policy"]
    resume = manifest["resume_policy"]

    assert checkpoints["steps"] == [4_883, 9_766, 12_208]
    assert checkpoints["scheduled_tokens"] == [10_000_384, 20_000_768, 25_001_984]
    assert checkpoints["maximum_retained"] == 3
    assert checkpoints["atomic_publish"] is True
    assert checkpoints["automatic_deletion_during_run"] is False
    assert resume["automatic_resume"] is False
    assert resume["automatic_retry"] is False
    assert resume["same_run_only"] is True
    assert resume["cross_candidate_resume"] is False
    assert resume["separate_user_approval_required"] is True


def test_execution_is_explicitly_blocked() -> None:
    manifest = load_yaml(MANIFEST_PATH)
    approval = manifest["execution_approval"]
    backend = manifest["execution_backend"]
    readiness = manifest["readiness"]

    assert approval["status"] == "consumed_failed_attempt"
    assert approval["execution_allowed"] is False
    assert approval["consumed"] is True
    assert approval["automatic_extension"] is False
    assert approval["automatic_retry"] is False
    assert backend["status"] == "implemented_and_cpu_validated"
    assert backend["candidate_b_execution_supported"] is True
    assert backend["default_optimizer_or_backward_allowed"] is False
    assert readiness["execution_allowed"] is False
    assert readiness["training_started"] is True
    assert readiness["backend_implemented"] is True
    assert readiness["cpu_validation_passed"] is True
    assert readiness["blocker_count"] == len(readiness["blocking_codes"]) == 4
    assert "CANDIDATE_B_EXECUTION_APPROVAL_MISSING" in readiness["blocking_codes"]
    assert "CANDIDATE_B_NEW_RUN_ID_REQUIRED" in readiness["blocking_codes"]
    assert "CANDIDATE_B_PHYSICAL_PREFLIGHT_MISSING" in readiness["blocking_codes"]


def test_config_fingerprint_and_paths_are_repository_safe() -> None:
    config = load_yaml(CONFIG_PATH)
    manifest = load_yaml(MANIFEST_PATH)

    assert manifest["identity"]["config_fingerprint"] == file_checksum(CONFIG_PATH)
    assert config["path_root"] == "configured_external"
    assert all(":\\" not in value and not value.startswith("/") for value in iter_strings(config))
    assert config["approval"]["execution_allowed"] is False
    assert config["execution_mode"] == "inspection_only"
