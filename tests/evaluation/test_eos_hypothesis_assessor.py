from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from src.evaluation.eos_diagnostic_artifacts import (
    diagnostic_fingerprint,
    new_diagnostic_artifact,
)
from src.evaluation.eos_diagnostic_backend import (
    AnalysisResult,
    build_diagnostic_summary,
)
from src.evaluation.eos_hypothesis_assessor import (
    HYPOTHESIS_DIAGNOSTICS,
    HYPOTHESIS_IDS,
    AssessorInput,
    EOSHypothesisAssessorError,
    EvidenceSignal,
    assess_hypotheses,
    attach_hypothesis_assessment_to_summary,
    build_r1_hypothesis_payload,
)

RUN_ID = "SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0005"
IDENTITY = "sha256:" + "a" * 64
MATRIX = "sha256:" + "b" * 64
POLICY = "candidate-c-hypothesis-selection-v1"

ARTIFACT_TYPES = {
    "D1": ("eos_rank_trajectory", "eos_probability_summary"),
    "D2": ("teacher_autoregressive_gap",),
    "D3": ("loop_analysis",),
    "D4": ("boundary_analysis",),
    "D5": ("prompt_category_position_analysis",),
    "D6": ("length_matrix",),
    "D7": ("decoding_ablation",),
    "D8": ("budget_proxy_analysis",),
}


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _result(
    diagnostic_id: str,
    artifact_type: str,
    status: str = "complete",
) -> AnalysisResult:
    summary: dict[str, object] = {"synthetic_metric_count": 1}
    if diagnostic_id == "D2":
        summary["paired_observation_count"] = 1
    elif diagnostic_id == "D4":
        summary["packed_comparison_available"] = True
    elif diagnostic_id == "D7":
        summary["pure_greedy_summary"] = {"trace_count": 1}
    semantic = {
        "diagnostic_id": diagnostic_id,
        "artifact_type": artifact_type,
        "evidence_status": status,
        "records": [],
        "summary": summary,
        "limitations": [],
    }
    return AnalysisResult(
        diagnostic_id=diagnostic_id,
        artifact_type=artifact_type,
        evidence_status=status,
        records=(),
        summary=summary,
        limitations=(),
        result_fingerprint=diagnostic_fingerprint(semantic),
    )


def _results(**statuses: str) -> tuple[AnalysisResult, ...]:
    return tuple(
        _result(diagnostic_id, artifact_type, statuses.get(diagnostic_id, "complete"))
        for diagnostic_id, artifact_types in ARTIFACT_TYPES.items()
        for artifact_type in artifact_types
    )


def _fingerprint_for(results: tuple[AnalysisResult, ...], diagnostic_id: str) -> str:
    return next(
        item.result_fingerprint
        for item in results
        if item.diagnostic_id == diagnostic_id
    )


def _signal(
    results: tuple[AnalysisResult, ...],
    hypothesis_id: str,
    direction: str,
    *,
    suffix: str = "01",
    strength: str = "strong",
    approval_required: bool = False,
    artifact_fingerprint: str | None = None,
) -> EvidenceSignal:
    diagnostic_id = HYPOTHESIS_DIAGNOSTICS[hypothesis_id][0]
    semantic: dict[str, object] = {
        "signal_id": f"SYNTHETIC-{hypothesis_id}-{direction}-{suffix}",
        "hypothesis_id": hypothesis_id,
        "direction": direction,
        "diagnostic_id": diagnostic_id,
        "artifact_fingerprint": artifact_fingerprint
        or _fingerprint_for(results, diagnostic_id),
        "metric_name": "synthetic_metric_delta",
        "comparison_scope": "synthetic_fixture",
        "observation": {"direction_code": 1, "sample_count": 4},
        "evidence_strength": strength,
        "limitation_codes": [],
        "approval_required": approval_required,
    }
    semantic["signal_fingerprint"] = diagnostic_fingerprint(semantic)
    return EvidenceSignal.from_mapping(semantic)


def _input(
    *,
    results: tuple[AnalysisResult, ...] | None = None,
    signals: tuple[EvidenceSignal, ...] = (),
) -> AssessorInput:
    values = results or _results()
    summary = build_diagnostic_summary(RUN_ID, values)
    return AssessorInput.create(
        diagnostic_run_id=RUN_ID,
        policy_version=POLICY,
        candidate_b_identity_fingerprint=IDENTITY,
        generation_matrix_fingerprint=MATRIX,
        results=values,
        diagnostic_summary=summary,
        signals=signals,
    )


