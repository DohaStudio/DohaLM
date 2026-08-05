"""Synthetic-only EOS-DIAG-R5 hypothesis evidence assessor.

The assessor consumes immutable R4 analysis results and caller-declared,
metric-only evidence signals.  It validates evidence bindings and policy
eligibility without inventing numerical thresholds, selecting an actual
Candidate C hypothesis, or authorizing training.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .eos_diagnostic_artifacts import diagnostic_fingerprint
from .eos_diagnostic_backend import EVIDENCE_STATUSES, AnalysisResult
from .eos_hypothesis_policy import (
    DIRECTIONS,
    EVIDENCE_STRENGTHS,
    FORBIDDEN_OBSERVATION_KEYS,
    HYPOTHESIS_DIAGNOSTICS,
    HYPOTHESIS_IDS,
    INTERVENTION_CATEGORIES,
    SELECTION_STATUSES,
    aggregate_evidence_status,
)

ASSESSOR_SCHEMA_VERSION = 5
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FORBIDDEN_KEYS = FORBIDDEN_OBSERVATION_KEYS | {"record_id"}


class EOSHypothesisAssessorError(RuntimeError):
    """Fail-closed assessor error exposing only a stable safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise EOSHypothesisAssessorError(code)


def _strict(value: object, fields: Sequence[str], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _fail(code)
    if set(value) & _FORBIDDEN_KEYS:
        _fail(code)
    return value


def _text(value: object, code: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        _fail(code)
    return value


def _fingerprint(value: object, code: str) -> str:
    if type(value) is not str or not _FINGERPRINT.fullmatch(value):
        _fail(code)
    return value


def _boolean(value: object, code: str) -> bool:
    if type(value) is not bool:
        _fail(code)
    return value


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _metric_tree(value: object, code: str) -> None:
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail(code)
        return
    if type(value) is list:
        for item in value:
            _metric_tree(item, code)
        return
    if type(value) is dict:
        if set(value) & _FORBIDDEN_KEYS:
            _fail(code)
        for key, item in value.items():
            _text(key, code)
            _metric_tree(item, code)
        return
    _fail(code)


def _string_list(value: object, code: str) -> tuple[str, ...]:
    if type(value) is not list:
        _fail(code)
    result = tuple(_text(item, code) for item in value)
    if tuple(sorted(set(result))) != result:
        _fail(code)
    return result


@dataclass(frozen=True)
class EvidenceSignal:
    signal_id: str
    hypothesis_id: str
    direction: str
    diagnostic_id: str
    artifact_fingerprint: str
    metric_name: str
    comparison_scope: str
    observation: Any
    evidence_strength: str
    limitation_codes: tuple[str, ...]
    approval_required: bool
    signal_fingerprint: str

    def __post_init__(self) -> None:
        code = "EOS_HYPOTHESIS_INPUT_INVALID"
        _text(self.signal_id, code)
        if self.hypothesis_id not in HYPOTHESIS_IDS:
            _fail("EOS_HYPOTHESIS_POLICY_INVALID")
        if self.diagnostic_id not in HYPOTHESIS_DIAGNOSTICS[self.hypothesis_id]:
            _fail("EOS_HYPOTHESIS_POLICY_INVALID")
        if (
            self.direction not in DIRECTIONS
            or self.evidence_strength not in EVIDENCE_STRENGTHS
        ):
            _fail(code)
        _fingerprint(self.artifact_fingerprint, "EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        _text(self.metric_name, code)
        _text(self.comparison_scope, code)
        observation = _thaw(self.observation)
        _metric_tree(observation, code)
        limitations = _string_list(list(self.limitation_codes), code)
        _boolean(self.approval_required, code)
        supplied = _fingerprint(
            self.signal_fingerprint, "EOS_HYPOTHESIS_ARTIFACT_MISMATCH"
        )
        semantic = {
            "signal_id": self.signal_id,
            "hypothesis_id": self.hypothesis_id,
            "direction": self.direction,
            "diagnostic_id": self.diagnostic_id,
            "artifact_fingerprint": self.artifact_fingerprint,
            "metric_name": self.metric_name,
            "comparison_scope": self.comparison_scope,
            "observation": observation,
            "evidence_strength": self.evidence_strength,
            "limitation_codes": list(limitations),
            "approval_required": self.approval_required,
        }
        if diagnostic_fingerprint(semantic) != supplied:
            _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        object.__setattr__(self, "observation", _freeze(observation))
        object.__setattr__(self, "limitation_codes", limitations)

    @classmethod
    def from_mapping(cls, value: object) -> EvidenceSignal:
        code = "EOS_HYPOTHESIS_INPUT_INVALID"
        item = _strict(
            value,
            (
                "signal_id",
                "hypothesis_id",
                "direction",
                "diagnostic_id",
                "artifact_fingerprint",
                "metric_name",
                "comparison_scope",
                "observation",
                "evidence_strength",
                "limitation_codes",
                "approval_required",
                "signal_fingerprint",
            ),
            code,
        )
        hypothesis_id = item["hypothesis_id"]
        if hypothesis_id not in HYPOTHESIS_IDS:
            _fail("EOS_HYPOTHESIS_POLICY_INVALID")
        diagnostic_id = item["diagnostic_id"]
        if diagnostic_id not in HYPOTHESIS_DIAGNOSTICS[hypothesis_id]:
            _fail("EOS_HYPOTHESIS_POLICY_INVALID")
        if item["direction"] not in DIRECTIONS:
            _fail(code)
        if item["evidence_strength"] not in EVIDENCE_STRENGTHS:
            _fail(code)
        _metric_tree(item["observation"], code)
        limitations = _string_list(item["limitation_codes"], code)
        semantic = dict(item)
        supplied = _fingerprint(semantic.pop("signal_fingerprint"), code)
        if diagnostic_fingerprint(semantic) != supplied:
            _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        return cls(
            signal_id=_text(item["signal_id"], code),
            hypothesis_id=hypothesis_id,
            direction=item["direction"],
            diagnostic_id=diagnostic_id,
            artifact_fingerprint=_fingerprint(
                item["artifact_fingerprint"],
                "EOS_HYPOTHESIS_ARTIFACT_MISMATCH",
            ),
            metric_name=_text(item["metric_name"], code),
            comparison_scope=_text(item["comparison_scope"], code),
            observation=_thaw(item["observation"]),
            evidence_strength=item["evidence_strength"],
            limitation_codes=limitations,
            approval_required=_boolean(item["approval_required"], code),
            signal_fingerprint=supplied,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "hypothesis_id": self.hypothesis_id,
            "direction": self.direction,
            "diagnostic_id": self.diagnostic_id,
            "artifact_fingerprint": self.artifact_fingerprint,
            "metric_name": self.metric_name,
            "comparison_scope": self.comparison_scope,
            "observation": _thaw(self.observation),
            "evidence_strength": self.evidence_strength,
            "limitation_codes": list(self.limitation_codes),
            "approval_required": self.approval_required,
            "signal_fingerprint": self.signal_fingerprint,
        }


def _result_semantic(result: AnalysisResult) -> dict[str, Any]:
    return {
        "diagnostic_id": result.diagnostic_id,
        "artifact_type": result.artifact_type,
        "evidence_status": result.evidence_status,
        "records": [_thaw(item) for item in result.records],
        "summary": _thaw(result.summary),
        "limitations": list(result.limitations),
    }


def _validate_results(
    results: Sequence[AnalysisResult],
) -> tuple[
    tuple[AnalysisResult, ...], Mapping[str, tuple[str, ...]], Mapping[str, str]
]:
    values = tuple(results)
    if any(not isinstance(item, AnalysisResult) for item in values):
        _fail("EOS_HYPOTHESIS_INPUT_INVALID")
    if {item.diagnostic_id for item in values} != {
        f"D{index}" for index in range(1, 9)
    }:
        _fail("EOS_HYPOTHESIS_INPUT_INVALID")
    if (
        len([item for item in values if item.diagnostic_id == "D1"]) != 2
        or len(values) != 9
    ):
        _fail("EOS_HYPOTHESIS_INPUT_INVALID")
    fingerprints: dict[str, list[str]] = defaultdict(list)
    statuses: dict[str, list[str]] = defaultdict(list)
    for result in values:
        if result.evidence_status not in EVIDENCE_STATUSES:
            _fail("EOS_HYPOTHESIS_INPUT_INVALID")
        expected = diagnostic_fingerprint(_result_semantic(result))
        if result.result_fingerprint != expected:
            _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        fingerprints[result.diagnostic_id].append(result.result_fingerprint)
        statuses[result.diagnostic_id].append(result.evidence_status)
    normalized_fingerprints = MappingProxyType(
        {key: tuple(sorted(items)) for key, items in sorted(fingerprints.items())}
    )
    normalized_statuses = MappingProxyType(
        {
            key: aggregate_evidence_status(items)
            for key, items in sorted(statuses.items())
        }
    )
    return values, normalized_fingerprints, normalized_statuses


def _validate_summary(summary: Mapping[str, Any], diagnostic_run_id: str) -> None:
    code = "EOS_HYPOTHESIS_INPUT_INVALID"
    if not isinstance(summary, Mapping):
        _fail(code)
    value = _thaw(summary)
    required = {
        "diagnostic_run_id",
        "run_mode",
        "completed_diagnostics",
        "limited_diagnostics",
        "insufficient_diagnostics",
        "incompatible_diagnostics",
        "pure_greedy_summary",
        "repetition_summary",
        "eos_summary",
        "evidence_coverage",
        "unresolved_questions",
        "hypothesis_selection_allowed",
        "actual_candidate_b_status_changed",
        "summary_fingerprint",
    }
    if type(value) is not dict or set(value) != required:
        _fail(code)
    if (
        value["diagnostic_run_id"] != diagnostic_run_id
        or value["run_mode"] != "synthetic_only"
        or value["actual_candidate_b_status_changed"] is not False
    ):
        _fail("EOS_HYPOTHESIS_PRODUCTION_NOT_AUTHORIZED")
    semantic = dict(value)
    supplied = _fingerprint(
        semantic.pop("summary_fingerprint"), "EOS_HYPOTHESIS_ARTIFACT_MISMATCH"
    )
    if diagnostic_fingerprint(semantic) != supplied:
        _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")


@dataclass(frozen=True)
class AssessorInput:
    diagnostic_run_id: str
    policy_version: str
    candidate_b_identity_fingerprint: str
    generation_matrix_fingerprint: str
    results: tuple[AnalysisResult, ...]
    diagnostic_summary: Mapping[str, Any]
    signals: tuple[EvidenceSignal, ...]
    diagnostic_artifact_fingerprints: Mapping[str, tuple[str, ...]]
    diagnostic_statuses: Mapping[str, str]
    input_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "diagnostic_summary", _freeze(_thaw(self.diagnostic_summary))
        )
        object.__setattr__(
            self,
            "diagnostic_artifact_fingerprints",
            _freeze(_thaw(self.diagnostic_artifact_fingerprints)),
        )
        object.__setattr__(
            self, "diagnostic_statuses", _freeze(_thaw(self.diagnostic_statuses))
        )

    @classmethod
    def create(
        cls,
        *,
        diagnostic_run_id: str,
        policy_version: str,
        candidate_b_identity_fingerprint: str,
        generation_matrix_fingerprint: str,
        results: Sequence[AnalysisResult],
        diagnostic_summary: Mapping[str, Any],
        signals: Sequence[EvidenceSignal],
    ) -> AssessorInput:
        code = "EOS_HYPOTHESIS_INPUT_INVALID"
        run_id = _text(diagnostic_run_id, code)
        if not run_id.startswith("SYNTHETIC-"):
            _fail("EOS_HYPOTHESIS_PRODUCTION_NOT_AUTHORIZED")
        policy = _text(policy_version, "EOS_HYPOTHESIS_POLICY_INVALID")
        result_values, artifact_fingerprints, statuses = _validate_results(results)
        _validate_summary(diagnostic_summary, run_id)
        summary_value = _thaw(diagnostic_summary)
        expected_groups = {
            "completed_diagnostics": [
                key for key, status in statuses.items() if status == "complete"
            ],
            "limited_diagnostics": [
                key
                for key, status in statuses.items()
                if status == "complete_with_limitations"
            ],
            "insufficient_diagnostics": [
                key
                for key, status in statuses.items()
                if status == "insufficient_evidence"
            ],
            "incompatible_diagnostics": [
                key
                for key, status in statuses.items()
                if status == "incompatible_input"
            ],
        }
        if any(
            summary_value[field] != expected
            for field, expected in expected_groups.items()
        ) or summary_value["hypothesis_selection_allowed"] != (
            not expected_groups["insufficient_diagnostics"]
            and not expected_groups["incompatible_diagnostics"]
            and not any(
                status in {"blocked", "schema_only"} for status in statuses.values()
            )
        ):
            _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        signal_values = tuple(signals)
        if any(not isinstance(item, EvidenceSignal) for item in signal_values):
            _fail(code)
        signal_values = tuple(
            EvidenceSignal.from_mapping(item.as_dict()) for item in signal_values
        )
        if len({item.signal_id for item in signal_values}) != len(signal_values) or len(
            {item.signal_fingerprint for item in signal_values}
        ) != len(signal_values):
            _fail(code)
        for signal in signal_values:
            if (
                signal.artifact_fingerprint
                not in artifact_fingerprints[signal.diagnostic_id]
            ):
                _fail("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
        ordered_signals = tuple(sorted(signal_values, key=lambda item: item.signal_id))
        semantic = {
            "schema_version": ASSESSOR_SCHEMA_VERSION,
            "diagnostic_run_id": run_id,
            "policy_version": policy,
            "candidate_b_identity_fingerprint": _fingerprint(
                candidate_b_identity_fingerprint, "EOS_HYPOTHESIS_ARTIFACT_MISMATCH"
            ),
            "generation_matrix_fingerprint": _fingerprint(
                generation_matrix_fingerprint, "EOS_HYPOTHESIS_ARTIFACT_MISMATCH"
            ),
            "diagnostic_summary_fingerprint": diagnostic_summary["summary_fingerprint"],
            "diagnostic_artifact_fingerprints": {
                key: list(value) for key, value in artifact_fingerprints.items()
            },
            "signals": [item.as_dict() for item in ordered_signals],
        }
        return cls(
            diagnostic_run_id=run_id,
            policy_version=policy,
            candidate_b_identity_fingerprint=semantic[
                "candidate_b_identity_fingerprint"
            ],
            generation_matrix_fingerprint=semantic["generation_matrix_fingerprint"],
            results=result_values,
            diagnostic_summary=_thaw(diagnostic_summary),
            signals=ordered_signals,
            diagnostic_artifact_fingerprints=artifact_fingerprints,
            diagnostic_statuses=statuses,
            input_fingerprint=diagnostic_fingerprint(semantic),
        )


@dataclass(frozen=True)
class HypothesisAssessment:
    hypothesis_id: str
    status: str
    supporting_signals: tuple[str, ...]
    contradictory_signals: tuple[str, ...]
    insufficient_signals: tuple[str, ...]
    evidence_coverage: Mapping[str, Any]
    confidence: str
    unresolved_questions: tuple[str, ...]
    intervention_category: str
    allowed_next_actions: tuple[str, ...]
    prohibited_next_actions: tuple[str, ...]
    assessment_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_coverage", _freeze(_thaw(self.evidence_coverage))
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "status": self.status,
            "supporting_signals": list(self.supporting_signals),
            "contradictory_signals": list(self.contradictory_signals),
            "insufficient_signals": list(self.insufficient_signals),
            "evidence_coverage": _thaw(self.evidence_coverage),
            "confidence": self.confidence,
            "unresolved_questions": list(self.unresolved_questions),
            "intervention_category": self.intervention_category,
            "allowed_next_actions": list(self.allowed_next_actions),
            "prohibited_next_actions": list(self.prohibited_next_actions),
            "assessment_fingerprint": self.assessment_fingerprint,
        }


@dataclass(frozen=True)
class SelectionResult:
    selection_status: str
    proposed_hypothesis: str | None
    conditions: tuple[str, ...]
    training_intervention_allowed: bool
    actual_project_decision_changed: bool
    selection_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "selection_status": self.selection_status,
            "proposed_hypothesis": self.proposed_hypothesis,
            "conditions": list(self.conditions),
            "training_intervention_allowed": self.training_intervention_allowed,
            "actual_project_decision_changed": self.actual_project_decision_changed,
            "selection_fingerprint": self.selection_fingerprint,
        }


@dataclass(frozen=True)
class HypothesisAssessmentBundle:
    assessor_input: AssessorInput
    evidence_coverage: Mapping[str, Any]
    assessments: tuple[HypothesisAssessment, ...]
    selection_result: SelectionResult
    assessment_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_coverage", _freeze(_thaw(self.evidence_coverage))
        )


