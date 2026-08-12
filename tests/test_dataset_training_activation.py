from __future__ import annotations

import copy
import gc
import importlib.util
import pickle
import weakref
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import scripts.training.run_full_pretraining as cli
import src.training.full_pretraining_backend as backend
from src.training.dataset_training_entry import (
    DatasetTrainingPermission,
    evaluate_dataset_training_entry,
    require_dataset_training_activation,
)
from src.training.errors import TrainingError


def _publication_fixtures() -> ModuleType:
    path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location("_activation_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("publication fixtures unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _permission(tmp_path: Path) -> DatasetTrainingPermission:
    fixtures = _publication_fixtures()
    published = fixtures.publish(tmp_path / "publication")
    manifest = published.dataset_manifest
    permission = evaluate_dataset_training_entry(
        published.dataset_version,
        manifest,
        upstream_objects=fixtures.upstream(),
        evaluated_at="2026-08-11T12:00:00Z",
        readiness_report={
            "execution_allowed": True,
            "inspection_only": True,
            "training_started": False,
            "blocking_codes": [],
        },
        expected_split_id=manifest["split_id"],
        artifact_references=manifest["object_file_artifact_refs"],
    )
    assert permission.allowed is True
    return permission


def _target(permission: DatasetTrainingPermission) -> dict[str, str]:
    return {
        "dataset_version_id": permission.dataset_version_id,
        "dataset_manifest_id": permission.dataset_manifest_id,
        "pair_fingerprint": permission.pair_fingerprint,
    }


def _run_kwargs(permission: DatasetTrainingPermission) -> dict:
    return {
        "dataset_permission": permission,
        "dataset_version_id": permission.dataset_version_id,
        "dataset_manifest_id": permission.dataset_manifest_id,
        "dataset_pair_fingerprint": permission.pair_fingerprint,
    }


def test_directly_constructed_permission_is_not_validated() -> None:
    forged = DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id="version",
        dataset_manifest_id="manifest",
        pair_fingerprint="sha256:" + "1" * 64,
    )
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
        require_dataset_training_activation(forged, **_target(forged))


def test_only_evaluator_issued_exact_instance_is_accepted(tmp_path: Path) -> None:
    original = _permission(tmp_path)
    require_dataset_training_activation(original, **_target(original))

    reconstructed = (
        copy.copy(original),
        copy.deepcopy(original),
        pickle.loads(pickle.dumps(original)),
        replace(original),
        DatasetTrainingPermission(
            allowed=original.allowed,
            reason_codes=original.reason_codes,
            dataset_version_id=original.dataset_version_id,
            dataset_manifest_id=original.dataset_manifest_id,
            pair_fingerprint=original.pair_fingerprint,
        ),
    )
    for forged in reconstructed:
        assert forged == original
        with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
            require_dataset_training_activation(forged, **_target(forged))

    field_forged = reconstructed[-1]
    object.__setattr__(field_forged, "_validated", True)
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
        require_dataset_training_activation(field_forged, **_target(field_forged))

    require_dataset_training_activation(original, **_target(original))


def test_permission_issuance_registry_follows_object_lifecycle(tmp_path: Path) -> None:
    permission = _permission(tmp_path)
    reference = weakref.ref(permission)
    equivalent = replace(permission)

    del permission
    gc.collect()

    assert reference() is None
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
        require_dataset_training_activation(equivalent, **_target(equivalent))


def test_reconstructed_permissions_have_zero_downstream_calls(
    monkeypatch, tmp_path: Path
) -> None:
    original = _permission(tmp_path)
    manual = DatasetTrainingPermission(
        allowed=original.allowed,
        reason_codes=original.reason_codes,
        dataset_version_id=original.dataset_version_id,
        dataset_manifest_id=original.dataset_manifest_id,
        pair_fingerprint=original.pair_fingerprint,
    )
    marker_forged = replace(original)
    object.__setattr__(marker_forged, "_validated", True)
    forged_permissions = (
        copy.copy(original),
        copy.deepcopy(original),
        pickle.loads(pickle.dumps(original)),
        replace(original),
        manual,
        marker_forged,
    )
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("downstream")
        raise AssertionError("downstream side effect")

    for name in (
        "require_full_pretraining_approval",
        "TokenizedJsonlDataset",
        "DohaLMTiny",
        "Trainer",
        "evaluate_language_model",
    ):
        monkeypatch.setattr(backend, name, forbidden)

    for forged in forged_permissions:
        with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
            backend.run_full_pretraining(
                Path("config"), Path("manifest"), {}, **_run_kwargs(forged)
            )
    assert calls == []


