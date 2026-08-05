from __future__ import annotations

from copy import deepcopy

import pytest

from src.evaluation.eos_diagnostic_artifacts import diagnostic_fingerprint
from src.evaluation.eos_diagnostic_backend import (
    BoundaryObservation,
    BudgetEvidence,
    EOSDiagnosticBackendError,
    LoopConfig,
    PromptMetadata,
    SyntheticGenerationTrace,
    TeacherForcedObservation,
    analyze_d1,
    analyze_d2,
    analyze_d3,
    analyze_d4,
    analyze_d5,
    analyze_d6,
    analyze_d7,
    analyze_d8,
    build_diagnostic_summary,
    build_r1_analysis_payloads,
)

RUN_ID = "SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0004"
HASH_A = "sha256:" + "a" * 64


def _signed(value: dict[str, object], field: str) -> dict[str, object]:
    result = deepcopy(value)
    result[field] = diagnostic_fingerprint(result)
    return result


def _step(
    index: int,
    token: int,
    *,
    eos: bool = False,
    rank: int | None = None,
    repeated: bool = False,
) -> dict[str, object]:
    return {
        "step_index": index,
        "selected_token_id": token,
        "eos_logit": float(index) - 2.0,
        "eos_probability": min(0.95, 0.1 + index * 0.2),
        "eos_rank": rank if rank is not None else max(1, 5 - index),
        "top_competitor_token_ids": [90 + index],
        "top_competitor_logits": [2.0 - index],
        "selected_token_probability": 0.6,
        "unique_token_ratio_so_far": 1.0 if index < 2 else 0.75,
        "repeated_ngram_hashes": [HASH_A] if repeated else [],
        "boundary_distance": index,
        "is_eos_selected": eos,
    }


def _trace_mapping(
    *,
    prompt: str = "synthetic-prompt-01",
    category: str = "synthetic-category",
    profile: str = "greedy",
    role: str = "pure_greedy",
    length: int = 16,
    termination: str = "eos",
    steps: list[dict[str, object]] | None = None,
    prefix_derived: bool = False,
    source_length: int | None = None,
) -> dict[str, object]:
    if steps is None:
        steps = [
            _step(0, 10, rank=8),
            _step(1, 11, rank=4),
            _step(2, 3, eos=True, rank=1),
        ]
    semantic: dict[str, object] = {
        "schema_version": 4,
        "diagnostic_run_id": RUN_ID,
        "opaque_prompt_id": prompt,
        "prompt_category": category,
        "prompt_length_bucket": "short",
        "context_class": "synthetic",
        "generation_profile_id": profile,
        "max_new_tokens": length,
        "decoding_role": role,
        "seed": 17,
        "eos_token_id": 3,
        "generated_steps": steps,
        "termination_type": termination,
        "prefix_derived": prefix_derived,
        "source_max_new_tokens": source_length or length,
    }
    return _signed(semantic, "trace_fingerprint")


def _trace(**kwargs: object) -> SyntheticGenerationTrace:
    return SyntheticGenerationTrace.from_mapping(_trace_mapping(**kwargs))


def _teacher(
    prompt: str = "synthetic-prompt-01",
    position: int = 1,
    *,
    packed: bool = True,
    distance: int | None = 1,
) -> TeacherForcedObservation:
    return TeacherForcedObservation.from_mapping(
        _signed(
            {
                "opaque_prompt_id": prompt,
                "category": "synthetic-category",
                "target_position": position,
                "pairing_key": f"{prompt}:{position}",
                "eos_target": True,
                "eos_logit": 1.0,
                "eos_probability": 0.7,
                "eos_rank": 2,
                "top_competitor_token_ids": [10, 11],
                "sequence_boundary_distance": distance,
                "packed_sequence": packed,
            },
            "observation_fingerprint",
        )
    )