def _overall_coverage(value: AssessorInput) -> Mapping[str, Any]:
    statuses = _thaw(value.diagnostic_statuses)
    incompatible = [
        key for key, status in statuses.items() if status == "incompatible_input"
    ]
    unavailable = [
        key for key, status in statuses.items() if status in {"blocked", "schema_only"}
    ]
    insufficient = [
        key for key, status in statuses.items() if status == "insufficient_evidence"
    ]
    d2 = next(item for item in value.results if item.diagnostic_id == "D2")
    d4 = next(item for item in value.results if item.diagnostic_id == "D4")
    paired = (
        d2.evidence_status in {"complete", "complete_with_limitations"}
        and int(d2.summary.get("paired_observation_count", 0)) > 0
    )
    comparison = (
        d4.evidence_status in {"complete", "complete_with_limitations"}
        and d4.summary.get("packed_comparison_available") is True
    )
    reviewed = {
        hypothesis_id: any(
            signal.hypothesis_id == hypothesis_id
            and signal.direction in {"contradictory", "insufficient", "neutral"}
            for signal in value.signals
        )
        for hypothesis_id in HYPOTHESIS_IDS
    }
    review_count = sum(reviewed.values())
    contradiction_review = (
        "complete"
        if review_count == len(HYPOTHESIS_IDS)
        else ("partial" if review_count else "none")
    )
    if incompatible:
        rating = "incompatible"
    elif unavailable or insufficient:
        rating = "insufficient"
    elif not paired or not comparison:
        rating = "partial"
    elif contradiction_review == "complete" and all(
        status == "complete" for status in statuses.values()
    ):
        rating = "complete"
    else:
        rating = "substantial"
    return _freeze(
        {
            "coverage_status": rating,
            "required_diagnostics_available": [
                key for key in sorted(statuses) if key not in unavailable
            ],
            "diagnostic_statuses": statuses,
            "compatible_inputs": not incompatible,
            "paired_evidence_available": paired,
            "comparison_group_available": comparison,
            "contradiction_review_coverage": contradiction_review,
        }
    )


