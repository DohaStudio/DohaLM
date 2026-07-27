from pathlib import Path
from types import SimpleNamespace
import tempfile

import yaml

from src.data.checksums import checksum_value
from src.evaluation.artifacts import ArtifactRegistry
from src.evaluation.benchmarks import BenchmarkRegistration
from src.evaluation.config import EvaluationConfig, EvaluationError
from src.model import ModelConfig


CONFIG = Path("configs/evaluation.example.yaml")
REGISTRY = Path("configs/evaluation-artifacts.example.yaml")


def test_registry_contains_required_artifacts() -> None:
    registry = ArtifactRegistry.load(REGISTRY)
    assert set(registry.artifacts) == {
        "initial-seed-17", "gate7-overfit-final", "pilot-100", "candidate-a-mid",
        "candidate-a-final", "candidate-b-final",
    }
    assert registry.get("candidate-a-final").value["evaluation_eligibility"] == "eligible"
    assert registry.get("candidate-b-final").value["run_id"] == "FULL-PRETRAIN-CANDIDATE-B-20260728-0002"


def test_initial_seed_17_initialization_fingerprint_is_reproducible() -> None:
    artifact = ArtifactRegistry.load(REGISTRY).get("initial-seed-17").value
    model_fingerprint = checksum_value(ModelConfig().to_dict())
    initialization_fingerprint = checksum_value({
        "mode": "fresh_seed_17", "seed": 17,
        "model_fingerprint": model_fingerprint, "pilot_checkpoint_used": False,
    })
    assert model_fingerprint == artifact["model_fingerprint"]
    assert initialization_fingerprint == artifact["config_fingerprint"]


def test_config_is_fail_closed_and_has_no_absolute_public_paths() -> None:
    config = EvaluationConfig.from_yaml(CONFIG)
    assert config.raw_text_storage is False
    assert config.token_id_storage is False
    assert config.external_benchmark == "disabled"
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert "D:/" not in CONFIG.read_text(encoding="utf-8")
    assert document["dataset_identity"]["original_validation_used"] is False


def test_full_profile_uses_all_sequences_and_has_distinct_fingerprint() -> None:
    quick = EvaluationConfig.from_yaml(CONFIG, profile="quick")
    full = EvaluationConfig.from_yaml(CONFIG, profile="full")
    assert full.profile.maximum_sequences == 14329
    assert full.profile.timeout_seconds == 900
    assert full.profile_fingerprint != quick.profile_fingerprint


def test_unregistered_artifact_is_blocked() -> None:
    registry = ArtifactRegistry.load(REGISTRY)
    try:
        registry.get("not-registered")
    except EvaluationError as exc:
        assert exc.code == "ARTIFACT_NOT_REGISTERED"
    else:
        raise AssertionError("unregistered artifact was accepted")


def test_checkpoint_identity_mismatches_are_blocked(monkeypatch) -> None:
    registry = ArtifactRegistry.load(REGISTRY)
    artifact = registry.get("candidate-a-final")
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint = Path(temporary) / "checkpoint"
        checkpoint.mkdir()
        (checkpoint / "checksums.json").write_text("{}", encoding="utf-8")
        class Config:
            def external_path(self, logical: str) -> Path:
                return checkpoint
        base = dict(
            global_step=4883,
            tokenizer_fingerprint=artifact.value["tokenizer_fingerprint"],
            model_config_fingerprint=artifact.value["model_fingerprint"],
            dataset_fingerprint=artifact.value["dataset_fingerprint"],
            training_config_fingerprint=artifact.value["checkpoint_training_config_fingerprint"],
        )
        monkeypatch.setattr("src.evaluation.artifacts.file_checksum", lambda path: artifact.value["checkpoint_checksum"])
        monkeypatch.setattr("src.evaluation.artifacts._directory_bytes", lambda path: artifact.value["checkpoint_bundle_bytes"])
        for field in ("tokenizer_fingerprint", "dataset_fingerprint", "training_config_fingerprint"):
            value = {**base, field: "sha256:mismatch"}
            inspection = SimpleNamespace(**value, to_dict=lambda value=value: value)
            monkeypatch.setattr("src.evaluation.artifacts.CheckpointManager.inspect", lambda path, inspection=inspection: inspection)
            assert registry.inspect(Config(), artifact.artifact_id)["status"] == "fingerprint_mismatch"


def test_missing_and_superseded_statuses_are_preserved() -> None:
    registry = ArtifactRegistry.load(REGISTRY)
    class MissingConfig:
        def external_path(self, logical: str) -> Path:
            return Path("Z:/definitely-absent-evaluation-artifact")
    assert registry.inspect(MissingConfig(), "candidate-a-final")["status"] == "missing"
    value = dict(registry.get("initial-seed-17").value)
    value["evaluation_eligibility"] = "superseded"
    blocked = ArtifactRegistry({"old": type(registry.get("initial-seed-17"))("old", value)})
    try:
        blocked.inspect(MissingConfig(), "old", require_eligible=True)
    except EvaluationError as exc:
        assert exc.code == "ARTIFACT_EVALUATION_BLOCKED"
    else:
        raise AssertionError("superseded artifact was accepted")


def test_external_benchmark_registration_is_fail_closed() -> None:
    registration = BenchmarkRegistration(
        dataset_id="example", version=None, license_status="pending",
        evaluation_purpose_approval="not_approved", contamination_status="not_run",
        redistribution_status="unknown", download_status="not_downloaded", logical_external_path=None,
    )
    try:
        registration.require_eligible()
    except EvaluationError as exc:
        assert exc.code == "BENCHMARK_NOT_APPROVED"
    else:
        raise AssertionError("unapproved external benchmark was accepted")
