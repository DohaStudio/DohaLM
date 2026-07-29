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


def detailed_statistics_schema(*, run_id: str, approval_id: str) -> dict[str, object]:
    """Return the complete aggregate-only Run 0003 statistics schema."""

    return {
        "run": {"run_id": run_id, "approval_id": approval_id, "status": "processing", "processing_calls": 0, "payload_open_sessions": 0},
        "input": {"Training": 0, "Validation": 0, "Total": 0},
        "source": {"sftdata_records": 0, "sftlabel_records": 0},
        "join": {"matched": 0, "orphan_data": 0, "orphan_label": 0, "duplicate_data_id": 0, "duplicate_label_id": 0, "split_mismatch": 0, "question_mismatch": 0},
        "schema": {"malformed_records": 0, "empty_instruction": 0, "empty_output": 0, "unknown_fields": 0},
        "pii": {"sensitive_topic_keep": 0, "single_identifier_review": 0, "multiple_identifier_blocked": 0, "identifier_sensitive_blocked": 0, "critical_blocked": 0, "training_excluded": 0, "validation_excluded": 0},
        "exact_duplicate": {"same_split_groups": 0, "canonical_kept": 0, "same_split_excluded": 0, "cross_split_groups": 0, "validation_excluded": 0, "question_conflicts": 0, "answer_reuse_records": 0},
        "near_duplicate": {"same_split_review": 0, "cross_split_question_review": 0, "cross_split_question_validation_excluded": 0, "cross_split_answer_review": 0, "cross_split_qa_validation_excluded": 0},
        "leakage": {"exact_qa_validation_excluded": 0, "normalized_qa_validation_excluded": 0, "exact_question_validation_excluded": 0, "normalized_question_validation_excluded": 0, "near_question_review": 0, "answer_only_kept": 0, "evaluation_prompt_blocked": 0, "candidate_prompt_blocked": 0},
        "actions": {"keep": 0, "canonical": 0, "review": 0, "blocked": 0, "training_excluded": 0, "validation_excluded": 0, "unresolved": 0},
        "output": {"Training": 0, "Validation": 0, "Total": 0, "excluded_total": 0, "exclusion_rate": 0.0, "output_files": 0, "output_bytes": 0},
        "runtime": {"elapsed_seconds": 0.0, "peak_memory_mib": 0.0, "soft_runtime_triggered": False, "soft_memory_triggered": False},
        "validation": {"jsonl_valid": False, "split_isolation_valid": False, "checksum_valid": False, "source_immutable": False, "output_budget_valid": False},
    }


def validate_detailed_statistics(statistics: Mapping[str, object]) -> None:
    expected = detailed_statistics_schema(run_id="x", approval_id="y")
    if set(statistics) != set(expected):
        raise ProcessingStatisticsError("STATISTICS_CONTRACT_INVALID")
    for section, fields in expected.items():
        candidate = statistics.get(section)
        if not isinstance(candidate, Mapping) or set(candidate) != set(fields):  # type: ignore[arg-type]
            raise ProcessingStatisticsError("STATISTICS_CONTRACT_INVALID")
    inputs = statistics["input"]  # type: ignore[index]
    outputs = statistics["output"]  # type: ignore[index]
    actions = statistics["actions"]  # type: ignore[index]
    if inputs["Training"] + inputs["Validation"] != inputs["Total"]:  # type: ignore[index,operator]
        raise ProcessingStatisticsError("STATISTICS_SPLIT_MISMATCH")
    if outputs["Training"] + outputs["Validation"] != outputs["Total"]:  # type: ignore[index,operator]
        raise ProcessingStatisticsError("STATISTICS_SPLIT_MISMATCH")
    action_total = sum(actions[name] for name in actions)  # type: ignore[index,arg-type]
    if action_total != inputs["Total"]:  # type: ignore[index]
        raise ProcessingStatisticsError("STATISTICS_ACTION_MISMATCH")
    if outputs["Total"] + outputs["excluded_total"] != inputs["Total"]:  # type: ignore[index,operator]
        raise ProcessingStatisticsError("STATISTICS_TOTAL_MISMATCH")
    if actions["unresolved"] != 0:  # type: ignore[index]
        raise ProcessingStatisticsError("STATISTICS_ACTION_MISMATCH")
