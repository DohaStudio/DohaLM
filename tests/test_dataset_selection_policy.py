from dataclasses import FrozenInstanceError

import pytest

from src.data.dataset_selection_policy import (
    AIHUB_71748,
    BLOCKED,
    COMPLETED,
    CONDITIONALLY_SELECTED,
    CURRENT_SELECTION_CONDITIONS,
    DEFERRED,
    INVALID_APPROVAL_REQUEST,
    NOT_STARTED,
    REJECTED,
    REVIEW_REQUIRED,
    SFT,
    DatasetSelectionDecision,
    evaluate_dataset_selection_policy,
)


def completed_statuses() -> dict[str, str]:
    return {
        "schema": COMPLETED,
        "join": COMPLETED,
        "safe_inspector": COMPLETED,
        "component_consistency": COMPLETED,
        "pii": COMPLETED,
        "exact_duplicate": COMPLETED,
        "near_duplicate": COMPLETED,
        "leakage": COMPLETED,
        "license": COMPLETED,
        "benchmark": COMPLETED,
        "dataset_processing": COMPLETED,
    }


def current_statuses() -> dict[str, str]:
    values = completed_statuses()
    values.update(
        pii=REVIEW_REQUIRED,
        exact_duplicate=REVIEW_REQUIRED,
        near_duplicate=REVIEW_REQUIRED,
        leakage=REVIEW_REQUIRED,
        license=REVIEW_REQUIRED,
        benchmark=BLOCKED,
        dataset_processing=NOT_STARTED,
    )
    return values


def evaluate(
    requested_decision: str = CONDITIONALLY_SELECTED,
    **overrides: object,
) -> DatasetSelectionDecision:
    arguments: dict[str, object] = {
        "readiness_statuses": current_statuses(),
        "selection_conditions": CURRENT_SELECTION_CONDITIONS,
        "requested_decision": requested_decision,
    }
    arguments.update(overrides)
    return evaluate_dataset_selection_policy(**arguments)  # type: ignore[arg-type]


def test_completed_evidence_without_blockers_recommends_conditional_selection() -> None:
    decision = evaluate_dataset_selection_policy(
        completed_statuses(), (), CONDITIONALLY_SELECTED
    )
    assert decision.recommendation == CONDITIONALLY_SELECTED
    assert decision.decision_allowed is True
    assert decision.reason_codes == (
        "SCHEMA_VALIDATED",
        "JOIN_INTEGRITY_PASSED",
        "SAFE_INSPECTOR_VALIDATED",
    )


def test_current_review_and_blocked_state_is_recommendation_only() -> None:
    decision = evaluate()
    assert decision.recommendation == CONDITIONALLY_SELECTED
    assert decision.decision_allowed is True
    assert decision.processing_allowed is False
    assert decision.training_allowed is False
    assert decision.execution_allowed is False
    assert decision.reason_codes == (
        "SCHEMA_VALIDATED",
        "JOIN_INTEGRITY_PASSED",
        "SAFE_INSPECTOR_VALIDATED",
        "PII_POLICY_PENDING",
        "DUPLICATE_POLICY_PENDING",
        "LEAKAGE_POLICY_PENDING",
        "TERMS_EVIDENCE_PENDING",
        "BENCHMARK_SOURCE_PENDING",
        "BENCHMARK_CONTAMINATION_UNDETERMINED",
        "PROCESSING_MANIFEST_PENDING",
        "PROCESSING_BACKEND_PENDING",
    )


@pytest.mark.parametrize(
    "requested_decision",
    [CONDITIONALLY_SELECTED, DEFERRED, REJECTED],
)
def test_all_three_selection_options_are_valid_review_inputs(
    requested_decision: str,
) -> None:
    decision = evaluate(requested_decision)
    assert decision.requested_decision == requested_decision
    assert decision.decision_allowed is True
    assert decision.execution_allowed is False


@pytest.mark.parametrize("requested_decision", ["UNKNOWN", "", object(), []])
def test_unknown_decision_fails_closed(requested_decision: object) -> None:
    decision = evaluate(requested_decision)  # type: ignore[arg-type]
    assert decision.recommendation == DEFERRED
    assert decision.requested_decision == "INVALID"
    assert decision.decision_allowed is False
    assert decision.reason_codes == (INVALID_APPROVAL_REQUEST,)


@pytest.mark.parametrize("status", ["unknown", "approved", object(), []])
def test_unknown_readiness_fails_closed(status: object) -> None:
    statuses = current_statuses()
    statuses["pii"] = status  # type: ignore[assignment]
    decision = evaluate(readiness_statuses=statuses)
    assert decision.decision_allowed is False
    assert decision.reason_codes == (INVALID_APPROVAL_REQUEST,)


def test_missing_or_additional_readiness_evidence_fails_closed() -> None:
    missing = current_statuses()
    missing.pop("join")
    additional = current_statuses()
    additional["unexpected"] = COMPLETED
    assert evaluate(readiness_statuses=missing).decision_allowed is False
    assert evaluate(readiness_statuses=additional).decision_allowed is False


@pytest.mark.parametrize(
    "flag",
    ["processing_allowed", "training_allowed", "execution_allowed"],
)
def test_requested_downstream_permission_fails_closed(flag: str) -> None:
    decision = evaluate(**{flag: True})
    assert decision.decision_allowed is False
    assert decision.processing_allowed is False
    assert decision.training_allowed is False
    assert decision.execution_allowed is False


def test_final_approval_requires_valid_immutable_evidence_commit() -> None:
    missing = evaluate(final_approval_requested=True)
    malformed = evaluate(final_approval_requested=True, evidence_commit="not-a-commit")
    valid = evaluate(final_approval_requested=True, evidence_commit="a" * 40)
    assert missing.decision_allowed is False
    assert malformed.decision_allowed is False
    assert valid.decision_allowed is True


@pytest.mark.parametrize(
    "identity",
    [
        {"dataset_id": "SYNTHETIC-DATASET"},
        {"component": "SYNTHETIC-COMPONENT"},
    ],
)
def test_identity_mismatch_fails_closed(identity: dict[str, str]) -> None:
    decision = evaluate(**identity)
    assert decision.recommendation == DEFERRED
    assert decision.reason_codes == (INVALID_APPROVAL_REQUEST,)


def test_unknown_condition_fails_closed_without_echoing_it() -> None:
    decision = evaluate(selection_conditions=("SYNTHETIC_UNKNOWN_CONDITION",))
    assert decision.reason_codes == (INVALID_APPROVAL_REQUEST,)


def test_reason_codes_are_deterministic_for_condition_order() -> None:
    forward = evaluate()
    reverse = evaluate(selection_conditions=reversed(CURRENT_SELECTION_CONDITIONS))
    assert forward.reason_codes == reverse.reason_codes


def test_decision_is_immutable() -> None:
    decision = evaluate(dataset_id=AIHUB_71748, component=SFT)
    with pytest.raises(FrozenInstanceError):
        decision.decision_allowed = False  # type: ignore[misc]