def _boundary(packed: bool) -> BoundaryObservation:
    return BoundaryObservation.from_mapping(
        _signed(
            {
                "opaque_sample_id": f"synthetic-sample-{int(packed)}",
                "split": "synthetic",
                "packed_sequence": packed,
                "boundary_index": 2,
                "eos_target_position": 3,
                "boundary_distance": 1,
                "source_sequence_length": 8,
                "target_sequence_length": 8,
                "category": "synthetic-category",
            },
            "observation_fingerprint",
        )
    )


def _metadata() -> PromptMetadata:
    return PromptMetadata.from_mapping(
        _signed(
            {
                "opaque_prompt_id": "synthetic-prompt-01",
                "category": "synthetic-category",
                "prompt_length_bucket": "short",
                "context_class": "synthetic",
                "expected_output_position_bucket": "early",
            },
            "prompt_identity_fingerprint",
        )
    )


def _loop_config() -> LoopConfig:
    return LoopConfig.from_mapping(
        _signed(
            {
                "minimum_repeat_count": 3,
                "minimum_loop_length": 1,
                "persistence_steps": 1,
                "ngram_sizes": [2, 3],
            },
            "config_fingerprint",
        )
    )


def _budget(candidate: str, budget: int, *, identity: str = HASH_A) -> BudgetEvidence:
    return BudgetEvidence.from_mapping(
        _signed(
            {
                "candidate_id": candidate,
                "training_token_budget": budget,
                "optimizer_steps": budget // 100,
                "final_loss": 5.0,
                "perplexity": 150.0,
                "teacher_forced_eos_rank": 4.0,
                "teacher_forced_eos_probability": 0.5,
                "pure_greedy_eos_rate": 0.0,
                "max_length_rate": 1.0,
                "repetition_rate": 0.5,
                "model_config_fingerprint": identity,
                "tokenizer_fingerprint": HASH_A,
                "dataset_fingerprint": HASH_A,
                "evaluation_fingerprint": HASH_A,
            },
            "evidence_fingerprint",
        )
    )


def _matrix_traces() -> tuple[SyntheticGenerationTrace, ...]:
    roles = (
        ("greedy", "pure_greedy"),
        ("temperature-0.7", "sampling"),
        ("repetition-1.05", "repetition_penalty"),
        ("no-repeat-bigram", "no_repeat_ngram"),
    )
    return tuple(
        _trace(profile=profile, role=role, length=length)
        for length in (16, 32, 64, 128)
        for profile, role in roles
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["generated_steps"][1].update(step_index=3),
        lambda value: value["generated_steps"][0].update(eos_probability=1.1),
        lambda value: value["generated_steps"][0].update(eos_rank=0),
        lambda value: value["generated_steps"][0].update(eos_logit=float("nan")),
        lambda value: value.update(prompt_text="forbidden"),
    ],
)
def test_trace_rejects_gaps_invalid_numbers_and_raw_text(mutation) -> None:
    value = _trace_mapping()
    mutation(value)
    with pytest.raises(EOSDiagnosticBackendError, match="^EOS_DIAG_TRACE_INVALID$"):
        SyntheticGenerationTrace.from_mapping(value)


def test_trace_and_d1_are_deterministic_and_report_top_k_trajectory() -> None:
    trace = _trace()
    trajectory, probability = analyze_d1((trace,))
    repeated, probability_repeated = analyze_d1((trace,))
    assert trajectory.result_fingerprint == repeated.result_fingerprint
    assert probability.result_fingerprint == probability_repeated.result_fingerprint
    assert trajectory.summary["first_top_k_entry_step_mean"] == 0.0
    assert trajectory.records[-1]["is_eos_selected"] is True
    assert probability.summary["maximum_eos_probability"] == 0.5


