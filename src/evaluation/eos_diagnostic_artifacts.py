"""Strict, synthetic-safe artifact system for Candidate B EOS diagnostics.

This module implements the R1 envelope/writer and the R4 synthetic payload
extension.  It never imports torch, opens a checkpoint or tokenizer, or
performs generation.
"""

from __future__ import annotations

import errno
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from src.data.checksums import canonical_json_bytes, file_checksum, sha256_bytes

from .eos_hypothesis_policy import (
    ASSESSMENT_STATUSES,
    CONFIDENCE_STATUSES,
    COVERAGE_STATUSES,
    DIAGNOSTIC_ARTIFACT_TYPES,
    DIRECTIONS,
    EVIDENCE_STRENGTHS,
    FORBIDDEN_OBSERVATION_KEYS,
    HYPOTHESIS_DIAGNOSTICS,
    HYPOTHESIS_IDS,
    INTERVENTION_CATEGORIES,
    SELECTION_STATUSES,
    aggregate_evidence_status,
)

EOS_DIAGNOSTIC_SCHEMA_VERSION = 1
EOS_DIAGNOSTIC_WRITER_NAME = "dohalm-eos-diagnostic-artifact-writer"
EOS_DIAGNOSTIC_WRITER_VERSION = "1"
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

ARTIFACT_FILENAMES: Mapping[str, str] = MappingProxyType(
    {
        "diagnostic_run_manifest": "diagnostic-plan.json",
        "checkpoint_identity": "checkpoint-identity.json",
        "tokenizer_identity": "tokenizer-identity.json",
        "prompt_set_identity": "prompt-set-manifest.json",
        "generation_matrix": "generation-matrix.json",
        "eos_rank_trajectory": "eos-rank-trajectory.jsonl",
        "eos_probability_summary": "eos-probability-summary.json",
        "teacher_autoregressive_gap": "teacher-autoregressive-gap.json",
        "loop_analysis": "loop-analysis.json",
        "boundary_analysis": "boundary-analysis.json",
        "prompt_category_position_analysis": "prompt-category-position-analysis.json",
        "length_matrix": "length-matrix.json",
        "decoding_ablation": "decoding-ablation.json",
        "budget_proxy_analysis": "budget-proxy-analysis.json",
        "hypothesis_assessment": "hypothesis-assessment.json",
        "output_manifest": "diagnostic-summary.json",
        "artifact_inventory": "checksum-inventory.json",
        "completion_evidence": "completion-evidence.json",
    }
)
EXACT_ARTIFACT_FILENAMES = tuple(ARTIFACT_FILENAMES.values())

_CONTENT_TYPES = tuple(
    artifact_type
    for artifact_type in ARTIFACT_FILENAMES
    if artifact_type not in {"artifact_inventory", "completion_evidence"}
)
_PRE_COMPLETION_TYPES = tuple(
    artifact_type
    for artifact_type in ARTIFACT_FILENAMES
    if artifact_type != "completion_evidence"
)
_ANALYSIS_TYPES = frozenset(
    {
        "eos_rank_trajectory",
        "eos_probability_summary",
        "teacher_autoregressive_gap",
        "loop_analysis",
        "boundary_analysis",
        "prompt_category_position_analysis",
        "length_matrix",
        "decoding_ablation",
        "budget_proxy_analysis",
        "hypothesis_assessment",
    }
)
_R4_ANALYSIS_TYPES = _ANALYSIS_TYPES - {"hypothesis_assessment"}
_EVIDENCE_STATUSES = frozenset(
    {
        "complete",
        "complete_with_limitations",
        "insufficient_evidence",
        "incompatible_input",
        "blocked",
        "schema_only",
    }
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "diagnostic_run_id",
        "checkpoint_identity_fingerprint",
        "tokenizer_identity_fingerprint",
        "prompt_set_fingerprint",
        "generation_matrix_fingerprint",
        "source_commit",
        "created_at",
        "record_count",
        "payload",
        "artifact_fingerprint",
        "checksum",
    }
)
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_UTC_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_RUN_ID = re.compile(
    r"(?:SYNTHETIC-)?DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-(\d{8})-(\d{4})\Z"
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_LOGICAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")


class EOSDiagnosticArtifactError(RuntimeError):
    """Fail-closed error exposing only a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _raise(code: str = "EOS_DIAGNOSTIC_ARTIFACT_INVALID") -> None:
    raise EOSDiagnosticArtifactError(code)


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


@dataclass(frozen=True)
class DiagnosticArtifact:
    schema_version: int
    artifact_type: str
    diagnostic_run_id: str
    checkpoint_identity_fingerprint: str
    tokenizer_identity_fingerprint: str
    prompt_set_fingerprint: str
    generation_matrix_fingerprint: str
    source_commit: str
    created_at: str
    record_count: int
    payload: Mapping[str, Any]
    artifact_fingerprint: str
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze(_thaw(self.payload)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "diagnostic_run_id": self.diagnostic_run_id,
            "checkpoint_identity_fingerprint": self.checkpoint_identity_fingerprint,
            "tokenizer_identity_fingerprint": self.tokenizer_identity_fingerprint,
            "prompt_set_fingerprint": self.prompt_set_fingerprint,
            "generation_matrix_fingerprint": self.generation_matrix_fingerprint,
            "source_commit": self.source_commit,
            "created_at": self.created_at,
            "record_count": self.record_count,
            "payload": _thaw(self.payload),
            "artifact_fingerprint": self.artifact_fingerprint,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class ArtifactWriteResult:
    artifact_type: str
    filename: str
    artifact_fingerprint: str
    artifact_checksum: str
    file_checksum: str
    bytes_written: int


@dataclass(frozen=True)
class DiagnosticBundleResult:
    diagnostic_run_id: str
    status: str
    completion_scope: str
    artifact_count: int
    completion_checksum: str


def canonical_diagnostic_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON with one trailing LF and no non-finite values."""
    try:
        return canonical_json_bytes(_thaw(value))
    except (TypeError, ValueError, RecursionError):
        _raise()


def diagnostic_fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_diagnostic_json_bytes(value))


