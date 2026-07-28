"""In-memory, synthetic-only orchestration for the SFT processing backend."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from .processing_manifest import ProcessingManifestSchema
from .processing_rules import ProcessingRuleError, evaluate_rule
from .processing_statistics import ProcessingStatistics, build_processing_statistics
from .processing_validation import (
    MAX_SYNTHETIC_RECORDS,
    ProcessingValidationError,
    ValidatedSFTRecord,
    validate_manifest,
    validate_sft_record,
)


@dataclass(frozen=True)
class ProcessingResult:
    records: tuple[ValidatedSFTRecord, ...]
    statistics: ProcessingStatistics
    manifest_generated: bool = False
    processed_dataset_created: bool = False
    execution_allowed: bool = False


def process_synthetic_records(
    records: Iterable[Mapping[str, object]],
    manifest: ProcessingManifestSchema,
) -> ProcessingResult:
    """Validate the backend with bounded in-memory synthetic records only."""

    validate_manifest(manifest)
    try:
        materialized = tuple(records)
    except TypeError as exc:
        raise ProcessingValidationError("INVALID_RECORD_COLLECTION") from exc
    if len(materialized) > MAX_SYNTHETIC_RECORDS:
        raise ProcessingValidationError("SYNTHETIC_RECORD_LIMIT_EXCEEDED")

    validated = tuple(validate_sft_record(record) for record in materialized)
    rules = {rule.name: rule for rule in manifest.rule_set}
    applied_by_rule = {name: 0 for name in manifest.processing_order}
    excluded_by_rule = {name: 0 for name in manifest.processing_order}
    retained: list[ValidatedSFTRecord] = []

    for record in validated:
        excluded = False
        for name in manifest.processing_order:
            try:
                decision = evaluate_rule(rules[name], record.metadata)
            except ProcessingRuleError as exc:
                raise ProcessingValidationError(str(exc)) from exc
            if decision.applied:
                applied_by_rule[name] += 1
            if decision.exclude:
                excluded_by_rule[name] += 1
                excluded = True
                break
        if not excluded:
            retained.append(record)

    statistics = build_processing_statistics(
        input_count=len(validated),
        applied_by_rule=applied_by_rule,
        excluded_by_rule=excluded_by_rule,
    )
    return ProcessingResult(records=tuple(retained), statistics=statistics)