def test_d2_exact_pairing_gap_and_insufficient_evidence() -> None:
    result = analyze_d2((_teacher(),), (_trace(),))
    assert result.evidence_status == "complete"
    assert result.summary["paired_observation_count"] == 1
    assert result.records[0]["eos_rank_gap"] == 2
    missing = analyze_d2((_teacher(position=9),), (_trace(),))
    assert missing.evidence_status == "insufficient_evidence"
    duplicate = (_teacher(), _teacher())
    with pytest.raises(EOSDiagnosticBackendError, match="^EOS_DIAG_PAIRING_INVALID$"):
        analyze_d2(duplicate, (_trace(),))

    mismatched = _signed(
        {
            "opaque_prompt_id": "synthetic-prompt-01",
            "category": "synthetic-category",
            "target_position": 1,
            "pairing_key": "synthetic-prompt-01:2",
            "eos_target": True,
            "eos_logit": 1.0,
            "eos_probability": 0.7,
            "eos_rank": 2,
            "top_competitor_token_ids": [10],
            "sequence_boundary_distance": 1,
            "packed_sequence": True,
        },
        "observation_fingerprint",
    )
    with pytest.raises(EOSDiagnosticBackendError, match="^EOS_DIAG_PAIRING_INVALID$"):
        TeacherForcedObservation.from_mapping(mismatched)


def test_d3_detects_repeated_token_and_no_loop() -> None:
    loop_steps = [_step(index, 7, repeated=index >= 2) for index in range(6)]
    loop = _trace(termination="max_length", length=6, steps=loop_steps)
    result = analyze_d3((loop, _trace(prompt="synthetic-prompt-02")), _loop_config())
    assert result.summary["loop_detected_count"] == 1
    detected = next(item for item in result.records if item["loop_detected"])
    assert detected["onset_step"] == 0
    assert detected["loop_type"] in {"repeated_token_run", "periodic_pattern"}
    assert detected["repeated_ngram_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("tokens", "ngram_sizes", "expected_type"),
    [
        ([1, 2, 1, 2, 1, 2], [2], "repeated_2gram"),
        ([4, 5, 6, 4, 5, 6, 4], [3], "repeated_3gram"),
        ([1, 2, 1, 2, 1, 2], [], "periodic_pattern"),
    ],
)
def test_d3_detects_bigram_trigram_and_periodic_patterns(
    tokens: list[int], ngram_sizes: list[int], expected_type: str
) -> None:
    config = LoopConfig.from_mapping(
        _signed(
            {
                "minimum_repeat_count": 3,
                "minimum_loop_length": 2,
                "persistence_steps": 1,
                "ngram_sizes": ngram_sizes,
            },
            "config_fingerprint",
        )
    )
    trace = _trace(
        termination="max_length",
        length=len(tokens),
        steps=[_step(index, token) for index, token in enumerate(tokens)],
    )
    result = analyze_d3((trace,), config)
    assert result.records[0]["loop_type"] == expected_type


def test_d4_boundary_groups_and_missing_metadata_are_fail_closed() -> None:
    complete = analyze_d4(
        (_teacher(packed=True), _teacher(prompt="synthetic-prompt-02", packed=False)),
        (_boundary(True), _boundary(False)),
    )
    assert complete.evidence_status == "complete"
    assert complete.summary["packed_comparison_available"] is True
    missing = analyze_d4((_teacher(distance=None),), ())
    assert missing.evidence_status == "insufficient_evidence"
    limited = analyze_d4((_teacher(packed=True),), (_boundary(True),))
    assert limited.evidence_status == "complete_with_limitations"


def test_d5_category_length_position_and_incomplete_aggregates() -> None:
    incomplete_steps = [_step(0, 7, repeated=True)]
    result = analyze_d5(
        (_metadata(),),
        (
            _trace(
                termination="incomplete",
                steps=incomplete_steps,
            ),
        ),
        (_teacher(),),
    )
    dimensions = {item["dimension"] for item in result.records}
    assert dimensions == {"category", "output_position_bucket", "prompt_length_bucket"}
    assert result.summary["aggregate_count"] == 3
    assert all(item["incomplete_count"] == 1 for item in result.records)
    assert all(item["repetition_count"] == 1 for item in result.records)


