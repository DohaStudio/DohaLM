from __future__ import annotations

import importlib.util
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType

import pytest

import src.training.dataset_training_entry as consumer
from src.data.checksums import checksum_value
from src.data.common_dataset_contracts import CommonContractRuntimeError
from src.training.dataset_training_entry import evaluate_dataset_training_entry


def _publication_fixtures() -> ModuleType:
    path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location(
        "_consumer_publication_fixtures", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("publication fixtures unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(tmp_path: Path) -> dict:
    fixtures = _publication_fixtures()
    published = fixtures.publish(tmp_path / "synthetic-publication")
    manifest = published.dataset_manifest
    return {
        "dataset_version": published.dataset_version,
        "dataset_manifest": manifest,
        "upstream_objects": fixtures.upstream(),
        "evaluated_at": "2026-08-11T12:00:00Z",
        "readiness_report": {
            "status": "ready_for_execution",
            "execution_allowed": True,
            "inspection_only": True,
            "training_started": False,
            "blocking_codes": [],
        },
        "expected_split_id": manifest["split_id"],
        "artifact_references": deepcopy(manifest["object_file_artifact_refs"]),
    }


def _refresh_manifest_checksum(values: dict) -> None:
    manifest = values["dataset_manifest"]
    projection = dict(manifest)
    projection.pop("manifest_checksum")
    manifest["manifest_checksum"] = checksum_value(projection)


def test_valid_pair_returns_immutable_non_activating_permission(tmp_path: Path):
    values = _inputs(tmp_path)
    result = evaluate_dataset_training_entry(**values)
    assert result.allowed is True
    assert result.reason_codes == ()
    assert result.dataset_version_id == "dataset_version_1"
    assert result.dataset_manifest_id == "dataset_manifest_1"
    assert result.pair_fingerprint.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        result.allowed = False
    for forbidden in (
        "TokenizedJsonlDataset",
        "DohaLMTiny",
        "Trainer",
        "run_full_pretraining",
        "evaluate_language_model",
    ):
        assert forbidden not in vars(consumer)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("not-frozen", "DATASET_VERSION_NOT_FROZEN"),
        ("not-issued", "DATASET_MANIFEST_NOT_ISSUED"),
        ("version-training-blocked", "DATASET_VERSION_INVALID"),
        ("manifest-training-blocked", "DATASET_TRAINING_NOT_ALLOWED"),
    ),
)
def test_lifecycle_and_training_permission_fail_closed(
    tmp_path: Path, mutation: str, code: str
):
    values = _inputs(tmp_path)
    if mutation == "not-frozen":
        values["dataset_version"].update(
            status="approved", frozen=False, training_allowed=False
        )
    elif mutation == "not-issued":
        values["dataset_manifest"].update(
            manifest_status="draft", training_allowed=False
        )
        _refresh_manifest_checksum(values)
    elif mutation == "version-training-blocked":
        values["dataset_version"]["training_allowed"] = False
    else:
        values["dataset_manifest"]["training_allowed"] = False
        _refresh_manifest_checksum(values)
    assert evaluate_dataset_training_entry(**values).reason_codes == (code,)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("manifest-id", "DATASET_MANIFEST_INVALID"),
        ("source-id", "DATASET_PAIR_IDENTITY_MISMATCH"),
        ("source-checksum", "DATASET_PAIR_CHECKSUM_MISMATCH"),
        ("manifest-checksum", "DATASET_PAIR_CHECKSUM_MISMATCH"),
    ),
)
def test_pair_identity_and_checksum_fail_closed(
    tmp_path: Path, mutation: str, code: str
):
    values = _inputs(tmp_path)
    manifest = values["dataset_manifest"]
    if mutation == "manifest-id":
        manifest["dataset_manifest_id"] = "dataset_manifest_other"
    elif mutation == "source-id":
        manifest["source_dataset_version_id"] = "dataset_version_other"
    elif mutation == "source-checksum":
        manifest["source_dataset_version_checksum"] = "sha256:" + "0" * 64
    else:
        manifest["manifest_checksum"] = "sha256:" + "0" * 64
    if mutation != "manifest-checksum":
        _refresh_manifest_checksum(values)
    assert evaluate_dataset_training_entry(**values).reason_codes == (code,)


