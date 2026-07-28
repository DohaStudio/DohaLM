"""Immutable aggregate-only statistics for synthetic processing tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ProcessingStatisticsError(ValueError):
    """Aggregate counts are internally inconsistent."""


@dataclass(frozen=True)
class RuleImpact:
    rule: str
    applied_count: int
    excluded_count: int


@dataclass(frozen=True)
class ProcessingStatistics:
    input_count: int
    processed_count: int
    retained_count: int
    excluded_count: int
    rule_impacts: tuple[RuleImpact, ...]
    validation_status: str


def build_processing_statistics(
    *,
    input_count: int,
    applied_by_rule: Mapping[str, int],
    excluded_by_rule: Mapping[str, int],
) -> ProcessingStatistics:
    """Build deterministic aggregate statistics without record identifiers."""

    if isinstance(input_count, bool) or not isinstance(input_count, int) or input_count < 0:
        raise ProcessingStatisticsError("INVALID_INPUT_COUNT")
    if set(applied_by_rule) != set(excluded_by_rule):
        raise ProcessingStatisticsError("RULE_STATISTICS_MISMATCH")

    impacts: list[RuleImpact] = []
    for rule in applied_by_rule:
        applied = applied_by_rule[rule]
        excluded = excluded_by_rule[rule]
        if (
            isinstance(applied, bool)
            or not isinstance(applied, int)
            or isinstance(excluded, bool)
            or not isinstance(excluded, int)
            or applied < 0
            or excluded < 0
            or excluded > applied
        ):
            raise ProcessingStatisticsError("INVALID_RULE_STATISTICS")
        impacts.append(RuleImpact(rule, applied, excluded))

    excluded_count = sum(impact.excluded_count for impact in impacts)
    if excluded_count > input_count:
        raise ProcessingStatisticsError("EXCLUDED_COUNT_EXCEEDS_INPUT")
    return ProcessingStatistics(
        input_count=input_count,
        processed_count=input_count,
        retained_count=input_count - excluded_count,
        excluded_count=excluded_count,
        rule_impacts=tuple(impacts),
        validation_status="passed",
    )