def test_d6_length_matrix_separates_pure_and_diagnostic() -> None:
    result = analyze_d6(
        _matrix_traces(), expected_prompt_count=1, expected_profile_count=4
    )
    assert [item["max_new_tokens"] for item in result.records] == [16, 32, 64, 128]
    assert all(
        item["official_pure_greedy"]["trace_count"] == 1 for item in result.records
    )
    assert all(item["diagnostic_only"]["trace_count"] == 3 for item in result.records)
    with pytest.raises(
        EOSDiagnosticBackendError, match="^EOS_DIAG_LENGTH_MATRIX_INVALID$"
    ):
        analyze_d6((_trace(),))

    prefix_values = list(_matrix_traces())
    prefix_values[0] = _trace(
        profile="greedy",
        role="pure_greedy",
        length=16,
        prefix_derived=True,
        source_length=128,
    )
    prefix_result = analyze_d6(
        prefix_values, expected_prompt_count=1, expected_profile_count=4
    )
    assert prefix_result.records[0]["prefix_derived_count"] == 1
    assert prefix_result.records[0]["eos_termination_count"] == 4


def test_d7_keeps_assisted_results_out_of_pure_metric() -> None:
    result = analyze_d7(_matrix_traces())
    assert result.evidence_status == "complete_with_limitations"
    assert result.summary["base_pass_decision_allowed"] is False
    pure = next(
        item for item in result.records if item["decoding_role"] == "pure_greedy"
    )
    sampling = next(
        item for item in result.records if item["decoding_role"] == "sampling"
    )
    assert pure["metric_role"] == "official_pure_model"
    assert sampling["metric_role"] == "diagnostic_only"


def test_d8_compatible_incompatible_and_incomplete_budget_proxy() -> None:
    result = analyze_d8(
        (_budget("candidate-a", 10_000), _budget("candidate-b", 25_000))
    )
    assert result.evidence_status == "complete_with_limitations"
    assert result.summary["causal_budget_conclusion_allowed"] is False
    incompatible = analyze_d8(
        (
            _budget("candidate-a", 10_000),
            _budget("candidate-b", 25_000, identity="sha256:" + "b" * 64),
        )
    )
    assert incompatible.evidence_status == "incompatible_input"
    assert (
        analyze_d8((_budget("candidate-a", 10_000),)).evidence_status
        == "insufficient_evidence"
    )


def test_summary_and_r1_payloads_reflect_coverage_without_selecting_hypothesis() -> (
    None
):
    traces = _matrix_traces()
    d1 = analyze_d1(traces)
    results = (
        *d1,
        analyze_d2((_teacher(),), (_trace(),)),
        analyze_d3(traces, _loop_config()),
        analyze_d4(
            (
                _teacher(packed=True),
                _teacher(prompt="synthetic-prompt-02", packed=False),
            ),
            (_boundary(True), _boundary(False)),
        ),
        analyze_d5((_metadata(),), (_trace(),), (_teacher(),)),
        analyze_d6(traces, expected_prompt_count=1, expected_profile_count=4),
        analyze_d7(traces),
        analyze_d8((_budget("candidate-a", 10_000), _budget("candidate-b", 25_000))),
    )
    summary = build_diagnostic_summary(RUN_ID, results)
    assert summary["hypothesis_selection_allowed"] is True
    assert summary["actual_candidate_b_status_changed"] is False
    payloads = build_r1_analysis_payloads(results, summary)
    assert len(payloads) == 10
    assert payloads["eos_rank_trajectory"]["records"]
    assert payloads["diagnostic_summary"]["run_mode"] == "synthetic_only"

    insufficient_results = list(results)
    insufficient_results[2] = analyze_d2((_teacher(position=9),), (_trace(),))
    blocked = build_diagnostic_summary(RUN_ID, insufficient_results)
    assert blocked["hypothesis_selection_allowed"] is False
    assert blocked["insufficient_diagnostics"] == ("D2",)
