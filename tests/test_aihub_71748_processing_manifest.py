from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path, PureWindowsPath
import re

import pytest
import yaml

from src.data.processing import (
    AIHub71748ManifestError,
    validate_aihub_71748_processing_manifest,
)


MANIFEST_PATH = Path("configs/data/aihub-71748-sft-processing-v1.yaml")


def _manifest() -> dict[str, object]:
    loaded = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _error(manifest: dict[str, object], code: str) -> None:
    with pytest.raises(AIHub71748ManifestError, match=f"^{code}$"):
        validate_aihub_71748_processing_manifest(manifest)


def test_canonical_manifest_is_valid_and_non_executable() -> None:
    manifest = _manifest()

    result = validate_aihub_71748_processing_manifest(manifest)

    assert result.dataset_id == "AIHUB-71748"
    assert result.component == "SFT"
    assert result.manifest_version == 1
    assert result.rule_count == 6
    assert result.processing_allowed is False
    assert result.tokenization_allowed is False
    assert result.training_allowed is False
    assert result.execution_allowed is False


def test_validator_accepts_only_an_in_memory_mapping() -> None:
    signature = inspect.signature(validate_aihub_71748_processing_manifest)

    assert tuple(signature.parameters) == ("manifest",)


@pytest.mark.parametrize(
    ("field", "value"),
    [("dataset_id", "SYNTHETIC"), ("component", "GENERAL")],
)
def test_identity_mismatch_fails_closed(field: str, value: str) -> None:
    manifest = _manifest()
    manifest["manifest_identity"][field] = value  # type: ignore[index]

    _error(manifest, "DATASET_IDENTITY_MISMATCH")


def test_input_count_and_join_contract_fail_closed() -> None:
    count = _manifest()
    count["input_contract"]["records"]["Total"] = 1  # type: ignore[index]
    join = _manifest()
    join["input_contract"]["join_relationship"] = "many_to_one"  # type: ignore[index]

    _error(count, "INPUT_RECORD_COUNT_MISMATCH")
    _error(join, "JOIN_CONTRACT_MISMATCH")


def test_output_schema_mismatch_fails_closed() -> None:
    manifest = _manifest()
    manifest["output_schema"]["metadata"]["training_input"] = True  # type: ignore[index]

    _error(manifest, "OUTPUT_SCHEMA_MISMATCH")


def test_rule_order_mismatch_fails_closed() -> None:
    manifest = _manifest()
    manifest["rule_order"] = list(reversed(manifest["rule_order"]))  # type: ignore[arg-type]

    _error(manifest, "RULE_ORDER_MISMATCH")


def test_unknown_rule_fails_closed() -> None:
    manifest = _manifest()
    rules = manifest["processing_rules"]  # type: ignore[assignment]
    rules["UNKNOWN_RULE"] = rules.pop("PII_POLICY")  # type: ignore[index,union-attr]

    _error(manifest, "UNKNOWN_RULE")


def test_unknown_action_fails_closed() -> None:
    manifest = _manifest()
    manifest["processing_rules"]["PII_POLICY"]["critical_candidate"]["action"] = "DELETE"  # type: ignore[index]

    _error(manifest, "UNKNOWN_ACTION")


@pytest.mark.parametrize(
    ("key", "value"),
    [("review_min", -0.1), ("review_min", 0.98), ("high_similarity_min", 1.0)],
)
def test_near_duplicate_threshold_range_fails_closed(
    key: str,
    value: float,
) -> None:
    manifest = _manifest()
    manifest["thresholds"]["near_duplicate"][key] = value  # type: ignore[index]

    _error(manifest, "INVALID_THRESHOLD")


def test_negative_validation_minimum_fails_closed() -> None:
    manifest = _manifest()
    manifest["validation_policy"]["minimum_validation_records"] = -1  # type: ignore[index]

    _error(manifest, "INVALID_THRESHOLD")


@pytest.mark.parametrize("rate", [-0.1, 1.1])
def test_exclusion_rate_range_fails_closed(rate: float) -> None:
    manifest = _manifest()
    manifest["expected_statistics"]["output"]["maximum_total_exclusion_rate"] = rate  # type: ignore[index]

    _error(manifest, "INVALID_THRESHOLD")


def test_raw_and_output_path_collision_fails_closed() -> None:
    manifest = _manifest()
    raw = manifest["output_contract"]["raw_root"]  # type: ignore[index]
    manifest["output_contract"]["processed_root"] = raw  # type: ignore[index]

    _error(manifest, "OUTPUT_PATH_CONFLICT")


def test_absolute_local_path_fails_closed() -> None:
    manifest = _manifest()
    manifest["output_contract"]["raw_root"] = "/forbidden/source"  # type: ignore[index]

    _error(manifest, "OUTPUT_PATH_CONFLICT")


def test_overwrite_permission_fails_closed() -> None:
    manifest = _manifest()
    manifest["output_contract"]["overwrite_allowed"] = True  # type: ignore[index]

    _error(manifest, "OUTPUT_PATH_CONFLICT")


def test_missing_approval_fails_closed() -> None:
    manifest = _manifest()
    manifest.pop("processing_approval")

    _error(manifest, "MISSING_APPROVAL")


@pytest.mark.parametrize(
    "field",
    [
        "processing_allowed",
        "tokenization_allowed",
        "training_allowed",
        "execution_allowed",
        "retry_allowed",
        "resume_allowed",
        "overwrite_allowed",
    ],
)
def test_permission_escalation_fails_closed(field: str) -> None:
    manifest = _manifest()
    manifest["processing_approval"][field] = True  # type: ignore[index]

    _error(manifest, "APPROVAL_PERMISSION_ESCALATION")


def test_filled_approval_identity_fails_closed() -> None:
    manifest = _manifest()
    manifest["processing_approval"]["approval_id"] = "SYNTHETIC-APPROVAL"  # type: ignore[index]

    _error(manifest, "APPROVAL_PERMISSION_ESCALATION")


def test_rule_conflict_priority_fails_closed() -> None:
    manifest = _manifest()
    manifest["conflict_resolution"]["priority"] = ["KEEP", "BLOCKED"]  # type: ignore[index]

    _error(manifest, "RULE_CONFLICT")


def test_unknown_policy_state_fails_closed() -> None:
    manifest = _manifest()
    manifest["status"]["processing_execution"] = "approved"  # type: ignore[index]

    _error(manifest, "UNKNOWN_POLICY_STATE")


def test_manifest_contains_no_absolute_path_record_id_or_sha256_value() -> None:
    manifest = _manifest()
    scalar_strings: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str):
            scalar_strings.append(value)

    collect(manifest)

    assert not any(PureWindowsPath(value).is_absolute() for value in scalar_strings)
    assert not any("DohaLM-Datasets" in value for value in scalar_strings)
    assert not any(re.fullmatch(r"(?:sha256:)?[0-9a-fA-F]{64}", value) for value in scalar_strings)
    approval = manifest["processing_approval"]
    assert approval["manifest_sha256"] is None  # type: ignore[index]
    assert approval["approval_id"] is None  # type: ignore[index]
    assert approval["processing_run_id"] is None  # type: ignore[index]


def test_manifest_validation_does_not_mutate_input() -> None:
    manifest = _manifest()
    before = deepcopy(manifest)

    validate_aihub_71748_processing_manifest(manifest)

    assert manifest == before