def _hypothesis_coverage(
    value: AssessorInput, hypothesis_id: str, signals: Sequence[EvidenceSignal]
) -> Mapping[str, Any]:
    diagnostics = HYPOTHESIS_DIAGNOSTICS[hypothesis_id]
    statuses = {key: value.diagnostic_statuses[key] for key in diagnostics}
    incompatible = any(status == "incompatible_input" for status in statuses.values())
    unavailable = any(
        status in {"blocked", "schema_only"} for status in statuses.values()
    )
    insufficient = any(
        status == "insufficient_evidence" for status in statuses.values()
    )
    contradiction_reviewed = any(
        signal.direction in {"contradictory", "insufficient", "neutral"}
        for signal in signals
    )
    if incompatible:
        rating = "incompatible"
    elif unavailable:
        rating = "insufficient"
    elif insufficient:
        rating = "partial"
    elif contradiction_reviewed and all(
        status == "complete" for status in statuses.values()
    ):
        rating = "complete"
    else:
        rating = "substantial"
    return _freeze(
        {
            "coverage_status": rating,
            "required_diagnostics_available": list(diagnostics),
            "diagnostic_statuses": statuses,
            "compatible_inputs": not incompatible,
            "paired_evidence_available": value.diagnostic_statuses["D2"]
            in {"complete", "complete_with_limitations"}
            if "D2" in diagnostics
            else None,
            "comparison_group_available": next(
                item for item in value.results if item.diagnostic_id == "D4"
            ).summary.get("packed_comparison_available")
            if "D4" in diagnostics
            else None,
            "contradiction_review_coverage": "reviewed"
            if contradiction_reviewed
            else "missing",
        }
    )