@pytest.mark.parametrize("mutation", ("expired", "revoked", "missing"))
def test_scenario_expiry_revocation_and_missing_upstream_are_blocked(
    tmp_path: Path, mutation: str
):
    values = _inputs(tmp_path)
    if mutation == "expired":
        values["evaluated_at"] = "2028-08-11T12:00:00Z"
    elif mutation == "revoked":
        rights = next(
            item
            for item in values["upstream_objects"]
            if item["schema_name"] == "rights_metadata"
        )
        rights["retention_allowed"]["allowed"] = False
    else:
        values["upstream_objects"].pop()
    assert evaluate_dataset_training_entry(**values).reason_codes == (
        "DATASET_PUBLICATION_SCENARIO_INVALID",
    )


def test_readiness_split_and_artifact_references_are_explicit(tmp_path: Path):
    blocked = _inputs(tmp_path / "readiness")
    blocked["readiness_report"]["execution_allowed"] = False
    blocked["readiness_report"]["blocking_codes"] = ["SYNTHETIC_BLOCKER"]
    assert evaluate_dataset_training_entry(**blocked).reason_codes == (
        "FULL_PRETRAINING_READINESS_BLOCKED",
    )

    split = _inputs(tmp_path / "split")
    split["expected_split_id"] = "split_other"
    assert evaluate_dataset_training_entry(**split).reason_codes == (
        "DATASET_SPLIT_REFERENCE_MISMATCH",
    )

    artifact = _inputs(tmp_path / "artifact")
    artifact["artifact_references"][0]["object_id"] = "artifact_other"
    assert evaluate_dataset_training_entry(**artifact).reason_codes == (
        "DATASET_ARTIFACT_REFERENCE_MISMATCH",
    )


def test_pending_execution_approval_remains_technically_ready(tmp_path: Path):
    values = _inputs(tmp_path)
    values["readiness_report"].update(
        status="ready_awaiting_final_execution_approval",
        execution_allowed=False,
        blocking_codes=["FULL_PRETRAINING_NOT_APPROVED"],
    )

    permission = evaluate_dataset_training_entry(**values)

    assert permission.allowed is True
    assert permission.reason_codes == ()
    assert values["readiness_report"]["execution_allowed"] is False


def test_malformed_pin_failure_and_errors_are_sanitized(monkeypatch, tmp_path: Path):
    malformed = _inputs(tmp_path / "malformed")
    malformed["dataset_version"] = {"secret": "raw-private-payload"}
    decision = evaluate_dataset_training_entry(**malformed)
    assert decision.allowed is False
    assert decision.reason_codes == ("DATASET_VERSION_INVALID",)
    assert "raw-private-payload" not in repr(decision)

    unavailable = _inputs(tmp_path / "runtime")

    def fail_runtime() -> None:
        raise CommonContractRuntimeError

    monkeypatch.setattr(consumer, "verify_common_contract_runtime", fail_runtime)
    assert evaluate_dataset_training_entry(**unavailable).reason_codes == (
        "COMMON_CONTRACT_RUNTIME_UNAVAILABLE",
    )


def test_inputs_are_snapshotted_and_validation_order_precedes_readiness(
    monkeypatch, tmp_path: Path
):
    values = _inputs(tmp_path)
    calls: list[str] = []
    for name in (
        "verify_common_contract_runtime",
        "validate_dataset_version",
        "validate_dataset_manifest",
        "validate_dataset_publication_scenario",
        "require_full_pretraining_technical_readiness",
    ):
        original = getattr(consumer, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(consumer, name, wrapper)

    result = evaluate_dataset_training_entry(**values)
    values["dataset_version"]["object_id"] = "mutated"
    values["dataset_manifest"]["object_id"] = "mutated"
    values["upstream_objects"].clear()
    assert result.allowed is True
    assert result.dataset_version_id == "dataset_version_1"
    assert result.dataset_manifest_id == "dataset_manifest_1"
    assert calls == [
        "verify_common_contract_runtime",
        "validate_dataset_version",
        "validate_dataset_manifest",
        "validate_dataset_publication_scenario",
        "require_full_pretraining_technical_readiness",
    ]
