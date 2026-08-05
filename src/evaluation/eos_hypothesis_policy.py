"""Shared immutable policy constants for EOS-DIAG-R5."""

from types import MappingProxyType

HYPOTHESIS_IDS = (
    "H1_EOS_LOGIT_CALIBRATION",
    "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH",
    "H3_BOUNDARY_FREQUENCY",
    "H4_PACKING_OBJECTIVE",
    "H5_DECODING_PARAMETER",
    "H6_TRAINING_BUDGET",
    "H7_REPETITION_LOOP_COMPETITION",
)
HYPOTHESIS_DIAGNOSTICS = MappingProxyType(
    {
        "H1_EOS_LOGIT_CALIBRATION": ("D1", "D2", "D5", "D6"),
        "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH": ("D1", "D2", "D3"),
        "H3_BOUNDARY_FREQUENCY": ("D4", "D5"),
        "H4_PACKING_OBJECTIVE": ("D2", "D4"),
        "H5_DECODING_PARAMETER": ("D3", "D6", "D7"),
        "H6_TRAINING_BUDGET": ("D8",),
        "H7_REPETITION_LOOP_COMPETITION": ("D1", "D3", "D7"),
    }
)
DIAGNOSTIC_ARTIFACT_TYPES = MappingProxyType(
    {
        "D1": ("eos_rank_trajectory", "eos_probability_summary"),
        "D2": ("teacher_autoregressive_gap",),
        "D3": ("loop_analysis",),
        "D4": ("boundary_analysis",),
        "D5": ("prompt_category_position_analysis",),
        "D6": ("length_matrix",),
        "D7": ("decoding_ablation",),
        "D8": ("budget_proxy_analysis",),
    }
)
INTERVENTION_CATEGORIES = MappingProxyType(
    {
        "H1_EOS_LOGIT_CALIBRATION": "eos_loss_calibration",
        "H2_AUTOREGRESSIVE_EXPOSURE_MISMATCH": "autoregressive_robustness",
        "H3_BOUNDARY_FREQUENCY": "boundary_sampling",
        "H4_PACKING_OBJECTIVE": "packing_policy",
        "H5_DECODING_PARAMETER": "decoding_policy",
        "H6_TRAINING_BUDGET": "training_budget",
        "H7_REPETITION_LOOP_COMPETITION": "repetition_regularization",
    }
)
DIRECTIONS = frozenset({"supporting", "contradictory", "insufficient", "neutral"})
EVIDENCE_STRENGTHS = frozenset({"weak", "moderate", "strong", "indeterminate"})
ASSESSMENT_STATUSES = frozenset(
    {
        "supported",
        "conditionally_supported",
        "contradicted",
        "insufficient_evidence",
        "mixed_evidence",
        "not_applicable",
    }
)
CONFIDENCE_STATUSES = frozenset({"low", "medium", "high", "indeterminate"})
COVERAGE_STATUSES = frozenset(
    {"complete", "substantial", "partial", "insufficient", "incompatible"}
)
SELECTION_STATUSES = frozenset(
    {
        "selected",
        "conditionally_selected",
        "no_hypothesis_selected",
        "multiple_hypotheses_unresolved",
        "diagnostic_incomplete",
    }
)
FORBIDDEN_OBSERVATION_KEYS = frozenset(
    {
        "prompt",
        "prompt_text",
        "generated_text",
        "response",
        "raw_text",
        "text",
        "tokens",
        "token_sequence",
        "raw_token_sequence",
        "path",
        "absolute_path",
        "checkpoint_path",
        "tokenizer_path",
        "secret",
        "conclusion",
    }
)


def aggregate_evidence_status(items: tuple[str, ...] | list[str]) -> str:
    """Return a deterministic, fail-closed aggregate for one diagnostic ID."""

    values = frozenset(items)
    for status in (
        "incompatible_input",
        "blocked",
        "schema_only",
        "insufficient_evidence",
        "complete_with_limitations",
        "complete",
    ):
        if status in values:
            return status
    raise ValueError("EOS_HYPOTHESIS_INPUT_INVALID")