def _assess_one(value: AssessorInput, hypothesis_id: str) -> HypothesisAssessment:
    signals = tuple(
        signal for signal in value.signals if signal.hypothesis_id == hypothesis_id
    )
    supporting = tuple(
        signal.signal_id for signal in signals if signal.direction == "supporting"
    )
    contradictory = tuple(
        signal.signal_id for signal in signals if signal.direction == "contradictory"
    )
    insufficient = tuple(
        signal.signal_id for signal in signals if signal.direction == "insufficient"
    )
    neutral = tuple(
        signal.signal_id for signal in signals if signal.direction == "neutral"
    )
    contradiction_reviewed = bool(contradictory or insufficient or neutral)
    coverage = _hypothesis_coverage(value, hypothesis_id, signals)
    unresolved: list[str] = []
    if coverage["coverage_status"] in {"incompatible", "insufficient", "partial"}:
        status = "insufficient_evidence"
        confidence = "indeterminate"
        unresolved.append("REQUIRED_DIAGNOSTIC_EVIDENCE_INCOMPLETE")
    elif supporting and contradictory:
        status = "mixed_evidence"
        confidence = "low"
        unresolved.append("SUPPORT_AND_CONTRADICTION_BOTH_PRESENT")
    elif supporting:
        strengths = {
            signal.evidence_strength
            for signal in signals
            if signal.direction == "supporting"
        }
        approval = any(
            signal.approval_required
            for signal in signals
            if signal.direction == "supporting"
        )
        if (
            not contradiction_reviewed
            or bool(insufficient)
            or hypothesis_id == "H6_TRAINING_BUDGET"
            or approval
            or strengths <= {"weak", "indeterminate"}
        ):
            status = "conditionally_supported"
            confidence = "low" if hypothesis_id == "H6_TRAINING_BUDGET" else "medium"
            unresolved.append(
                "CONTRADICTION_REVIEW_REQUIRED"
                if not contradiction_reviewed
                else "APPROVAL_OR_ADDITIONAL_EVIDENCE_REQUIRED"
            )
        else:
            status = "supported"
            confidence = "medium"
    elif contradictory:
        status = "contradicted"
        confidence = "medium"
    elif neutral:
        status = "not_applicable"
        confidence = "indeterminate"
    else:
        status = "insufficient_evidence"
        confidence = "indeterminate"
        unresolved.append("NO_HYPOTHESIS_EVIDENCE_SIGNAL")
    if (
        hypothesis_id == "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH"
        and value.diagnostic_statuses["D2"] == "insufficient_evidence"
    ):
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("EXACT_PAIRING_EVIDENCE_REQUIRED")
    if (
        hypothesis_id in {"H3_BOUNDARY_FREQUENCY", "H4_PACKING_OBJECTIVE"}
        and coverage["comparison_group_available"] is not True
    ):
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("PACKED_NON_PACKED_COMPARISON_REQUIRED")
    allowed = ["review_evidence_only", "prepare_proposed_hypothesis_review"]
    if hypothesis_id == "H5_DECODING_PARAMETER":
        allowed = ["review_decoding_policy", "review_evidence_only"]
    elif hypothesis_id == "H6_TRAINING_BUDGET":
        allowed = ["design_separate_budget_experiment", "review_evidence_only"]
    prohibited = [
        "approve_candidate_c_config",
        "candidate_c_gpu",
        "candidate_c_training",
    ]
    semantic = {
        "hypothesis_id": hypothesis_id,
        "status": status,
        "supporting_signals": list(supporting),
        "contradictory_signals": list(contradictory),
        "insufficient_signals": list(insufficient),
        "evidence_coverage": _thaw(coverage),
        "confidence": confidence,
        "unresolved_questions": sorted(set(unresolved)),
        "intervention_category": INTERVENTION_CATEGORIES[hypothesis_id],
        "allowed_next_actions": sorted(allowed),
        "prohibited_next_actions": sorted(prohibited),
    }
    return HypothesisAssessment(
        hypothesis_id=hypothesis_id,
        status=status,
        supporting_signals=supporting,
        contradictory_signals=contradictory,
        insufficient_signals=insufficient,
        evidence_coverage=coverage,
        confidence=confidence,
        unresolved_questions=tuple(semantic["unresolved_questions"]),
        intervention_category=INTERVENTION_CATEGORIES[hypothesis_id],
        allowed_next_actions=tuple(semantic["allowed_next_actions"]),
        prohibited_next_actions=tuple(semantic["prohibited_next_actions"]),
        assessment_fingerprint=diagnostic_fingerprint(semantic),
    )