def _complete_review_signals(
    results: tuple[AnalysisResult, ...], *supported: str
) -> tuple[EvidenceSignal, ...]:
    return tuple(
        _signal(results, hypothesis_id, "neutral", suffix="review")
        for hypothesis_id in HYPOTHESIS_IDS
    ) + tuple(
        _signal(results, hypothesis_id, "supporting") for hypothesis_id in supported
    )


def test_signal_is_strict_and_deterministic() -> None:
    results = _results()
    first = _signal(results, HYPOTHESIS_IDS[0], "supporting")
    second = _signal(results, HYPOTHESIS_IDS[0], "supporting")
    assert first == second
    assert first.signal_fingerprint == second.signal_fingerprint

    invalid = first.as_dict()
    invalid["direction"] = "favorable"
    invalid["signal_fingerprint"] = diagnostic_fingerprint(
        {key: value for key, value in invalid.items() if key != "signal_fingerprint"}
    )
    with pytest.raises(
        EOSHypothesisAssessorError, match="^EOS_HYPOTHESIS_INPUT_INVALID$"
    ):
        EvidenceSignal.from_mapping(invalid)

    invalid = first.as_dict()
    invalid["artifact_fingerprint"] = "invalid"
    with pytest.raises(EOSHypothesisAssessorError):
        EvidenceSignal.from_mapping(invalid)


def test_duplicate_signal_and_artifact_mismatch_fail_closed() -> None:
    results = _results()
    signal = _signal(results, HYPOTHESIS_IDS[0], "supporting")
    with pytest.raises(
        EOSHypothesisAssessorError, match="^EOS_HYPOTHESIS_INPUT_INVALID$"
    ):
        _input(results=results, signals=(signal, signal))
    mismatch = _signal(
        results,
        HYPOTHESIS_IDS[0],
        "supporting",
        artifact_fingerprint="sha256:" + "f" * 64,
    )
    with pytest.raises(
        EOSHypothesisAssessorError,
        match="^EOS_HYPOTHESIS_ARTIFACT_MISMATCH$",
    ):
        _input(results=results, signals=(mismatch,))


def test_direct_signal_construction_cannot_bypass_strict_validation() -> None:
    results = _results()
    signal = _signal(results, "H1_EOS_LOGIT_CALIBRATION", "supporting")
    with pytest.raises(EOSHypothesisAssessorError):
        replace(signal, diagnostic_id="D8")
    with pytest.raises(EOSHypothesisAssessorError):
        replace(signal, direction="favorable")
    with pytest.raises(EOSHypothesisAssessorError):
        replace(signal, observation={"prompt": "forbidden"})
    with pytest.raises(EOSHypothesisAssessorError):
        replace(signal, signal_fingerprint="sha256:" + "0" * 64)


def test_diagnostic_summary_status_drift_is_rejected() -> None:
    results = _results()
    summary = _plain(build_diagnostic_summary(RUN_ID, results))
    summary["completed_diagnostics"] = summary["completed_diagnostics"][:-1]
    semantic = dict(summary)
    semantic.pop("summary_fingerprint")
    summary["summary_fingerprint"] = diagnostic_fingerprint(semantic)
    with pytest.raises(
        EOSHypothesisAssessorError,
        match="^EOS_HYPOTHESIS_ARTIFACT_MISMATCH$",
    ):
        AssessorInput.create(
            diagnostic_run_id=RUN_ID,
            policy_version=POLICY,
            candidate_b_identity_fingerprint=IDENTITY,
            generation_matrix_fingerprint=MATRIX,
            results=results,
            diagnostic_summary=summary,
            signals=(),
        )


@pytest.mark.parametrize("hypothesis_id", HYPOTHESIS_IDS)
@pytest.mark.parametrize(
    ("directions", "expected"),
    [
        (("supporting",), "conditionally_supported"),
        (("contradictory",), "contradicted"),
        (("insufficient",), "insufficient_evidence"),
        (("supporting", "contradictory"), "mixed_evidence"),
    ],
)
def test_each_hypothesis_preserves_support_contradiction_and_insufficiency(
    hypothesis_id: str, directions: tuple[str, ...], expected: str
) -> None:
    results = _results()
    signals = tuple(
        _signal(results, hypothesis_id, direction, suffix=str(index))
        for index, direction in enumerate(directions)
    )
    bundle = assess_hypotheses(_input(results=results, signals=signals))
    assessment = next(
        item for item in bundle.assessments if item.hypothesis_id == hypothesis_id
    )
    assert assessment.status == expected
    if "contradictory" in directions:
        assert assessment.contradictory_signals