def _strict_object(value: object, fields: Sequence[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _raise()
    return value


def _strict_subset(
    value: object, *, allowed: frozenset[str], required: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if (
        type(value) is not dict
        or not required.issubset(value)
        or not set(value).issubset(allowed)
    ):
        _raise()
    return value


def _string(value: object, *, logical: bool = False, identifier: bool = False) -> str:
    if type(value) is not str or not value or value != value.strip():
        _raise()
    if "\x00" in value or "\n" in value or "\r" in value:
        _raise()
    pattern = _LOGICAL_ID if logical else _IDENTIFIER if identifier else None
    if pattern is not None and pattern.fullmatch(value) is None:
        _raise()
    if logical and (value.startswith("/") or "\\" in value or ".." in value.split("/")):
        _raise()
    return value


def _optional_string(value: object, *, identifier: bool = False) -> str | None:
    if value is None:
        return None
    return _string(value, identifier=identifier)


def _integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        _raise()
    return value


def _number(value: object) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        _raise()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        _raise()
    return value


def _fingerprint(value: object) -> str:
    candidate = _string(value)
    if _FINGERPRINT.fullmatch(candidate) is None:
        _raise()
    return candidate


def _git_sha(value: object) -> str:
    candidate = _string(value)
    if _GIT_SHA.fullmatch(candidate) is None:
        _raise()
    return candidate


def _timestamp(value: object) -> str:
    candidate = _string(value)
    if _UTC_Z.fullmatch(candidate) is None:
        _raise()
    try:
        datetime.fromisoformat(candidate[:-1] + "+00:00")
    except ValueError:
        _raise()
    return candidate


def _run_id(value: object) -> str:
    candidate = _string(value)
    match = _RUN_ID.fullmatch(candidate)
    if match is None:
        _raise()
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        _raise()
    return candidate


def _string_list(value: object, *, exact: tuple[str, ...] | None = None) -> list[str]:
    if type(value) is not list:
        _raise()
    result = [_string(item) for item in value]
    if len(result) != len(set(result)):
        _raise()
    if exact is not None and tuple(result) != exact:
        _raise()
    return result


def _distribution(value: object) -> dict[str, int]:
    if type(value) is not dict or not value:
        _raise()
    result: dict[str, int] = {}
    for key, count in value.items():
        result[_string(key, identifier=True)] = _integer(count)
    return result


def _validate_json_tree(value: object) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _number(value)
        return
    if type(value) is list:
        for item in value:
            _validate_json_tree(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _raise()
            _validate_json_tree(item)
        return
    _raise()


def _validate_metric_tree(value: object) -> None:
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        _number(value)
        return
    if type(value) is list:
        for item in value:
            _validate_metric_tree(item)
        return
    if type(value) is dict:
        if set(value) & FORBIDDEN_OBSERVATION_KEYS:
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
        for key, item in value.items():
            _string(key, identifier=True)
            _validate_metric_tree(item)
        return
    _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")


def _validate_hypothesis_signal(value: object) -> dict[str, Any]:
    signal = _strict_object(
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
    )
    _string(signal["signal_id"], identifier=True)
    if signal["hypothesis_id"] not in HYPOTHESIS_IDS:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    if signal["diagnostic_id"] not in HYPOTHESIS_DIAGNOSTICS[signal["hypothesis_id"]]:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    if (
        signal["direction"] not in DIRECTIONS
        or signal["evidence_strength"] not in EVIDENCE_STRENGTHS
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _fingerprint(signal["artifact_fingerprint"])
    _string(signal["metric_name"], identifier=True)
    _string(signal["comparison_scope"], identifier=True)
    _validate_metric_tree(signal["observation"])
    _string_list(signal["limitation_codes"])
    _boolean(signal["approval_required"])
    semantic = dict(signal)
    supplied = _fingerprint(semantic.pop("signal_fingerprint"))
    if diagnostic_fingerprint(semantic) != supplied:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
    return signal


def _validate_hypothesis_assessment(value: object) -> dict[str, Any]:
    assessment = _strict_object(
        value,
        (
            "hypothesis_id",
            "status",
            "supporting_signals",
            "contradictory_signals",
            "insufficient_signals",
            "evidence_coverage",
            "confidence",
            "unresolved_questions",
            "intervention_category",
            "allowed_next_actions",
            "prohibited_next_actions",
            "assessment_fingerprint",
        ),
    )
    hypothesis_id = assessment["hypothesis_id"]
    if hypothesis_id not in HYPOTHESIS_IDS:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    if (
        assessment["status"] not in ASSESSMENT_STATUSES
        or assessment["confidence"] not in CONFIDENCE_STATUSES
        or assessment["confidence"] == "high"
        or assessment["intervention_category"] != INTERVENTION_CATEGORIES[hypothesis_id]
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    for field in (
        "supporting_signals",
        "contradictory_signals",
        "insufficient_signals",
        "unresolved_questions",
        "allowed_next_actions",
        "prohibited_next_actions",
    ):
        _string_list(assessment[field])
    coverage = _strict_object(
        assessment["evidence_coverage"],
        (
            "coverage_status",
            "required_diagnostics_available",
            "diagnostic_statuses",
            "compatible_inputs",
            "paired_evidence_available",
            "comparison_group_available",
            "contradiction_review_coverage",
        ),
    )
    if coverage["coverage_status"] not in COVERAGE_STATUSES:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _string_list(
        coverage["required_diagnostics_available"],
        exact=HYPOTHESIS_DIAGNOSTICS[hypothesis_id],
    )
    statuses = _strict_object(
        coverage["diagnostic_statuses"], HYPOTHESIS_DIAGNOSTICS[hypothesis_id]
    )
    for status in statuses.values():
        if status not in _EVIDENCE_STATUSES:
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _boolean(coverage["compatible_inputs"])
    for field in ("paired_evidence_available", "comparison_group_available"):
        if coverage[field] is not None:
            _boolean(coverage[field])
    if coverage["contradiction_review_coverage"] not in {"reviewed", "missing"}:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    semantic = dict(assessment)
    supplied = _fingerprint(semantic.pop("assessment_fingerprint"))
    if diagnostic_fingerprint(semantic) != supplied:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
    return assessment


def _validate_selection_result(value: object) -> dict[str, Any]:
    selection = _strict_object(
        value,
        (
            "selection_status",
            "proposed_hypothesis",
            "conditions",
            "training_intervention_allowed",
            "actual_project_decision_changed",
            "selection_fingerprint",
        ),
    )
    if selection["selection_status"] not in SELECTION_STATUSES:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    proposed = selection["proposed_hypothesis"]
    if proposed is not None and proposed not in HYPOTHESIS_IDS:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    if selection["selection_status"] in {"selected", "conditionally_selected"}:
        if proposed is None:
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    elif proposed is not None:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _string_list(selection["conditions"])
    if (
        selection["training_intervention_allowed"] is not False
        or selection["actual_project_decision_changed"] is not False
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    semantic = dict(selection)
    supplied = _fingerprint(semantic.pop("selection_fingerprint"))
    if diagnostic_fingerprint(semantic) != supplied:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
    return selection


def _expected_assessment_semantics(
    assessment: Mapping[str, Any], signals: list[Mapping[str, Any]]
) -> tuple[str, str, list[str]]:
    hypothesis_id = assessment["hypothesis_id"]
    coverage = assessment["evidence_coverage"]
    supporting = [item for item in signals if item["direction"] == "supporting"]
    contradictory = [item for item in signals if item["direction"] == "contradictory"]
    insufficient = [item for item in signals if item["direction"] == "insufficient"]
    neutral = [item for item in signals if item["direction"] == "neutral"]
    reviewed = bool(contradictory or insufficient or neutral)
    unresolved: list[str] = []
    if coverage["coverage_status"] in {"incompatible", "insufficient", "partial"}:
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("REQUIRED_DIAGNOSTIC_EVIDENCE_INCOMPLETE")
    elif supporting and contradictory:
        status, confidence = "mixed_evidence", "low"
        unresolved.append("SUPPORT_AND_CONTRADICTION_BOTH_PRESENT")
    elif supporting:
        strengths = {item["evidence_strength"] for item in supporting}
        approval = any(item["approval_required"] for item in supporting)
        if (
            not reviewed
            or insufficient
            or hypothesis_id == "H6_TRAINING_BUDGET"
            or approval
            or strengths <= {"weak", "indeterminate"}
        ):
            status = "conditionally_supported"
            confidence = "low" if hypothesis_id == "H6_TRAINING_BUDGET" else "medium"
            unresolved.append(
                "CONTRADICTION_REVIEW_REQUIRED"
                if not reviewed
                else "APPROVAL_OR_ADDITIONAL_EVIDENCE_REQUIRED"
            )
        else:
            status, confidence = "supported", "medium"
    elif contradictory:
        status, confidence = "contradicted", "medium"
    elif neutral:
        status, confidence = "not_applicable", "indeterminate"
    else:
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("NO_HYPOTHESIS_EVIDENCE_SIGNAL")
    statuses = coverage["diagnostic_statuses"]
    if (
        hypothesis_id == "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH"
        and statuses["D2"] == "insufficient_evidence"
    ):
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("EXACT_PAIRING_EVIDENCE_REQUIRED")
    if (
        hypothesis_id in {"H3_BOUNDARY_FREQUENCY", "H4_PACKING_OBJECTIVE"}
        and coverage["comparison_group_available"] is not True
    ):
        status, confidence = "insufficient_evidence", "indeterminate"
        unresolved.append("PACKED_NON_PACKED_COMPARISON_REQUIRED")
    return status, confidence, sorted(set(unresolved))


def _expected_selection(
    overall_coverage: Mapping[str, Any], assessments: list[Mapping[str, Any]]
) -> tuple[str, str | None, list[str]]:
    conditions: list[str] = []
    proposed: str | None = None
    if overall_coverage["coverage_status"] != "complete":
        status = "diagnostic_incomplete"
        conditions.append("COMPLETE_COMPATIBLE_DIAGNOSTICS_REQUIRED")
    else:
        supported = [
            item["hypothesis_id"]
            for item in assessments
            if item["status"] == "supported"
        ]
        conditional = [
            item["hypothesis_id"]
            for item in assessments
            if item["status"] == "conditionally_supported"
        ]
        candidates = supported + conditional
        if {"H3_BOUNDARY_FREQUENCY", "H4_PACKING_OBJECTIVE"}.issubset(candidates):
            status = "multiple_hypotheses_unresolved"
            conditions.append("BOUNDARY_FREQUENCY_AND_PACKING_CAUSALITY_UNRESOLVED")
        elif {
            "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH",
            "H7_REPETITION_LOOP_COMPETITION",
        }.issubset(candidates):
            status = "multiple_hypotheses_unresolved"
            conditions.append("EXPOSURE_AND_LOOP_CAUSAL_DIRECTION_UNRESOLVED")
        elif len(candidates) > 1:
            status = "multiple_hypotheses_unresolved"
            conditions.append("MULTIPLE_SUPPORTED_HYPOTHESES_REQUIRE_CAUSAL_SEPARATION")
        elif len(supported) == 1:
            status, proposed = "selected", supported[0]
        elif len(conditional) == 1:
            status, proposed = "conditionally_selected", conditional[0]
            item = next(
                value for value in assessments if value["hypothesis_id"] == proposed
            )
            conditions.extend(item["unresolved_questions"])
        else:
            status = "no_hypothesis_selected"
            conditions.append("NO_ELIGIBLE_SINGLE_HYPOTHESIS")
    if proposed == "H5_DECODING_PARAMETER":
        conditions.append("DECODING_POLICY_REVIEW_ONLY")
    if proposed == "H6_TRAINING_BUDGET":
        conditions.extend(
            (
                "CAUSAL_CONFIDENCE_HIGH_FORBIDDEN",
                "SEPARATE_BUDGET_EXPERIMENT_APPROVAL_REQUIRED",
            )
        )
    return status, proposed, sorted(set(conditions))


def _validate_r5_hypothesis_payload(value: object, record_count: int) -> dict[str, Any]:
    payload = _strict_object(
        value,
        (
            "analysis_status",
            "record_schema_version",
            "policy_version",
            "diagnostic_run_id",
            "candidate_b_identity_fingerprint",
            "generation_matrix_fingerprint",
            "assessor_input_fingerprint",
            "diagnostic_artifact_fingerprints",
            "evidence_coverage",
            "evidence_signals",
            "hypothesis_assessments",
            "selection_result",
            "contradictory_evidence_summary",
            "unresolved_questions",
            "allowed_next_actions",
            "prohibited_next_actions",
            "actual_project_state",
            "assessment_fingerprint",
        ),
    )
    if (
        payload["analysis_status"] != "complete"
        or payload["record_schema_version"] != 5
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _string(payload["policy_version"], identifier=True)
    _run_id(payload["diagnostic_run_id"])
    for field in (
        "candidate_b_identity_fingerprint",
        "generation_matrix_fingerprint",
        "assessor_input_fingerprint",
    ):
        _fingerprint(payload[field])
    fingerprints = _strict_object(
        payload["diagnostic_artifact_fingerprints"],
        tuple(f"D{index}" for index in range(1, 9)),
    )
    for diagnostic_id, values in fingerprints.items():
        expected_count = 2 if diagnostic_id == "D1" else 1
        if (
            type(values) is not list
            or len(values) != expected_count
            or values != sorted(set(values))
        ):
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
        for item in values:
            _fingerprint(item)
    signals = payload["evidence_signals"]
    if type(signals) is not list:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    validated_signals = [_validate_hypothesis_signal(item) for item in signals]
    signal_ids = [item["signal_id"] for item in validated_signals]
    signal_fingerprints = [item["signal_fingerprint"] for item in validated_signals]
    if (
        len(signal_ids) != len(set(signal_ids))
        or len(signal_fingerprints) != len(set(signal_fingerprints))
        or signal_ids != sorted(signal_ids)
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    for signal in validated_signals:
        if signal["artifact_fingerprint"] not in fingerprints[signal["diagnostic_id"]]:
            _raise("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
    overall = _strict_object(
        payload["evidence_coverage"],
        (
            "coverage_status",
            "required_diagnostics_available",
            "diagnostic_statuses",
            "compatible_inputs",
            "paired_evidence_available",
            "comparison_group_available",
            "contradiction_review_coverage",
        ),
    )
    if overall["coverage_status"] not in COVERAGE_STATUSES:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _string_list(overall["required_diagnostics_available"])
    overall_statuses = _strict_object(
        overall["diagnostic_statuses"], tuple(DIAGNOSTIC_ARTIFACT_TYPES)
    )
    if any(status not in _EVIDENCE_STATUSES for status in overall_statuses.values()):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    _boolean(overall["compatible_inputs"])
    _boolean(overall["paired_evidence_available"])
    _boolean(overall["comparison_group_available"])
    if overall["contradiction_review_coverage"] not in {"complete", "partial", "none"}:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    assessments = payload["hypothesis_assessments"]
    if type(assessments) is not list or len(assessments) != len(HYPOTHESIS_IDS):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    validated_assessments = [
        _validate_hypothesis_assessment(item) for item in assessments
    ]
    if tuple(item["hypothesis_id"] for item in validated_assessments) != HYPOTHESIS_IDS:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    signals_by_id = {item["signal_id"]: item for item in validated_signals}
    for assessment in validated_assessments:
        hypothesis_id = assessment["hypothesis_id"]
        hypothesis_signals = [
            item for item in validated_signals if item["hypothesis_id"] == hypothesis_id
        ]
        for field, direction in (
            ("supporting_signals", "supporting"),
            ("contradictory_signals", "contradictory"),
            ("insufficient_signals", "insufficient"),
        ):
            expected = sorted(
                item["signal_id"]
                for item in hypothesis_signals
                if item["direction"] == direction
            )
            if assessment[field] != expected or any(
                signal_id not in signals_by_id for signal_id in assessment[field]
            ):
                _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
        expected_status, expected_confidence, expected_unresolved = (
            _expected_assessment_semantics(assessment, hypothesis_signals)
        )
        if (
            assessment["status"] != expected_status
            or assessment["confidence"] != expected_confidence
            or assessment["unresolved_questions"] != expected_unresolved
        ):
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
        coverage = assessment["evidence_coverage"]
        expected_statuses = {
            diagnostic_id: overall_statuses[diagnostic_id]
            for diagnostic_id in HYPOTHESIS_DIAGNOSTICS[hypothesis_id]
        }
        reviewed = any(
            item["direction"] in {"contradictory", "insufficient", "neutral"}
            for item in hypothesis_signals
        )
        incompatible = any(
            status == "incompatible_input" for status in expected_statuses.values()
        )
        unavailable = any(
            status in {"blocked", "schema_only"}
            for status in expected_statuses.values()
        )
        insufficient = any(
            status == "insufficient_evidence" for status in expected_statuses.values()
        )
        if incompatible:
            expected_coverage_status = "incompatible"
        elif unavailable:
            expected_coverage_status = "insufficient"
        elif insufficient:
            expected_coverage_status = "partial"
        elif reviewed and all(
            status == "complete" for status in expected_statuses.values()
        ):
            expected_coverage_status = "complete"
        else:
            expected_coverage_status = "substantial"
        if (
            coverage["diagnostic_statuses"] != expected_statuses
            or coverage["coverage_status"] != expected_coverage_status
            or coverage["compatible_inputs"] is not (not incompatible)
            or coverage["paired_evidence_available"]
            is not (
                overall_statuses["D2"] in {"complete", "complete_with_limitations"}
                if "D2" in HYPOTHESIS_DIAGNOSTICS[hypothesis_id]
                else None
            )
            or coverage["comparison_group_available"]
            is not (
                overall["comparison_group_available"]
                if "D4" in HYPOTHESIS_DIAGNOSTICS[hypothesis_id]
                else None
            )
            or coverage["contradiction_review_coverage"]
            != ("reviewed" if reviewed else "missing")
        ):
            _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    incompatible_ids = [
        key
        for key, status in overall_statuses.items()
        if status == "incompatible_input"
    ]
    unavailable_ids = [
        key
        for key, status in overall_statuses.items()
        if status in {"blocked", "schema_only"}
    ]
    insufficient_ids = [
        key
        for key, status in overall_statuses.items()
        if status == "insufficient_evidence"
    ]
    reviewed_count = sum(
        any(
            signal["hypothesis_id"] == hypothesis_id
            and signal["direction"] in {"contradictory", "insufficient", "neutral"}
            for signal in validated_signals
        )
        for hypothesis_id in HYPOTHESIS_IDS
    )
    expected_review = (
        "complete"
        if reviewed_count == len(HYPOTHESIS_IDS)
        else ("partial" if reviewed_count else "none")
    )
    if incompatible_ids:
        expected_overall_status = "incompatible"
    elif unavailable_ids or insufficient_ids:
        expected_overall_status = "insufficient"
    elif (
        not overall["paired_evidence_available"]
        or not overall["comparison_group_available"]
    ):
        expected_overall_status = "partial"
    elif expected_review == "complete" and all(
        status == "complete" for status in overall_statuses.values()
    ):
        expected_overall_status = "complete"
    else:
        expected_overall_status = "substantial"
    if (
        overall["coverage_status"] != expected_overall_status
        or overall["required_diagnostics_available"]
        != [key for key in sorted(overall_statuses) if key not in unavailable_ids]
        or overall["compatible_inputs"] is not (not incompatible_ids)
        or overall["contradiction_review_coverage"] != expected_review
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    selection = _validate_selection_result(payload["selection_result"])
    expected_status, expected_hypothesis, expected_conditions = _expected_selection(
        overall, validated_assessments
    )
    if (
        selection["selection_status"] != expected_status
        or selection["proposed_hypothesis"] != expected_hypothesis
        or selection["conditions"] != expected_conditions
    ):
        _raise("EOS_HYPOTHESIS_SELECTION_INVALID")
    contradictions = payload["contradictory_evidence_summary"]
    if type(contradictions) is not dict or not set(contradictions).issubset(
        HYPOTHESIS_IDS
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    for values in contradictions.values():
        _string_list(values)
    expected_contradictions = {
        item["hypothesis_id"]: item["contradictory_signals"]
        for item in validated_assessments
        if item["contradictory_signals"]
    }
    if contradictions != expected_contradictions:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    for field in (
        "unresolved_questions",
        "allowed_next_actions",
        "prohibited_next_actions",
    ):
        _string_list(payload[field])
    expected_unresolved = sorted(
        {
            question
            for item in validated_assessments
            for question in item["unresolved_questions"]
        }
        | set(selection["conditions"])
    )
    if (
        payload["unresolved_questions"] != expected_unresolved
        or payload["allowed_next_actions"]
        != ["review_evidence_only", "review_proposed_selection"]
        or payload["prohibited_next_actions"]
        != ["approve_candidate_c_config", "candidate_c_gpu", "candidate_c_training"]
    ):
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    state = _strict_object(
        payload["actual_project_state"],
        ("candidate_c_primary_hypothesis", "candidate_c_execution_allowed", "gate_c4"),
    )
    if state != {
        "candidate_c_primary_hypothesis": "not_selected",
        "candidate_c_execution_allowed": False,
        "gate_c4": "blocked",
    }:
        _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
    semantic = dict(payload)
    supplied = _fingerprint(semantic.pop("assessment_fingerprint"))
    if diagnostic_fingerprint(semantic) != supplied or record_count != len(
        HYPOTHESIS_IDS
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
    return payload


def _validate_payload(
    artifact_type: str, value: object, record_count: int
) -> dict[str, Any]:
    if artifact_type == "diagnostic_run_manifest":
        base_fields = frozenset(
            {
                "purpose",
                "execution_mode",
                "permissions",
                "exact_artifact_set",
                "predecessor_diagnostic_run_id",
            }
        )
        payload = _strict_subset(
            value,
            allowed=base_fields | {"preflight"},
            required=base_fields,
        )
        _string(payload["purpose"])
        if payload["execution_mode"] not in {
            "synthetic_schema_rehearsal",
            "synthetic_diagnostic_rehearsal",
            "diagnostic_execution",
        }:
            _raise()
        permissions = _strict_object(
            payload["permissions"],
            (
                "checkpoint_load",
                "tokenizer_load",
                "gpu",
                "generation",
                "checkpoint_write",
                "training",
            ),
        )
        for permission in permissions.values():
            _boolean(permission)
        if permissions["checkpoint_write"] or permissions["training"]:
            _raise()
        _string_list(payload["exact_artifact_set"], exact=EXACT_ARTIFACT_FILENAMES)
        predecessor = payload["predecessor_diagnostic_run_id"]
        if predecessor is not None:
            _run_id(predecessor)
        if "preflight" in payload:
            preflight = _strict_object(
                payload["preflight"],
                (
                    "schema_version",
                    "diagnostic_run_id",
                    "status",
                    "request_fingerprint",
                    "repository_state",
                    "backend_fingerprint",
                    "dependency_fingerprint",
                    "input_root_status",
                    "output_destination_status",
                    "gate_1_status",
                    "gate_2_status",
                    "blockers",
                    "approved_next_actions",
                    "prohibited_actions",
                    "diagnostic_execution_allowed",
                    "preflight_fingerprint",
                ),
            )
            if preflight["schema_version"] != 3:
                _raise()
            _run_id(preflight["diagnostic_run_id"])
            if preflight["status"] not in {
                "passed",
                "passed_with_conditions",
                "blocked",
                "incomplete",
                "incompatible",
                "failed",
            }:
                _raise()
            for field in (
                "request_fingerprint",
                "backend_fingerprint",
                "dependency_fingerprint",
                "preflight_fingerprint",
            ):
                _fingerprint(preflight[field])
            if preflight["gate_1_status"] not in {
                "passed",
                "blocked",
                "incomplete",
                "review",
            }:
                _raise()
            if preflight["gate_2_status"] not in {
                "passed",
                "blocked",
                "incomplete",
                "review",
            }:
                _raise()
            if preflight["diagnostic_execution_allowed"] is not False:
                _raise()
            _string_list(preflight["approved_next_actions"])
            prohibited = _string_list(preflight["prohibited_actions"])
            if not {
                "checkpoint_payload_read",
                "tokenizer_payload_read",
                "prompt_payload_read",
                "gpu",
                "generation",
            }.issubset(prohibited):
                _raise()
            for field in (
                "repository_state",
                "input_root_status",
                "output_destination_status",
                "blockers",
            ):
                _validate_json_tree(preflight[field])
            semantic_preflight = dict(preflight)
            semantic_preflight.pop("preflight_fingerprint")
            if preflight["preflight_fingerprint"] != diagnostic_fingerprint(
                semantic_preflight
            ):
                _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
        if record_count != 1:
            _raise()
    elif artifact_type == "checkpoint_identity":
        payload = _strict_object(
            value,
            (
                "checkpoint_id",
                "checkpoint_checksum",
                "checkpoint_manifest_fingerprint",
                "model_config_fingerprint",
                "training_run_id",
                "training_source_commit",
                "full_evaluation_id",
                "read_only",
            ),
        )
        _string(payload["checkpoint_id"], identifier=True)
        _fingerprint(payload["checkpoint_checksum"])
        _fingerprint(payload["checkpoint_manifest_fingerprint"])
        _fingerprint(payload["model_config_fingerprint"])
        _string(payload["training_run_id"], identifier=True)
        _git_sha(payload["training_source_commit"])
        _string(payload["full_evaluation_id"], identifier=True)
        if payload["read_only"] is not True or record_count != 1:
            _raise()
    elif artifact_type == "tokenizer_identity":
        payload = _strict_object(
            value,
            (
                "tokenizer_id",
                "bundle_checksum",
                "model_checksum",
                "vocab_checksum",
                "tokenizer_fingerprint",
                "vocab_size",
                "special_token_ids",
                "loaded",
            ),
        )
        _string(payload["tokenizer_id"], identifier=True)
        for field in (
            "bundle_checksum",
            "model_checksum",
            "vocab_checksum",
            "tokenizer_fingerprint",
        ):
            _fingerprint(payload[field])
        _integer(payload["vocab_size"], positive=True)
        special = _strict_object(
            payload["special_token_ids"], ("pad", "unk", "bos", "eos")
        )
        for token_id in special.values():
            _integer(token_id)
        if (
            len(set(special.values())) != len(special)
            or payload["loaded"] is not False
            or record_count != 1
        ):
            _raise()
    elif artifact_type == "prompt_set_identity":
        payload = _strict_object(
            value,
            (
                "prompt_set_id",
                "version",
                "checksum",
                "prompt_count",
                "category_distribution",
                "length_distribution",
                "normalization_policy",
                "pii_status",
                "leakage_status",
                "source_evidence",
                "prompt_text_stored",
            ),
        )
        _string(payload["prompt_set_id"], identifier=True)
        _string(payload["version"], identifier=True)
        _fingerprint(payload["checksum"])
        count = _integer(payload["prompt_count"], positive=True)
        categories = _distribution(payload["category_distribution"])
        lengths = _distribution(payload["length_distribution"])
        if sum(categories.values()) != count or sum(lengths.values()) != count:
            _raise()
        _string(payload["normalization_policy"], identifier=True)
        _string(payload["pii_status"], identifier=True)
        _string(payload["leakage_status"], identifier=True)
        _fingerprint(payload["source_evidence"])
        if payload["prompt_text_stored"] is not False or record_count != count:
            _raise()
    elif artifact_type == "generation_matrix":
        payload = _strict_object(
            value,
            (
                "matrix_id",
                "device",
                "dtype",
                "seed",
                "prompt_repetitions",
                "lengths",
                "profiles",
                "stop_policy",
                "privacy",
            ),
        )
        _string(payload["matrix_id"], identifier=True)
        _string(payload["device"], identifier=True)
        _string(payload["dtype"], identifier=True)
        _integer(payload["seed"])
        _integer(payload["prompt_repetitions"], positive=True)
        if type(payload["lengths"]) is not list or not payload["lengths"]:
            _raise()
        lengths = [_integer(item, positive=True) for item in payload["lengths"]]
        if len(lengths) != len(set(lengths)):
            _raise()
        if type(payload["profiles"]) is not list or not payload["profiles"]:
            _raise()
        names: list[str] = []
        allowed_parameters = frozenset(
            {
                "do_sample",
                "temperature",
                "top_p",
                "top_k",
                "repetition_penalty",
                "no_repeat_ngram",
                "forced_eos",
                "logit_bias",
                "heuristic_stop",
            }
        )
        for profile_value in payload["profiles"]:
            profile = _strict_object(profile_value, ("name", "mode", "parameters"))
            names.append(_string(profile["name"], identifier=True))
            if profile["mode"] not in {
                "pure_greedy",
                "diagnostic_only_sampling",
                "diagnostic_only_assisted",
            }:
                _raise()
            parameters = _strict_subset(
                profile["parameters"],
                allowed=allowed_parameters,
                required=frozenset({"do_sample"}),
            )
            for key, parameter in parameters.items():
                if key in {"do_sample", "forced_eos", "logit_bias", "heuristic_stop"}:
                    _boolean(parameter)
                elif parameter is not None:
                    _number(parameter)
        if len(names) != len(set(names)):
            _raise()
        _strict_object(
            payload["stop_policy"], ("eos", "maximum_new_tokens", "external_heuristic")
        )
        for item in payload["stop_policy"].values():
            _boolean(item)
        privacy = _strict_object(
            payload["privacy"], ("raw_text_storage", "raw_token_sequence_storage")
        )
        if (
            privacy["raw_text_storage"] is not False
            or privacy["raw_token_sequence_storage"] is not False
        ):
            _raise()
        if record_count != len(payload["profiles"]):
            _raise()
    elif (
        artifact_type == "hypothesis_assessment"
        and type(value) is dict
        and set(value)
        != {
            "analysis_status",
            "record_schema_version",
            "records",
            "summary",
            "limitations",
        }
    ):
        payload = _validate_r5_hypothesis_payload(value, record_count)
    elif artifact_type in _ANALYSIS_TYPES:
        payload = _strict_object(
            value,
            (
                "analysis_status",
                "record_schema_version",
                "records",
                "summary",
                "limitations",
            ),
        )
        if payload["analysis_status"] not in _EVIDENCE_STATUSES:
            _raise("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
        _integer(payload["record_schema_version"], positive=True)
        if type(payload["records"]) is not list or type(payload["summary"]) is not dict:
            _raise()
        _string_list(payload["limitations"])
        _validate_json_tree(payload["records"])
        _validate_json_tree(payload["summary"])
        if record_count != len(payload["records"]):
            _raise()
        if payload["analysis_status"] == "schema_only" and (
            payload["records"] or payload["summary"]
        ):
            _raise()
    elif artifact_type == "output_manifest":
        fields = frozenset(
            {
                "status",
                "output_root_logical_id",
                "writer_name",
                "writer_version",
                "exact_artifact_set",
                "optional_artifact_set",
            }
        )
        payload = _strict_subset(
            value,
            allowed=fields | {"diagnostic_summary"},
            required=fields,
        )
        if payload["status"] not in {"writing", "validating", "completed", "failed"}:
            _raise()
        _string(payload["output_root_logical_id"], logical=True)
        _string(payload["writer_name"], identifier=True)
        _string(payload["writer_version"], identifier=True)
        _string_list(payload["exact_artifact_set"], exact=EXACT_ARTIFACT_FILENAMES)
        _string_list(payload["optional_artifact_set"])
        if "diagnostic_summary" in payload:
            base_summary_fields = frozenset(
                {
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
            )
            r5_summary_fields = frozenset(
                {
                    "hypothesis_assessment_status",
                    "hypothesis_selection_result",
                    "primary_hypothesis",
                    "training_intervention_allowed",
                    "assessment_fingerprint",
                }
            )
            summary = _strict_subset(
                payload["diagnostic_summary"],
                allowed=base_summary_fields | r5_summary_fields,
                required=base_summary_fields,
            )
            if frozenset(summary) not in {
                base_summary_fields,
                base_summary_fields | r5_summary_fields,
            }:
                _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
            if summary["run_mode"] != "synthetic_only":
                _raise("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
            if (
                summary["actual_candidate_b_status_changed"] is not False
                or type(summary["hypothesis_selection_allowed"]) is not bool
            ):
                _raise("EOS_DIAG_ARTIFACT_PAYLOAD_INVALID")
            for field in (
                "completed_diagnostics",
                "limited_diagnostics",
                "insufficient_diagnostics",
                "incompatible_diagnostics",
                "unresolved_questions",
            ):
                _string_list(summary[field])
            if r5_summary_fields.issubset(summary):
                if (
                    summary["hypothesis_assessment_status"] != "completed_synthetic"
                    or summary["hypothesis_selection_result"]
                    not in {
                        "selected",
                        "conditionally_selected",
                        "no_hypothesis_selected",
                        "multiple_hypotheses_unresolved",
                        "diagnostic_incomplete",
                    }
                    or summary["primary_hypothesis"] is not None
                    or summary["training_intervention_allowed"] is not False
                ):
                    _raise("EOS_HYPOTHESIS_PAYLOAD_INVALID")
                _fingerprint(summary["assessment_fingerprint"])
            _validate_json_tree(summary)
            semantic_summary = dict(summary)
            supplied = _fingerprint(semantic_summary.pop("summary_fingerprint"))
            if diagnostic_fingerprint(semantic_summary) != supplied:
                _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
        if record_count != len(EXACT_ARTIFACT_FILENAMES):
            _raise()
    elif artifact_type == "artifact_inventory":
        payload = _strict_object(value, ("inventory_scope", "artifacts"))
        if (
            payload["inventory_scope"]
            != "content_artifacts_excluding_inventory_and_completion"
        ):
            _raise()
        if type(payload["artifacts"]) is not list or len(payload["artifacts"]) != len(
            _CONTENT_TYPES
        ):
            _raise()
        expected_names = [ARTIFACT_FILENAMES[item] for item in _CONTENT_TYPES]
        actual_names: list[str] = []
        for expected_type, entry_value in zip(
            _CONTENT_TYPES, payload["artifacts"], strict=True
        ):
            entry = _strict_object(
                entry_value,
                (
                    "artifact_type",
                    "filename",
                    "artifact_fingerprint",
                    "artifact_checksum",
                    "file_checksum",
                    "bytes",
                    "record_count",
                ),
            )
            if _string(entry["artifact_type"], identifier=True) != expected_type:
                _raise()
            actual_names.append(_string(entry["filename"]))
            _fingerprint(entry["artifact_fingerprint"])
            _fingerprint(entry["artifact_checksum"])
            _fingerprint(entry["file_checksum"])
            _integer(entry["bytes"], positive=True)
            _integer(entry["record_count"])
        if actual_names != expected_names or record_count != len(payload["artifacts"]):
            _raise()
    elif artifact_type == "completion_evidence":
        payload = _strict_object(
            value,
            (
                "status",
                "completion_scope",
                "expected_artifacts",
                "validated_artifacts",
                "inventory_checksum",
                "validation_completed_at",
            ),
        )
        if payload["status"] != "completed":
            _raise()
        if payload["completion_scope"] not in {
            "synthetic_schema_rehearsal",
            "synthetic_diagnostic_rehearsal",
            "diagnostic_execution",
        }:
            _raise()
        _string_list(payload["expected_artifacts"], exact=EXACT_ARTIFACT_FILENAMES)
        _string_list(
            payload["validated_artifacts"],
            exact=tuple(ARTIFACT_FILENAMES[item] for item in _PRE_COMPLETION_TYPES),
        )
        _fingerprint(payload["inventory_checksum"])
        _timestamp(payload["validation_completed_at"])
        if record_count != len(_PRE_COMPLETION_TYPES):
            _raise()
    else:
        _raise()
    return payload


def _artifact_fingerprint(value: Mapping[str, Any]) -> str:
    semantic = dict(value)
    semantic.pop("created_at", None)
    semantic.pop("artifact_fingerprint", None)
    semantic.pop("checksum", None)
    return diagnostic_fingerprint(semantic)


def _artifact_checksum(value: Mapping[str, Any]) -> str:
    checksummed = dict(value)
    checksummed["checksum"] = ""
    return diagnostic_fingerprint(checksummed)


def _validate_artifact_value(value: object) -> DiagnosticArtifact:
    root = _strict_object(value, tuple(_TOP_LEVEL_FIELDS))
    if root["schema_version"] != EOS_DIAGNOSTIC_SCHEMA_VERSION:
        _raise()
    artifact_type = _string(root["artifact_type"], identifier=True)
    if artifact_type not in ARTIFACT_FILENAMES:
        _raise()
    run_id = _run_id(root["diagnostic_run_id"])
    checkpoint = _fingerprint(root["checkpoint_identity_fingerprint"])
    tokenizer = _fingerprint(root["tokenizer_identity_fingerprint"])
    prompt_set = _fingerprint(root["prompt_set_fingerprint"])
    matrix = _fingerprint(root["generation_matrix_fingerprint"])
    source_commit = _git_sha(root["source_commit"])
    created_at = _timestamp(root["created_at"])
    record_count = _integer(root["record_count"])
    payload = _validate_payload(artifact_type, root["payload"], record_count)
    if (
        artifact_type == "hypothesis_assessment"
        and payload["analysis_status"] != "schema_only"
        and (
            payload["candidate_b_identity_fingerprint"] != checkpoint
            or payload["generation_matrix_fingerprint"] != matrix
        )
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH")
    if (
        artifact_type == "diagnostic_run_manifest"
        and "preflight" in payload
        and payload["preflight"]["diagnostic_run_id"] != run_id
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH")
    if (
        artifact_type == "output_manifest"
        and "diagnostic_summary" in payload
        and payload["diagnostic_summary"]["diagnostic_run_id"] != run_id
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH")
    if (
        artifact_type == "hypothesis_assessment"
        and payload["analysis_status"] != "schema_only"
        and payload["diagnostic_run_id"] != run_id
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH")
    if (
        artifact_type in _R4_ANALYSIS_TYPES
        and payload["analysis_status"] != "schema_only"
        and not run_id.startswith("SYNTHETIC-")
    ):
        _raise("EOS_DIAGNOSTIC_PRODUCTION_PAYLOAD_NOT_AUTHORIZED")
    if (
        artifact_type == "hypothesis_assessment"
        and payload["analysis_status"] != "schema_only"
        and not run_id.startswith("SYNTHETIC-")
    ):
        _raise("EOS_HYPOTHESIS_PRODUCTION_NOT_AUTHORIZED")
    if (
        artifact_type == "output_manifest"
        and "diagnostic_summary" in payload
        and not run_id.startswith("SYNTHETIC-")
    ):
        _raise("EOS_DIAGNOSTIC_PRODUCTION_PAYLOAD_NOT_AUTHORIZED")
    if (
        artifact_type == "diagnostic_run_manifest"
        and payload["execution_mode"] == "synthetic_diagnostic_rehearsal"
        and not run_id.startswith("SYNTHETIC-")
    ):
        _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
    artifact_fingerprint = _fingerprint(root["artifact_fingerprint"])
    checksum = _fingerprint(root["checksum"])
    if artifact_fingerprint != _artifact_fingerprint(
        root
    ) or checksum != _artifact_checksum(root):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH")
    return DiagnosticArtifact(
        schema_version=EOS_DIAGNOSTIC_SCHEMA_VERSION,
        artifact_type=artifact_type,
        diagnostic_run_id=run_id,
        checkpoint_identity_fingerprint=checkpoint,
        tokenizer_identity_fingerprint=tokenizer,
        prompt_set_fingerprint=prompt_set,
        generation_matrix_fingerprint=matrix,
        source_commit=source_commit,
        created_at=created_at,
        record_count=record_count,
        payload=payload,
        artifact_fingerprint=artifact_fingerprint,
        checksum=checksum,
    )


def _validate_r5_bundle_links(
    artifacts: Mapping[str, DiagnosticArtifact],
) -> None:
    hypothesis = artifacts["hypothesis_assessment"]
    if hypothesis.payload["analysis_status"] != "complete":
        return
    actual_fingerprints: dict[str, list[str]] = {}
    actual_statuses: dict[str, str] = {}
    for diagnostic_id, artifact_types in DIAGNOSTIC_ARTIFACT_TYPES.items():
        fingerprints: list[str] = []
        statuses: list[str] = []
        for artifact_type in artifact_types:
            artifact_payload = artifacts[artifact_type].payload
            summary = artifact_payload["summary"]
            if "result_fingerprint" not in summary:
                _raise("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
            fingerprints.append(_fingerprint(summary["result_fingerprint"]))
            statuses.append(artifact_payload["analysis_status"])
        actual_fingerprints[diagnostic_id] = sorted(fingerprints)
        actual_statuses[diagnostic_id] = aggregate_evidence_status(statuses)
    if (
        _thaw(hypothesis.payload["diagnostic_artifact_fingerprints"])
        != actual_fingerprints
    ):
        _raise("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
    if (
        _thaw(hypothesis.payload["evidence_coverage"])["diagnostic_statuses"]
        != actual_statuses
    ):
        _raise("EOS_HYPOTHESIS_ARTIFACT_MISMATCH")
    summary_value = artifacts["output_manifest"].payload.get("diagnostic_summary")
    summary = None if summary_value is None else _thaw(summary_value)
    selection = hypothesis.payload["selection_result"]
    if summary is None or (
        summary.get("hypothesis_assessment_status") != "completed_synthetic"
        or summary.get("hypothesis_selection_result") != selection["selection_status"]
        or summary.get("primary_hypothesis") is not None
        or summary.get("training_intervention_allowed")
        != selection["training_intervention_allowed"]
        or summary.get("assessment_fingerprint")
        != hypothesis.payload["assessment_fingerprint"]
    ):
        _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
    expected_summary_groups = {
        "completed_diagnostics": [
            key for key, status in actual_statuses.items() if status == "complete"
        ],
        "limited_diagnostics": [
            key
            for key, status in actual_statuses.items()
            if status == "complete_with_limitations"
        ],
        "insufficient_diagnostics": [
            key
            for key, status in actual_statuses.items()
            if status == "insufficient_evidence"
        ],
        "incompatible_diagnostics": [
            key
            for key, status in actual_statuses.items()
            if status == "incompatible_input"
        ],
    }
    if any(
        summary[field] != expected
        for field, expected in expected_summary_groups.items()
    ):
        _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")


def new_diagnostic_artifact(
    *,
    artifact_type: str,
    diagnostic_run_id: str,
    checkpoint_identity_fingerprint: str,
    tokenizer_identity_fingerprint: str,
    prompt_set_fingerprint: str,
    generation_matrix_fingerprint: str,
    source_commit: str,
    created_at: str,
    record_count: int,
    payload: Mapping[str, Any],
) -> DiagnosticArtifact:
    """Create and strictly validate one immutable artifact value."""
    value: dict[str, Any] = {
        "schema_version": EOS_DIAGNOSTIC_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "diagnostic_run_id": diagnostic_run_id,
        "checkpoint_identity_fingerprint": checkpoint_identity_fingerprint,
        "tokenizer_identity_fingerprint": tokenizer_identity_fingerprint,
        "prompt_set_fingerprint": prompt_set_fingerprint,
        "generation_matrix_fingerprint": generation_matrix_fingerprint,
        "source_commit": source_commit,
        "created_at": created_at,
        "record_count": record_count,
        "payload": _thaw(payload),
        "artifact_fingerprint": "",
        "checksum": "",
    }
    value["artifact_fingerprint"] = _artifact_fingerprint(value)
    value["checksum"] = _artifact_checksum(value)
    return _validate_artifact_value(value)


def serialize_diagnostic_artifact(artifact: DiagnosticArtifact) -> bytes:
    if not isinstance(artifact, DiagnosticArtifact):
        _raise()
    validated = _validate_artifact_value(artifact.as_dict())
    if validated.artifact_type == "eos_rank_trajectory":
        header = validated.as_dict()
        records = header["payload"]["records"]
        header["payload"]["records"] = []
        return b"".join(
            [canonical_diagnostic_json_bytes(header)]
            + [canonical_diagnostic_json_bytes(record) for record in records]
        )
    return canonical_diagnostic_json_bytes(validated.as_dict())


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise("EOS_DIAGNOSTIC_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _raise("EOS_DIAGNOSTIC_NONFINITE_NUMBER")


def load_diagnostic_artifact(
    path: Path, *, expected_artifact_type: str | None = None
) -> DiagnosticArtifact:
    """Load one canonical, non-symlink artifact with duplicate-key rejection."""
    if not isinstance(path, Path):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
    try:
        if path.is_symlink() or not path.is_file():
            _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
        size = path.stat().st_size
        if size <= 0 or size > MAX_ARTIFACT_BYTES:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_SIZE_INVALID")
        raw = path.read_bytes()
        decoded = raw.decode("utf-8", errors="strict")
        if path.name == ARTIFACT_FILENAMES["eos_rank_trajectory"]:
            if not raw.endswith(b"\n"):
                _raise("EOS_DIAG_JSONL_INVALID")
            lines = decoded.splitlines()
            if not lines:
                _raise("EOS_DIAG_JSONL_INVALID")
            values = [
                json.loads(
                    line,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_constant,
                )
                for line in lines
            ]
            value = values[0]
            if type(value) is not dict or type(value.get("payload")) is not dict:
                _raise("EOS_DIAG_JSONL_INVALID")
            if value.get("artifact_type") != "eos_rank_trajectory":
                _raise("EOS_DIAG_JSONL_INVALID")
            if value["payload"].get("records") != []:
                _raise("EOS_DIAG_JSONL_INVALID")
            if value.get("record_count") != len(values) - 1:
                _raise("EOS_DIAG_JSONL_INVALID")
            if any(type(record) is not dict for record in values[1:]):
                _raise("EOS_DIAG_JSONL_INVALID")
            value["payload"]["records"] = values[1:]
        else:
            value = json.loads(
                decoded,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
    except EOSDiagnosticArtifactError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ):
        _raise()
    artifact = _validate_artifact_value(value)
    if (
        expected_artifact_type is not None
        and artifact.artifact_type != expected_artifact_type
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_TYPE_MISMATCH")
    if path.name != ARTIFACT_FILENAMES[artifact.artifact_type]:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_FILENAME_MISMATCH")
    if raw != serialize_diagnostic_artifact(artifact):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_NONCANONICAL")
    return artifact


def _sync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_WRITE_INCOMPLETE")


def _publish_no_replace(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_ALREADY_EXISTS")
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_ALREADY_EXISTS")
        if exc.errno in {errno.EXDEV, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            _raise("EOS_DIAGNOSTIC_NO_REPLACE_UNSUPPORTED")
        _raise("EOS_DIAGNOSTIC_ARTIFACT_ATOMIC_WRITE_FAILED")


def _validate_destination(destination: Path, artifact: DiagnosticArtifact) -> Path:
    if not isinstance(destination, Path) or not isinstance(
        artifact, DiagnosticArtifact
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
    if destination.name != ARTIFACT_FILENAMES.get(artifact.artifact_type):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_FILENAME_MISMATCH")
    parent = destination.parent
    try:
        if parent.is_symlink() or not parent.is_dir() or destination.is_symlink():
            _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
        resolved_parent = parent.resolve(strict=True)
        if destination.resolve(strict=False).parent != resolved_parent:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
    except EOSDiagnosticArtifactError:
        raise
    except (OSError, RuntimeError, ValueError):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_PATH_INVALID")
    return parent


def write_diagnostic_artifact(
    *, destination: Path, artifact: DiagnosticArtifact
) -> ArtifactWriteResult:
    """Atomically publish canonical JSON once, then reload and verify it."""
    parent = _validate_destination(destination, artifact)
    if destination.exists():
        _raise("EOS_DIAGNOSTIC_ARTIFACT_ALREADY_EXISTS")
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists() or temporary.is_symlink():
        _raise("EOS_DIAGNOSTIC_ARTIFACT_TEMPORARY_COLLISION")
    payload = serialize_diagnostic_artifact(artifact)
    temporary_owned = False
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            temporary_owned = True
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                if handle.write(payload) != len(payload):
                    _raise("EOS_DIAGNOSTIC_ARTIFACT_ATOMIC_WRITE_FAILED")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_TEMPORARY_COLLISION")
        except EOSDiagnosticArtifactError:
            raise
        except OSError:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_ATOMIC_WRITE_FAILED")
        _publish_no_replace(temporary, destination)
        try:
            temporary.unlink()
            temporary_owned = False
        except OSError:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_WRITE_INCOMPLETE")
        _sync_parent_directory(parent)
        loaded = load_diagnostic_artifact(
            destination, expected_artifact_type=artifact.artifact_type
        )
        if loaded != artifact or destination.read_bytes() != payload:
            _raise("EOS_DIAGNOSTIC_ARTIFACT_WRITE_INCOMPLETE")
        return ArtifactWriteResult(
            artifact_type=artifact.artifact_type,
            filename=destination.name,
            artifact_fingerprint=artifact.artifact_fingerprint,
            artifact_checksum=artifact.checksum,
            file_checksum=file_checksum(destination),
            bytes_written=len(payload),
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_owned:
            try:
                temporary.unlink()
            except OSError:
                pass


def _load_artifact_types(
    directory: Path, artifact_types: Sequence[str]
) -> dict[str, DiagnosticArtifact]:
    try:
        if directory.is_symlink() or not directory.is_dir():
            _raise("EOS_DIAGNOSTIC_BUNDLE_PATH_INVALID")
    except OSError:
        _raise("EOS_DIAGNOSTIC_BUNDLE_PATH_INVALID")
    return {
        artifact_type: load_diagnostic_artifact(
            directory / ARTIFACT_FILENAMES[artifact_type],
            expected_artifact_type=artifact_type,
        )
        for artifact_type in artifact_types
    }


def _common_identity(artifacts: Mapping[str, DiagnosticArtifact]) -> dict[str, str]:
    if not artifacts:
        _raise("EOS_DIAGNOSTIC_ARTIFACT_SET_INCOMPLETE")
    fields = (
        "diagnostic_run_id",
        "checkpoint_identity_fingerprint",
        "tokenizer_identity_fingerprint",
        "prompt_set_fingerprint",
        "generation_matrix_fingerprint",
        "source_commit",
    )
    first = next(iter(artifacts.values()))
    common = {field: getattr(first, field) for field in fields}
    if any(
        getattr(artifact, field) != value
        for artifact in artifacts.values()
        for field, value in common.items()
    ):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH")
    return common


def new_artifact_inventory(directory: Path, *, created_at: str) -> DiagnosticArtifact:
    """Build the inventory after all sixteen content artifacts exist."""
    artifacts = _load_artifact_types(directory, _CONTENT_TYPES)
    common = _common_identity(artifacts)
    entries = []
    for artifact_type in _CONTENT_TYPES:
        artifact = artifacts[artifact_type]
        path = directory / ARTIFACT_FILENAMES[artifact_type]
        entries.append(
            {
                "artifact_type": artifact_type,
                "filename": path.name,
                "artifact_fingerprint": artifact.artifact_fingerprint,
                "artifact_checksum": artifact.checksum,
                "file_checksum": file_checksum(path),
                "bytes": path.stat().st_size,
                "record_count": artifact.record_count,
            }
        )
    return new_diagnostic_artifact(
        artifact_type="artifact_inventory",
        created_at=created_at,
        record_count=len(entries),
        payload={
            "inventory_scope": "content_artifacts_excluding_inventory_and_completion",
            "artifacts": entries,
        },
        **common,
    )


def _validate_inventory(
    directory: Path,
    inventory: DiagnosticArtifact,
    content: Mapping[str, DiagnosticArtifact],
) -> None:
    entries = inventory.payload["artifacts"]
    for artifact_type, entry in zip(_CONTENT_TYPES, entries, strict=True):
        artifact = content[artifact_type]
        path = directory / ARTIFACT_FILENAMES[artifact_type]
        expected = {
            "artifact_type": artifact_type,
            "filename": path.name,
            "artifact_fingerprint": artifact.artifact_fingerprint,
            "artifact_checksum": artifact.checksum,
            "file_checksum": file_checksum(path),
            "bytes": path.stat().st_size,
            "record_count": artifact.record_count,
        }
        if _thaw(entry) != expected:
            _raise("EOS_DIAGNOSTIC_INVENTORY_MISMATCH")


def new_completion_evidence(
    directory: Path, *, created_at: str, completion_scope: str
) -> DiagnosticArtifact:
    """Build completion evidence only after the other seventeen artifacts validate."""
    artifacts = _load_artifact_types(directory, _PRE_COMPLETION_TYPES)
    common = _common_identity(artifacts)
    manifest_mode = artifacts["diagnostic_run_manifest"].payload["execution_mode"]
    inventory = artifacts["artifact_inventory"]
    _validate_inventory(
        directory, inventory, {key: artifacts[key] for key in _CONTENT_TYPES}
    )
    if completion_scope == "diagnostic_execution":
        if (
            common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "diagnostic_execution"
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if any(
            artifacts[item].payload["analysis_status"] != "completed"
            for item in _ANALYSIS_TYPES
        ):
            _raise("EOS_DIAGNOSTIC_ANALYSIS_INCOMPLETE")
        if artifacts["output_manifest"].payload["status"] not in {
            "validating",
            "completed",
        }:
            _raise("EOS_DIAGNOSTIC_OUTPUT_MANIFEST_INCOMPLETE")
    elif completion_scope == "synthetic_schema_rehearsal":
        if (
            not common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "synthetic_schema_rehearsal"
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if any(
            artifacts[item].payload["analysis_status"] != "schema_only"
            for item in _ANALYSIS_TYPES
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
    elif completion_scope == "synthetic_diagnostic_rehearsal":
        hypothesis = artifacts["hypothesis_assessment"]
        summary = artifacts["output_manifest"].payload.get("diagnostic_summary")
        _validate_r5_bundle_links(artifacts)
        if (
            not common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "synthetic_diagnostic_rehearsal"
            or hypothesis.payload["analysis_status"] not in {"schema_only", "complete"}
            or any(
                artifacts[item].payload["analysis_status"] in {"schema_only", "blocked"}
                for item in _R4_ANALYSIS_TYPES
            )
            or summary is None
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if hypothesis.payload["analysis_status"] == "complete":
            if (
                "hypothesis_assessment_status" not in summary
                or summary["assessment_fingerprint"]
                != hypothesis.payload["assessment_fingerprint"]
            ):
                _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        elif "hypothesis_assessment_status" in summary:
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if artifacts["output_manifest"].payload["status"] not in {
            "validating",
            "completed",
        }:
            _raise("EOS_DIAGNOSTIC_OUTPUT_MANIFEST_INCOMPLETE")
    else:
        _raise()
    return new_diagnostic_artifact(
        artifact_type="completion_evidence",
        created_at=created_at,
        record_count=len(_PRE_COMPLETION_TYPES),
        payload={
            "status": "completed",
            "completion_scope": completion_scope,
            "expected_artifacts": list(EXACT_ARTIFACT_FILENAMES),
            "validated_artifacts": [
                ARTIFACT_FILENAMES[item] for item in _PRE_COMPLETION_TYPES
            ],
            "inventory_checksum": inventory.checksum,
            "validation_completed_at": created_at,
        },
        **common,
    )


def validate_completed_bundle(directory: Path) -> DiagnosticBundleResult:
    """Require exactly eighteen valid artifacts and verified completion evidence."""
    try:
        entries = tuple(directory.iterdir())
    except OSError:
        _raise("EOS_DIAGNOSTIC_BUNDLE_PATH_INVALID")
    if any(item.is_symlink() or not item.is_file() for item in entries):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_SET_INCOMPLETE")
    names = tuple(sorted(item.name for item in entries))
    if names != tuple(sorted(EXACT_ARTIFACT_FILENAMES)):
        _raise("EOS_DIAGNOSTIC_ARTIFACT_SET_INCOMPLETE")
    artifacts = _load_artifact_types(directory, tuple(ARTIFACT_FILENAMES))
    common = _common_identity(artifacts)
    inventory = artifacts["artifact_inventory"]
    completion = artifacts["completion_evidence"]
    _validate_inventory(
        directory, inventory, {key: artifacts[key] for key in _CONTENT_TYPES}
    )
    if completion.payload["inventory_checksum"] != inventory.checksum:
        _raise("EOS_DIAGNOSTIC_COMPLETION_MISMATCH")
    scope = completion.payload["completion_scope"]
    manifest_mode = artifacts["diagnostic_run_manifest"].payload["execution_mode"]
    if scope == "diagnostic_execution":
        if (
            common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "diagnostic_execution"
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if any(
            artifacts[item].payload["analysis_status"] != "completed"
            for item in _ANALYSIS_TYPES
        ):
            _raise("EOS_DIAGNOSTIC_ANALYSIS_INCOMPLETE")
    elif scope == "synthetic_schema_rehearsal":
        if (
            not common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "synthetic_schema_rehearsal"
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if any(
            artifacts[item].payload["analysis_status"] != "schema_only"
            for item in _ANALYSIS_TYPES
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
    elif scope == "synthetic_diagnostic_rehearsal":
        hypothesis = artifacts["hypothesis_assessment"]
        summary = artifacts["output_manifest"].payload.get("diagnostic_summary")
        _validate_r5_bundle_links(artifacts)
        if (
            not common["diagnostic_run_id"].startswith("SYNTHETIC-")
            or manifest_mode != "synthetic_diagnostic_rehearsal"
            or hypothesis.payload["analysis_status"] not in {"schema_only", "complete"}
            or any(
                artifacts[item].payload["analysis_status"] in {"schema_only", "blocked"}
                for item in _R4_ANALYSIS_TYPES
            )
            or summary is None
        ):
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        if hypothesis.payload["analysis_status"] == "complete":
            if (
                "hypothesis_assessment_status" not in summary
                or summary["assessment_fingerprint"]
                != hypothesis.payload["assessment_fingerprint"]
            ):
                _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
        elif "hypothesis_assessment_status" in summary:
            _raise("EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID")
    else:
        _raise()
    return DiagnosticBundleResult(
        diagnostic_run_id=common["diagnostic_run_id"],
        status="completed",
        completion_scope=scope,
        artifact_count=len(artifacts),
        completion_checksum=completion.checksum,
    )