def _selection(
    coverage: Mapping[str, Any], assessments: Sequence[HypothesisAssessment]
) -> SelectionResult:
    by_id = {item.hypothesis_id: item for item in assessments}
    conditions: list[str] = []
    proposed: str | None = None
    if coverage["coverage_status"] != "complete":
        status = "diagnostic_incomplete"
        conditions.append("COMPLETE_COMPATIBLE_DIAGNOSTICS_REQUIRED")
    else:
        supported = [
            item.hypothesis_id for item in assessments if item.status == "supported"
        ]
        conditional = [
            item.hypothesis_id
            for item in assessments
            if item.status == "conditionally_supported"
        ]
        candidates = supported + conditional
        boundary_pair = {"H3_BOUNDARY_FREQUENCY", "H4_PACKING_OBJECTIVE"}
        exposure_loop_pair = {
            "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH",
            "H7_REPETITION_LOOP_COMPETITION",
        }
        if boundary_pair.issubset(candidates):
            status = "multiple_hypotheses_unresolved"
            conditions.append("BOUNDARY_FREQUENCY_AND_PACKING_CAUSALITY_UNRESOLVED")
        elif exposure_loop_pair.issubset(candidates):
            status = "multiple_hypotheses_unresolved"
            conditions.append("EXPOSURE_AND_LOOP_CAUSAL_DIRECTION_UNRESOLVED")
        elif len(candidates) > 1:
            status = "multiple_hypotheses_unresolved"
            conditions.append("MULTIPLE_SUPPORTED_HYPOTHESES_REQUIRE_CAUSAL_SEPARATION")
        elif len(supported) == 1:
            status, proposed = "selected", supported[0]
        elif len(conditional) == 1:
            status, proposed = "conditionally_selected", conditional[0]
            conditions.extend(by_id[proposed].unresolved_questions)
        else:
            status = "no_hypothesis_selected"
            conditions.append("NO_ELIGIBLE_SINGLE_HYPOTHESIS")
    if proposed == "H5_DECODING_PARAMETER":
        conditions.append("DECODING_POLICY_REVIEW_ONLY")
    if proposed == "H6_TRAINING_BUDGET":
        if status == "selected":
            _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
        conditions.extend(
            (
                "CAUSAL_CONFIDENCE_HIGH_FORBIDDEN",
                "SEPARATE_BUDGET_EXPERIMENT_APPROVAL_REQUIRED",
            )
        )
    semantic = {
        "selection_status": status,
        "proposed_hypothesis": proposed,
        "conditions": sorted(set(conditions)),
        "training_intervention_allowed": False,
        "actual_project_decision_changed": False,
    }
    return SelectionResult(
        selection_status=status,
        proposed_hypothesis=proposed,
        conditions=tuple(semantic["conditions"]),
        training_intervention_allowed=False,
        actual_project_decision_changed=False,
        selection_fingerprint=diagnostic_fingerprint(semantic),
    )