def test_coverage_complete_partial_insufficient_and_incompatible() -> None:
    results = _results()
    review_signals = tuple(
        _signal(results, hypothesis_id, "insufficient")
        for hypothesis_id in HYPOTHESIS_IDS
    )
    complete = assess_hypotheses(_input(results=results, signals=review_signals))
    assert complete.evidence_coverage["coverage_status"] == "complete"

    partial_results = _results(D2="insufficient_evidence")
    partial = assess_hypotheses(_input(results=partial_results))
    assert partial.evidence_coverage["coverage_status"] == "insufficient"
    assert partial.selection_result.selection_status == "diagnostic_incomplete"

    insufficient_results = _results(D4="blocked")
    insufficient = assess_hypotheses(_input(results=insufficient_results))
    assert insufficient.evidence_coverage["coverage_status"] == "insufficient"
    assert insufficient.selection_result.selection_status == "diagnostic_incomplete"

    incompatible_results = _results(D8="incompatible_input")
    incompatible = assess_hypotheses(_input(results=incompatible_results))
    assert incompatible.evidence_coverage["coverage_status"] == "incompatible"


@pytest.mark.parametrize(
    ("diagnostic_id", "status", "supported_hypothesis"),
    [
        ("D2", "insufficient_evidence", "H5_DECODING_PARAMETER"),
        ("D4", "insufficient_evidence", "H1_EOS_LOGIT_CALIBRATION"),
        ("D4", "blocked", "H7_REPETITION_LOOP_COMPETITION"),
        ("D8", "incompatible_input", "H1_EOS_LOGIT_CALIBRATION"),
        ("D3", "schema_only", "H1_EOS_LOGIT_CALIBRATION"),
    ],
)
def test_any_incomplete_diagnostic_blocks_selection(
    diagnostic_id: str, status: str, supported_hypothesis: str
) -> None:
    results = _results(**{diagnostic_id: status})
    bundle = assess_hypotheses(
        _input(
            results=results,
            signals=_complete_review_signals(results, supported_hypothesis),
        )
    )
    assert bundle.selection_result.selection_status == "diagnostic_incomplete"
    assert bundle.selection_result.proposed_hypothesis is None


@pytest.mark.parametrize(
    "hypothesis_id",
    (
        "H1_EOS_LOGIT_CALIBRATION",
        "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH",
        "H3_BOUNDARY_FREQUENCY",
        "H4_PACKING_OBJECTIVE",
        "H5_DECODING_PARAMETER",
        "H7_REPETITION_LOOP_COMPETITION",
    ),
)
def test_exact_one_supported_produces_synthetic_proposed_selection(
    hypothesis_id: str,
) -> None:
    results = _results()
    signals = _complete_review_signals(results, hypothesis_id)
    bundle = assess_hypotheses(_input(results=results, signals=signals))
    assert bundle.selection_result.selection_status == "selected"
    assert bundle.selection_result.proposed_hypothesis == hypothesis_id
    assert bundle.selection_result.actual_project_decision_changed is False
    assert bundle.selection_result.training_intervention_allowed is False


def test_h5_blocks_training_and_h6_is_only_conditional_proxy() -> None:
    results = _results()
    h5 = assess_hypotheses(
        _input(
            results=results,
            signals=_complete_review_signals(results, "H5_DECODING_PARAMETER"),
        )
    )
    assert "DECODING_POLICY_REVIEW_ONLY" in h5.selection_result.conditions
    assert h5.selection_result.training_intervention_allowed is False

    h6 = assess_hypotheses(
        _input(
            results=results,
            signals=_complete_review_signals(results, "H6_TRAINING_BUDGET"),
        )
    )
    assert h6.selection_result.selection_status == "conditionally_selected"
    assert h6.selection_result.proposed_hypothesis == "H6_TRAINING_BUDGET"
    assert "CAUSAL_CONFIDENCE_HIGH_FORBIDDEN" in h6.selection_result.conditions


