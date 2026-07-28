from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from src.data.processing import (
    MANIFEST_VERSION,
    OUTPUT_SCHEMA_FIELDS,
    PROCESSING_ORDER,
    STATISTICS_FIELDS,
    InputDatasetIdentity,
    ProcessingApproval,
    ProcessingManifestSchema,
    ProcessingRule,
    ProcessingValidationError,
    default_processing_rules,
    process_synthetic_records,
)


def _manifest(
    *,
    rules: tuple[ProcessingRule, ...] | None = None,
    approval: ProcessingApproval | None = None,
) -> ProcessingManifestSchema:
    return ProcessingManifestSchema(
        input_dataset=InputDatasetIdentity(
            dataset_id="SYNTHETIC-SFT-UNIT",
            dataset_version="synthetic-v1",
            component="SFT",
            synthetic=True,
        ),
        dataset_version="synthetic-v1",
        rule_set=default_processing_rules() if rules is None else rules,
        processing_order=PROCESSING_ORDER,
        statistics=STATISTICS_FIELDS,
        output_schema=OUTPUT_SCHEMA_FIELDS,
        approval=approval
        or ProcessingApproval(
            approval_id="SYNTHETIC-PROCESSING-UNIT",
            synthetic_validation_allowed=True,
        ),
        manifest_version=MANIFEST_VERSION,
    )


def _record(**metadata: object) -> dict[str, object]:
    return {
        "instruction": "synthetic instruction",
        "input": "synthetic input",
        "output": "synthetic output",
        "system": None,
        "metadata": {"synthetic": True, **metadata},
    }


def _rules(*enabled: str) -> tuple[ProcessingRule, ...]:
    return tuple(
        ProcessingRule(name=name, enabled=name in enabled)
        for name in PROCESSING_ORDER
    )


def test_default_rules_are_complete_and_disabled() -> None:
    rules = default_processing_rules()

    assert tuple(rule.name for rule in rules) == PROCESSING_ORDER
    assert all(rule.enabled is False for rule in rules)


def test_normal_synthetic_flow_retains_records_and_never_creates_artifacts() -> None:
    source = [_record(), _record()]

    result = process_synthetic_records(source, _manifest())

    assert len(result.records) == 2
    assert result.statistics.input_count == 2
    assert result.statistics.processed_count == 2
    assert result.statistics.retained_count == 2
    assert result.statistics.excluded_count == 0
    assert result.statistics.validation_status == "passed"
    assert result.manifest_generated is False
    assert result.processed_dataset_created is False
    assert result.execution_allowed is False
    assert all(impact.applied_count == 0 for impact in result.statistics.rule_impacts)
    assert source[0]["metadata"] == {"synthetic": True}


def test_enabled_rules_apply_precomputed_synthetic_signals() -> None:
    manifest = _manifest(rules=_rules("exact_duplicate", "canonical_selection"))
    records = [
        _record(exact_duplicate="unique", canonical="selected"),
        _record(exact_duplicate="duplicate", canonical="noncanonical"),
    ]

    result = process_synthetic_records(records, manifest)

    impacts = {impact.rule: impact for impact in result.statistics.rule_impacts}
    assert result.statistics.retained_count == 1
    assert result.statistics.excluded_count == 1
    assert impacts["exact_duplicate"].applied_count == 2
    assert impacts["exact_duplicate"].excluded_count == 1
    assert impacts["canonical_selection"].applied_count == 1


def test_validation_exclusion_requires_leakage_and_excludes_validation() -> None:
    manifest = _manifest(rules=_rules("leakage", "validation_exclusion"))
    records = [
        _record(leakage="clear", split="train"),
        _record(leakage="clear", split="validation"),
    ]

    result = process_synthetic_records(records, manifest)

    assert result.statistics.retained_count == 1
    assert result.statistics.excluded_count == 1


@pytest.mark.parametrize(
    "rules",
    [
        _rules("canonical_selection"),
        _rules("validation_exclusion"),
    ],
)
def test_rule_conflicts_fail_closed(rules: tuple[ProcessingRule, ...]) -> None:
    with pytest.raises(ProcessingValidationError, match="^RULE_CONFLICT$"):
        process_synthetic_records([], _manifest(rules=rules))