def validate_selection_result(
    selection: SelectionResult, assessments: Sequence[HypothesisAssessment]
) -> None:
    if (
        not isinstance(selection, SelectionResult)
        or selection.selection_status not in SELECTION_STATUSES
    ):
        _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
    by_id = {item.hypothesis_id: item for item in assessments}
    if set(by_id) != set(HYPOTHESIS_IDS) or len(by_id) != len(HYPOTHESIS_IDS):
        _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
    if (
        selection.training_intervention_allowed
        or selection.actual_project_decision_changed
    ):
        _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
    proposed = selection.proposed_hypothesis
    if selection.selection_status == "selected":
        if (
            proposed not in HYPOTHESIS_IDS
            or by_id[proposed].status != "supported"
            or proposed == "H6_TRAINING_BUDGET"
        ):
            _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
    elif selection.selection_status == "conditionally_selected":
        if (
            proposed not in HYPOTHESIS_IDS
            or by_id[proposed].status != "conditionally_supported"
            or not selection.conditions
        ):
            _fail("EOS_HYPOTHESIS_SELECTION_INVALID")
    elif proposed is not None:
        _fail("EOS_HYPOTHESIS_SELECTION_INVALID")


def assess_hypotheses(value: AssessorInput) -> HypothesisAssessmentBundle:
    if not isinstance(value, AssessorInput):
        _fail("EOS_HYPOTHESIS_INPUT_INVALID")
    coverage = _overall_coverage(value)
    assessments = tuple(
        _assess_one(value, hypothesis_id) for hypothesis_id in HYPOTHESIS_IDS
    )
    selection = _selection(coverage, assessments)
    validate_selection_result(selection, assessments)
    semantic = {
        "schema_version": ASSESSOR_SCHEMA_VERSION,
        "assessor_input_fingerprint": value.input_fingerprint,
        "evidence_coverage": _thaw(coverage),
        "assessments": [item.as_dict() for item in assessments],
        "selection_result": selection.as_dict(),
    }
    return HypothesisAssessmentBundle(
        assessor_input=value,
        evidence_coverage=coverage,
        assessments=assessments,
        selection_result=selection,
        assessment_fingerprint=diagnostic_fingerprint(semantic),
    )