@pytest.mark.parametrize(
    "pair",
    [
        ("H3_BOUNDARY_FREQUENCY", "H4_PACKING_OBJECTIVE"),
        (
            "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH",
            "H7_REPETITION_LOOP_COMPETITION",
        ),
    ],
)
def test_special_causal_pairs_remain_unresolved(pair: tuple[str, str]) -> None:
    results = _results()
    signals = _complete_review_signals(results, *pair)
    bundle = assess_hypotheses(_input(results=results, signals=signals))
    assert bundle.selection_result.selection_status == "multiple_hypotheses_unresolved"
    assert bundle.selection_result.proposed_hypothesis is None


def test_no_hypothesis_selected_and_output_is_deterministic() -> None:
    results = _results()
    signals = tuple(
        _signal(results, hypothesis_id, "neutral") for hypothesis_id in HYPOTHESIS_IDS
    )
    first = assess_hypotheses(_input(results=results, signals=signals))
    second = assess_hypotheses(_input(results=results, signals=signals))
    assert first.selection_result.selection_status == "no_hypothesis_selected"
    assert first.assessment_fingerprint == second.assessment_fingerprint


def test_signal_and_mixed_d1_result_order_do_not_change_output() -> None:
    base = list(_results())
    d1_insufficient = _result("D1", "eos_rank_trajectory", "insufficient_evidence")
    d1_blocked = _result("D1", "eos_probability_summary", "blocked")
    first_results = (d1_insufficient, d1_blocked, *base[2:])
    second_results = (d1_blocked, d1_insufficient, *base[2:])
    first = assess_hypotheses(_input(results=first_results))
    second = assess_hypotheses(_input(results=second_results))
    assert first.evidence_coverage == second.evidence_coverage
    assert first.selection_result == second.selection_result
    assert first.assessment_fingerprint == second.assessment_fingerprint

    complete_results = _results()
    signals = _complete_review_signals(complete_results, "H1_EOS_LOGIT_CALIBRATION")
    ordered = assess_hypotheses(_input(results=complete_results, signals=signals))
    reversed_order = assess_hypotheses(
        _input(results=complete_results, signals=tuple(reversed(signals)))
    )
    assert ordered.assessment_fingerprint == reversed_order.assessment_fingerprint


def test_r1_payload_and_summary_keep_project_state_unselected() -> None:
    results = _results()
    signals = _complete_review_signals(results, "H1_EOS_LOGIT_CALIBRATION")
    assessor_input = _input(results=results, signals=signals)
    bundle = assess_hypotheses(assessor_input)
    payload = build_r1_hypothesis_payload(bundle)
    summary = attach_hypothesis_assessment_to_summary(
        assessor_input.diagnostic_summary, bundle
    )
    assert payload["actual_project_state"] == {
        "candidate_c_primary_hypothesis": "not_selected",
        "candidate_c_execution_allowed": False,
        "gate_c4": "blocked",
    }
    assert (
        payload["selection_result"]["proposed_hypothesis"] == "H1_EOS_LOGIT_CALIBRATION"
    )
    assert summary["primary_hypothesis"] is None
    assert summary["training_intervention_allowed"] is False
    assert summary["assessment_fingerprint"] == payload["assessment_fingerprint"]
    artifact = new_diagnostic_artifact(
        artifact_type="hypothesis_assessment",
        diagnostic_run_id=RUN_ID,
        checkpoint_identity_fingerprint=IDENTITY,
        tokenizer_identity_fingerprint="sha256:" + "c" * 64,
        prompt_set_fingerprint="sha256:" + "d" * 64,
        generation_matrix_fingerprint=MATRIX,
        source_commit="1" * 40,
        created_at="2099-01-01T00:00:00Z",
        record_count=7,
        payload=payload,
    )
    assert (
        artifact.payload["assessment_fingerprint"] == summary["assessment_fingerprint"]
    )
    assert all(item.confidence != "high" for item in bundle.assessments)


def test_production_run_is_not_authorized() -> None:
    results = _results()
    summary = _plain(build_diagnostic_summary(RUN_ID, results))
    summary["diagnostic_run_id"] = "DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0005"
    semantic = dict(summary)
    semantic.pop("summary_fingerprint")
    summary["summary_fingerprint"] = diagnostic_fingerprint(semantic)
    with pytest.raises(
        EOSHypothesisAssessorError,
        match="^EOS_HYPOTHESIS_PRODUCTION_NOT_AUTHORIZED$",
    ):
        AssessorInput.create(
            diagnostic_run_id=summary["diagnostic_run_id"],
            policy_version=POLICY,
            candidate_b_identity_fingerprint=IDENTITY,
            generation_matrix_fingerprint=MATRIX,
            results=results,
            diagnostic_summary=summary,
            signals=(),
        )
