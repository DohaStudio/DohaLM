"""Fail-closed validators for synthetic SFT processing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping

from .processing_manifest import (
    MANIFEST_VERSION,
    OUTPUT_SCHEMA_FIELDS,
    STATISTICS_FIELDS,
    InputDatasetIdentity,
    ProcessingApproval,
    ProcessingManifestSchema,
)
from .processing_rules import (
    CANONICAL_SELECTION,
    EXACT_DUPLICATE,
    KNOWN_RULES,
    LEAKAGE,
    PROCESSING_ORDER,
    VALIDATION_EXCLUSION,
    ProcessingRule,
)


MAX_SYNTHETIC_RECORDS = 100


class ProcessingValidationError(ValueError):
    """A processing request is outside the approved synthetic-only contract."""


@dataclass(frozen=True)
class ValidatedSFTRecord:
    instruction: str
    input: str | None
    output: str
    system: str | None
    metadata: Mapping[str, object]


def validate_rule_set(
    rules: tuple[ProcessingRule, ...],
    processing_order: tuple[str, ...],
) -> None:
    if not isinstance(rules, tuple) or not isinstance(processing_order, tuple):
        raise ProcessingValidationError("INVALID_RULE_SET")
    names: list[str] = []
    for rule in rules:
        if not isinstance(rule, ProcessingRule):
            raise ProcessingValidationError("INVALID_RULE_SET")
        if not isinstance(rule.name, str) or rule.name not in KNOWN_RULES:
            raise ProcessingValidationError("UNKNOWN_RULE")
        if not isinstance(rule.enabled, bool):
            raise ProcessingValidationError("INVALID_RULE_ENABLED")
        names.append(rule.name)
    if len(names) != len(set(names)):
        raise ProcessingValidationError("DUPLICATE_RULE")
    if set(names) != KNOWN_RULES:
        raise ProcessingValidationError("MISSING_RULE")
    if processing_order != PROCESSING_ORDER:
        raise ProcessingValidationError("INVALID_PROCESSING_ORDER")

    enabled = {rule.name for rule in rules if rule.enabled}
    if CANONICAL_SELECTION in enabled and EXACT_DUPLICATE not in enabled:
        raise ProcessingValidationError("RULE_CONFLICT")
    if VALIDATION_EXCLUSION in enabled and LEAKAGE not in enabled:
        raise ProcessingValidationError("RULE_CONFLICT")


def validate_manifest(manifest: ProcessingManifestSchema) -> None:
    if not isinstance(manifest, ProcessingManifestSchema):
        raise ProcessingValidationError("INVALID_MANIFEST")
    if manifest.manifest_version != MANIFEST_VERSION:
        raise ProcessingValidationError("INVALID_MANIFEST_VERSION")
    identity = manifest.input_dataset
    if not isinstance(identity, InputDatasetIdentity):
        raise ProcessingValidationError("INVALID_INPUT_DATASET")
    if (
        not isinstance(identity.dataset_id, str)
        or not identity.dataset_id.startswith("SYNTHETIC-")
        or not isinstance(identity.dataset_version, str)
        or not identity.dataset_version
        or identity.component != "SFT"
        or identity.synthetic is not True
        or manifest.dataset_version != identity.dataset_version
    ):
        raise ProcessingValidationError("INVALID_INPUT_DATASET")
    if manifest.output_schema != OUTPUT_SCHEMA_FIELDS:
        raise ProcessingValidationError("MISSING_SCHEMA")
    if manifest.statistics != STATISTICS_FIELDS:
        raise ProcessingValidationError("INVALID_STATISTICS_SCHEMA")
    if manifest.approval is None:
        raise ProcessingValidationError("MISSING_APPROVAL")
    approval = manifest.approval
    if not isinstance(approval, ProcessingApproval):
        raise ProcessingValidationError("INVALID_APPROVAL")
    if (
        not isinstance(approval.approval_id, str)
        or not approval.approval_id.startswith("SYNTHETIC-")
        or approval.synthetic_validation_allowed is not True
        or approval.processing_allowed is not False
        or approval.training_allowed is not False
        or approval.execution_allowed is not False
    ):
        raise ProcessingValidationError("INVALID_APPROVAL")
    validate_rule_set(manifest.rule_set, manifest.processing_order)


def validate_sft_record(record: Mapping[str, object]) -> ValidatedSFTRecord:
    if not isinstance(record, Mapping) or set(record) != set(OUTPUT_SCHEMA_FIELDS):
        raise ProcessingValidationError("MISSING_SCHEMA")
    instruction = record["instruction"]
    input_value = record["input"]
    output = record["output"]
    system = record["system"]
    metadata = record["metadata"]
    if not isinstance(instruction, str) or not instruction.strip():
        raise ProcessingValidationError("INVALID_INSTRUCTION")
    if input_value is not None and not isinstance(input_value, str):
        raise ProcessingValidationError("INVALID_INPUT")
    if not isinstance(output, str) or not output.strip():
        raise ProcessingValidationError("INVALID_OUTPUT")
    if system is not None and not isinstance(system, str):
        raise ProcessingValidationError("INVALID_SYSTEM")
    if not isinstance(metadata, Mapping) or metadata.get("synthetic") is not True:
        raise ProcessingValidationError("NON_SYNTHETIC_RECORD")
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, (str, bool, int, float, type(None))):
            raise ProcessingValidationError("INVALID_METADATA")
    return ValidatedSFTRecord(
        instruction=instruction,
        input=input_value,
        output=output,
        system=system,
        metadata=MappingProxyType(dict(metadata)),
    )
