"""Deterministic rule contracts for synthetic SFT processing validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


SCHEMA_TRANSFORM = "schema_transform"
PII = "pii"
EXACT_DUPLICATE = "exact_duplicate"
CANONICAL_SELECTION = "canonical_selection"
NEAR_DUPLICATE = "near_duplicate"
LEAKAGE = "leakage"
VALIDATION_EXCLUSION = "validation_exclusion"

PROCESSING_ORDER = (
    SCHEMA_TRANSFORM,
    PII,
    EXACT_DUPLICATE,
    CANONICAL_SELECTION,
    NEAR_DUPLICATE,
    LEAKAGE,
    VALIDATION_EXCLUSION,
)
KNOWN_RULES = frozenset(PROCESSING_ORDER)


class ProcessingRuleError(ValueError):
    """A rule or its precomputed synthetic signal is invalid."""


@dataclass(frozen=True)
class ProcessingRule:
    """A disabled-by-default rule declaration."""

    name: str
    enabled: bool = False


@dataclass(frozen=True)
class RuleDecision:
    rule: str
    applied: bool
    exclude: bool
    reason_code: str


def default_processing_rules() -> tuple[ProcessingRule, ...]:
    """Return the complete rule vocabulary with every rule disabled."""

    return tuple(ProcessingRule(name=name) for name in PROCESSING_ORDER)


def _signal(
    metadata: Mapping[str, object],
    key: str,
    allowed: frozenset[str],
) -> str:
    value = metadata.get(key)
    if not isinstance(value, str):
        raise ProcessingRuleError("MISSING_RULE_SIGNAL")
    if value not in allowed:
        raise ProcessingRuleError("INVALID_RULE_SIGNAL")
    return value


def evaluate_rule(
    rule: ProcessingRule,
    metadata: Mapping[str, object],
) -> RuleDecision:
    """Evaluate one rule against precomputed synthetic-only metadata signals."""

    if not isinstance(rule.name, str) or rule.name not in KNOWN_RULES:
        raise ProcessingRuleError("UNKNOWN_RULE")
    if not isinstance(rule.enabled, bool):
        raise ProcessingRuleError("INVALID_RULE_ENABLED")
    if not rule.enabled:
        return RuleDecision(rule.name, False, False, "RULE_DISABLED")

    if rule.name == SCHEMA_TRANSFORM:
        return RuleDecision(rule.name, True, False, "SCHEMA_ALREADY_NORMALIZED")
    if rule.name == PII:
        value = _signal(metadata, "pii", frozenset({"keep", "exclude"}))
        return RuleDecision(rule.name, True, value == "exclude", "PII_SIGNAL_APPLIED")
    if rule.name == EXACT_DUPLICATE:
        value = _signal(
            metadata,
            "exact_duplicate",
            frozenset({"unique", "duplicate"}),
        )
        return RuleDecision(
            rule.name,
            True,
            value == "duplicate",
            "EXACT_DUPLICATE_SIGNAL_APPLIED",
        )
    if rule.name == CANONICAL_SELECTION:
        value = _signal(
            metadata,
            "canonical",
            frozenset({"selected", "noncanonical"}),
        )
        return RuleDecision(
            rule.name,
            True,
            value == "noncanonical",
            "CANONICAL_SIGNAL_APPLIED",
        )
    if rule.name == NEAR_DUPLICATE:
        value = _signal(
            metadata,
            "near_duplicate",
            frozenset({"unique", "duplicate"}),
        )
        return RuleDecision(
            rule.name,
            True,
            value == "duplicate",
            "NEAR_DUPLICATE_SIGNAL_APPLIED",
        )
    if rule.name == LEAKAGE:
        value = _signal(metadata, "leakage", frozenset({"clear", "exclude"}))
        return RuleDecision(
            rule.name,
            True,
            value == "exclude",
            "LEAKAGE_SIGNAL_APPLIED",
        )

    value = _signal(metadata, "split", frozenset({"train", "validation"}))
    return RuleDecision(
        rule.name,
        True,
        value == "validation",
        "VALIDATION_SPLIT_SIGNAL_APPLIED",
    )