def test_duplicate_rule_fails_closed() -> None:
    rules = default_processing_rules() + (ProcessingRule("pii"),)

    with pytest.raises(ProcessingValidationError, match="^DUPLICATE_RULE$"):
        process_synthetic_records([], _manifest(rules=rules))


def test_missing_rule_fails_closed() -> None:
    with pytest.raises(ProcessingValidationError, match="^MISSING_RULE$"):
        process_synthetic_records([], _manifest(rules=default_processing_rules()[:-1]))


def test_unknown_rule_fails_closed() -> None:
    rules = default_processing_rules()[:-1] + (ProcessingRule("unknown"),)

    with pytest.raises(ProcessingValidationError, match="^UNKNOWN_RULE$"):
        process_synthetic_records([], _manifest(rules=rules))


@pytest.mark.parametrize(
    ("manifest", "error"),
    [
        (replace(_manifest(), manifest_version="v0"), "INVALID_MANIFEST_VERSION"),
        (replace(_manifest(), approval=None), "MISSING_APPROVAL"),
        (replace(_manifest(), output_schema=("instruction",)), "MISSING_SCHEMA"),
        (replace(_manifest(), statistics=("input_count",)), "INVALID_STATISTICS_SCHEMA"),
        (
            replace(
                _manifest(),
                input_dataset=InputDatasetIdentity(
                    dataset_id="AIHUB-71748",
                    dataset_version="unknown",
                    component="SFT",
                    synthetic=False,
                ),
            ),
            "INVALID_INPUT_DATASET",
        ),
    ],
)
def test_invalid_manifest_contracts_fail_closed(
    manifest: ProcessingManifestSchema,
    error: str,
) -> None:
    with pytest.raises(ProcessingValidationError, match=f"^{error}$"):
        process_synthetic_records([], manifest)


@pytest.mark.parametrize(
    "approval",
    [
        ProcessingApproval("REAL-APPROVAL", True),
        ProcessingApproval("SYNTHETIC-X", False),
        ProcessingApproval("SYNTHETIC-X", True, processing_allowed=True),
        ProcessingApproval("SYNTHETIC-X", True, training_allowed=True),
        ProcessingApproval("SYNTHETIC-X", True, execution_allowed=True),
    ],
)
def test_invalid_or_downstream_approval_fails_closed(
    approval: ProcessingApproval,
) -> None:
    with pytest.raises(ProcessingValidationError, match="^INVALID_APPROVAL$"):
        process_synthetic_records([], _manifest(approval=approval))


def test_missing_record_schema_fails_closed() -> None:
    record = _record()
    del record["output"]

    with pytest.raises(ProcessingValidationError, match="^MISSING_SCHEMA$"):
        process_synthetic_records([record], _manifest())


def test_non_synthetic_record_fails_closed() -> None:
    record = _record()
    record["metadata"] = {"synthetic": False}

    with pytest.raises(ProcessingValidationError, match="^NON_SYNTHETIC_RECORD$"):
        process_synthetic_records([record], _manifest())


def test_enabled_rule_requires_valid_synthetic_signal() -> None:
    manifest = _manifest(rules=_rules("pii"))

    with pytest.raises(ProcessingValidationError, match="^MISSING_RULE_SIGNAL$"):
        process_synthetic_records([_record()], manifest)
    with pytest.raises(ProcessingValidationError, match="^INVALID_RULE_SIGNAL$"):
        process_synthetic_records([_record(pii="review")], manifest)


def test_record_limit_fails_closed() -> None:
    with pytest.raises(
        ProcessingValidationError,
        match="^SYNTHETIC_RECORD_LIMIT_EXCEEDED$",
    ):
        process_synthetic_records([_record()] * 101, _manifest())


def test_result_and_validated_metadata_are_immutable() -> None:
    result = process_synthetic_records([_record()], _manifest())

    with pytest.raises(FrozenInstanceError):
        result.execution_allowed = True  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.records[0].metadata["synthetic"] = False  # type: ignore[index]


def test_non_manifest_object_returns_fixed_fail_closed_error() -> None:
    with pytest.raises(ProcessingValidationError, match="^INVALID_MANIFEST$"):
        process_synthetic_records([], object())  # type: ignore[arg-type]