def test_denied_and_target_mismatch_fail_closed(tmp_path: Path) -> None:
    fixtures = _publication_fixtures()
    published = fixtures.publish(tmp_path / "denied-publication")
    denied = evaluate_dataset_training_entry(
        published.dataset_version,
        published.dataset_manifest,
        upstream_objects=fixtures.upstream(),
        evaluated_at="2026-08-11T12:00:00Z",
        readiness_report={"execution_allowed": False},
        expected_split_id=published.dataset_manifest["split_id"],
        artifact_references=published.dataset_manifest["object_file_artifact_refs"],
    )
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_DENIED"):
        require_dataset_training_activation(
            denied,
            dataset_version_id=denied.dataset_version_id or "version",
            dataset_manifest_id=denied.dataset_manifest_id or "manifest",
            pair_fingerprint=denied.pair_fingerprint or "sha256:" + "1" * 64,
        )

    permission = _permission(tmp_path)
    for field in ("dataset_version_id", "dataset_manifest_id", "pair_fingerprint"):
        target = _target(permission)
        target[field] = "sha256:" + "0" * 64 if field == "pair_fingerprint" else "other"
        with pytest.raises(
            TrainingError, match="DATASET_TRAINING_PERMISSION_TARGET_MISMATCH"
        ):
            require_dataset_training_activation(permission, **target)


def test_permission_absent_stops_before_backend_body(monkeypatch) -> None:
    monkeypatch.setattr(
        backend,
        "require_full_pretraining_approval",
        lambda _report: pytest.fail("readiness must not run"),
    )
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
        backend.run_full_pretraining(Path("config"), Path("manifest"), {})


def test_denied_or_mismatched_permission_has_zero_downstream_calls(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("downstream")
        raise AssertionError("downstream side effect")

    for name in (
        "require_full_pretraining_approval",
        "TokenizedJsonlDataset",
        "DohaLMTiny",
        "Trainer",
        "evaluate_language_model",
    ):
        monkeypatch.setattr(backend, name, forbidden)

    forged = DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id="version",
        dataset_manifest_id="manifest",
        pair_fingerprint="sha256:" + "1" * 64,
    )
    with pytest.raises(TrainingError, match="DATASET_TRAINING_PERMISSION_INVALID"):
        backend.run_full_pretraining(
            Path("config"), Path("manifest"), {}, **_run_kwargs(forged)
        )

    permission = _permission(tmp_path)
    kwargs = _run_kwargs(permission)
    kwargs["dataset_version_id"] = "other"
    with pytest.raises(
        TrainingError, match="DATASET_TRAINING_PERMISSION_TARGET_MISMATCH"
    ):
        backend.run_full_pretraining(Path("config"), Path("manifest"), {}, **kwargs)
    assert calls == []


def test_valid_permission_reaches_reader_only_after_both_gates(
    monkeypatch, tmp_path: Path
) -> None:
    permission = _permission(tmp_path)
    calls: list[str] = []
    config = SimpleNamespace(
        resume_checkpoint=None,
        disk_budget={"minimum_free_bytes_before_start": 0},
        output_dir="output",
        train_dataset="train",
        model=SimpleNamespace(context_length=8, vocab_size=32),
        seed=17,
        to_training_config=lambda: object(),
    )

    original_gate = backend.require_dataset_training_activation

    def activation_gate(*args, **kwargs):
        calls.append("dataset_permission")
        return original_gate(*args, **kwargs)

    def readiness_gate(_report):
        calls.append("readiness")

    def reader_sentinel(*_args, **_kwargs):
        calls.append("reader")
        raise TrainingError("SYNTHETIC_READER_BOUNDARY", "stop before data access")

    monkeypatch.setattr(backend, "require_dataset_training_activation", activation_gate)
    monkeypatch.setattr(backend, "require_full_pretraining_approval", readiness_gate)
    monkeypatch.setattr(
        backend,
        "require_training_execution_request",
        lambda *_args, **_kwargs: calls.append("request"),
    )
    monkeypatch.setattr(
        backend,
        "issue_training_execution_approval",
        lambda _request: calls.append("issuer") or object(),
    )
    monkeypatch.setattr(
        backend,
        "consume_training_execution_approval",
        lambda *_args, **_kwargs: calls.append("approval"),
    )
    monkeypatch.setattr(
        backend.FullPretrainingConfig, "from_yaml", lambda _path: config
    )
    monkeypatch.setattr(
        backend, "resolve_full_pretraining_path", lambda *_args: tmp_path / "absent"
    )
    monkeypatch.setattr(backend, "seed_everything", lambda _seed: calls.append("seed"))
    monkeypatch.setattr(backend, "_lineage", lambda _config: {})
    monkeypatch.setattr(backend, "TokenizedJsonlDataset", reader_sentinel)
    monkeypatch.setattr(
        backend.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=1),
    )

    with pytest.raises(TrainingError, match="SYNTHETIC_READER_BOUNDARY"):
        backend.run_full_pretraining(
            Path("config"),
            Path("manifest"),
            {"execution_allowed": True},
            **_run_kwargs(permission),
        )
    assert calls == [
        "dataset_permission",
        "readiness",
        "request",
        "issuer",
        "approval",
        "seed",
        "reader",
    ]


def test_cli_execute_cannot_synthesize_permission(monkeypatch, capsys) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("permission absence must stop before I/O")

    monkeypatch.setattr(cli, "resolve_repository_path", forbidden)
    monkeypatch.setattr(cli, "inspect_full_pretraining_readiness", forbidden)
    result = cli.main(["--config", "config", "--manifest", "manifest", "--execute"])
    assert result == 2
    assert "TRAINING_EXECUTION_APPROVAL_REQUIRED" in capsys.readouterr().err