def build_r1_hypothesis_payload(
    bundle: HypothesisAssessmentBundle,
) -> Mapping[str, Any]:
    if not isinstance(bundle, HypothesisAssessmentBundle):
        _fail("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    value = bundle.assessor_input
    contradictory = {
        item.hypothesis_id: list(item.contradictory_signals)
        for item in bundle.assessments
        if item.contradictory_signals
    }
    unresolved = sorted(
        {
            question
            for item in bundle.assessments
            for question in item.unresolved_questions
        }
        | set(bundle.selection_result.conditions)
    )
    semantic = {
        "analysis_status": "complete",
        "record_schema_version": ASSESSOR_SCHEMA_VERSION,
        "policy_version": value.policy_version,
        "diagnostic_run_id": value.diagnostic_run_id,
        "candidate_b_identity_fingerprint": value.candidate_b_identity_fingerprint,
        "generation_matrix_fingerprint": value.generation_matrix_fingerprint,
        "assessor_input_fingerprint": value.input_fingerprint,
        "diagnostic_artifact_fingerprints": {
            key: list(items)
            for key, items in value.diagnostic_artifact_fingerprints.items()
        },
        "evidence_coverage": _thaw(bundle.evidence_coverage),
        "evidence_signals": [signal.as_dict() for signal in value.signals],
        "hypothesis_assessments": [item.as_dict() for item in bundle.assessments],
        "selection_result": bundle.selection_result.as_dict(),
        "contradictory_evidence_summary": contradictory,
        "unresolved_questions": unresolved,
        "allowed_next_actions": ["review_evidence_only", "review_proposed_selection"],
        "prohibited_next_actions": [
            "approve_candidate_c_config",
            "candidate_c_gpu",
            "candidate_c_training",
        ],
        "actual_project_state": {
            "candidate_c_primary_hypothesis": "not_selected",
            "candidate_c_execution_allowed": False,
            "gate_c4": "blocked",
        },
    }
    return _freeze(
        {**semantic, "assessment_fingerprint": diagnostic_fingerprint(semantic)}
    )


def attach_hypothesis_assessment_to_summary(
    diagnostic_summary: Mapping[str, Any], bundle: HypothesisAssessmentBundle
) -> Mapping[str, Any]:
    if not isinstance(bundle, HypothesisAssessmentBundle):
        _fail("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _validate_summary(diagnostic_summary, bundle.assessor_input.diagnostic_run_id)
    payload_fingerprint = build_r1_hypothesis_payload(bundle)["assessment_fingerprint"]
    semantic = _thaw(diagnostic_summary)
    semantic.pop("summary_fingerprint")
    semantic.update(
        {
            "hypothesis_assessment_status": "completed_synthetic",
            "hypothesis_selection_result": bundle.selection_result.selection_status,
            "primary_hypothesis": None,
            "training_intervention_allowed": False,
            "assessment_fingerprint": payload_fingerprint,
        }
    )
    return _freeze(
        {**semantic, "summary_fingerprint": diagnostic_fingerprint(semantic)}
    )
