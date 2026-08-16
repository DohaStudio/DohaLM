from __future__ import annotations

import inspect
import threading
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest

from src.training import production_host_foundation as foundation
from src.training.errors import TrainingError
from src.training.execution_issuer import TrainingExecutionIssuerDecisionValue
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    ResolvedTrainingExecutionDecision,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationClaimResult,
    TrainingOrchestrationClaimStatus,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrainingOrchestrationTransition,
    TrustedDecisionProvenance,
    TrustedDecisionResolution,
)


FINGERPRINT = "sha256:" + "1" * 64
AUTHORIZATION_FINGERPRINT = "sha256:" + "2" * 64
EVIDENCE_FINGERPRINT = "sha256:" + "3" * 64
_DEFAULT_RESULT = object()


def _intent_values() -> dict[str, object]:
    return {
        "action": "full_pretraining",
        "execution_mode": "fresh",
        "dataset_version_reference": "dataset-version-1",
        "dataset_manifest_reference": "dataset-manifest-1",
        "expected_dataset_pair_fingerprint": "sha256:" + "4" * 64,
        "training_config_reference": "training-config-1",
        "expected_config_fingerprint": "sha256:" + "5" * 64,
        "readiness_evidence_reference": "readiness-evidence-1",
        "expected_readiness_fingerprint": "sha256:" + "6" * 64,
        "run_id": "run-1",
        "output_logical_root": "experiments/run-1",
        "decision_evidence_reference": "decision-evidence-1",
    }


def _intent() -> ProductionTrainingHostIntent:
    return ProductionTrainingHostIntent(**_intent_values())  # type: ignore[arg-type]


def _decision_values() -> dict[str, object]:
    return {
        "decision": TrainingExecutionIssuerDecisionValue.APPROVED,
        "authorization_id": "authorization-1",
        "issuer_id": "issuer-1",
        "approver_reference": "approver-1",
        "evidence_reference": "decision-evidence-1",
        "request_fingerprint": FINGERPRINT,
        "issued_at": "2026-08-13T04:00:00+09:00",
    }


def _decision() -> ResolvedTrainingExecutionDecision:
    return ResolvedTrainingExecutionDecision(**_decision_values())  # type: ignore[arg-type]


def _provenance_values() -> dict[str, object]:
    return {
        "source_identity": "decision-store-1",
        "policy_reference": "policy-1",
        "decision_authority_id": "99999999-9999-4999-8999-999999999999",
        "issuer_authority_id": "66666666-6666-4666-8666-666666666666",
        "approver_authority_id": "77777777-7777-4777-8777-777777777777",
        "bound_authorization_id": "authorization-1",
        "bound_issuer_id": "issuer-1",
        "bound_approver_reference": "approver-1",
        "bound_evidence_reference": "decision-evidence-1",
        "issuer_current": True,
        "approver_current": True,
        "current": True,
    }


def _resolution() -> TrustedDecisionResolution:
    return TrustedDecisionResolution(
        decision=_decision(),
        provenance=TrustedDecisionProvenance(
            **_provenance_values()  # type: ignore[arg-type]
        ),
    )


class FakeResolver:
    def __init__(
        self, result: object = _DEFAULT_RESULT, error: BaseException | None = None
    ):
        self.result = _resolution() if result is _DEFAULT_RESULT else result
        self.error = error
        self.calls: list[TrainingDecisionResolutionRequest] = []

    def resolve(
        self, request: TrainingDecisionResolutionRequest
    ) -> TrustedDecisionResolution:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result  # type: ignore[return-value]


class InMemoryJournal:
    """Deterministic test fake, not a production durability implementation."""

    def __init__(
        self, records: dict[str, TrainingOrchestrationRecord] | None = None
    ) -> None:
        self._lock = threading.Lock()
        self._records = dict(records or {})

    def claim(
        self, request: TrainingOrchestrationClaimRequest
    ) -> TrainingOrchestrationClaimResult:
        if type(request) is not TrainingOrchestrationClaimRequest:
            raise TrainingError(
                "TRAINING_HOST_JOURNAL_CONFLICT",
                "The training orchestration journal state conflicts with this operation.",
            )
        with self._lock:
            identity = request.identity
            current = self._records.get(identity.run_id)
            if current is None:
                record = TrainingOrchestrationRecord(
                    claim=request,
                    phase=TrainingOrchestrationPhase.CLAIMED,
                    journal_version=1,
                    reservation_group_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
                self._records[identity.run_id] = record
                status = TrainingOrchestrationClaimStatus.ACQUIRED
            elif current.claim != request:
                raise TrainingError(
                    "TRAINING_HOST_JOURNAL_CONFLICT",
                    "The training orchestration journal state conflicts with this operation.",
                )
            else:
                record = current
                status = TrainingOrchestrationClaimStatus.REPLAY
            return TrainingOrchestrationClaimResult(status=status, record=record)

    def read(self, run_id: str) -> TrainingOrchestrationRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def transition(
        self, transition: TrainingOrchestrationTransition
    ) -> TrainingOrchestrationRecord:
        with self._lock:
            current = self._records.get(transition.identity.run_id)
            if current is None:
                raise TrainingError(
                    "TRAINING_HOST_JOURNAL_CONFLICT",
                    "The training orchestration journal state conflicts with this operation.",
                )
            updated = foundation._next_journal_record(current, transition)
            self._records[transition.identity.run_id] = updated
            return updated


def _identity(fingerprint: str = FINGERPRINT) -> TrainingOrchestrationIdentity:
    return TrainingOrchestrationIdentity(
        run_id="run-1", request_fingerprint=fingerprint
    )


def _decision_request(
    fingerprint: str = FINGERPRINT,
) -> TrainingDecisionResolutionRequest:
    return TrainingDecisionResolutionRequest(
        intent=_intent(),
        decision_authority_id="99999999-9999-4999-8999-999999999999",
        request_fingerprint=fingerprint,
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        dataset_pair_authority_id="88888888-8888-4888-8888-888888888888",
        dataset_pair_fingerprint="sha256:" + "4" * 64,
        config_fingerprint="sha256:" + "5" * 64,
        readiness_fingerprint="sha256:" + "6" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="policy-1",
    )


def _claim_request(
    fingerprint: str = FINGERPRINT,
) -> TrainingOrchestrationClaimRequest:
    return TrainingOrchestrationClaimRequest(
        identity=_identity(fingerprint),
        intent_fingerprint="sha256:" + "7" * 64,
        orchestration_correlation_id="run-1",
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        dataset_pair_fingerprint="sha256:" + "4" * 64,
        config_fingerprint="sha256:" + "5" * 64,
        readiness_fingerprint="sha256:" + "6" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="policy-1",
        process_boundary_id="process-boundary-1",
    )


def _record(
    phase: TrainingOrchestrationPhase,
    *,
    fingerprint: str = FINGERPRINT,
    version: int = 1,
    **kwargs: object,
) -> TrainingOrchestrationRecord:
    return TrainingOrchestrationRecord(
        claim=_claim_request(fingerprint),
        phase=phase,
        journal_version=version,
        reservation_group_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        **kwargs,  # type: ignore[arg-type]
    )


def _transition(
    identity: TrainingOrchestrationIdentity,
    expected: TrainingOrchestrationPhase,
    next_phase: TrainingOrchestrationPhase,
    **kwargs: object,
) -> TrainingOrchestrationTransition:
    return TrainingOrchestrationTransition(
        identity=identity,
        process_boundary_id="process-boundary-1",
        expected_phase=expected,
        expected_version=int(kwargs.pop("expected_version", 1)),
        next_phase=next_phase,
        **kwargs,  # type: ignore[arg-type]
    )


def test_host_intent_is_exact_immutable_reference_only_contract() -> None:
    intent = _intent()
    assert [item.name for item in fields(intent)] == [
        "action",
        "execution_mode",
        "dataset_version_reference",
        "dataset_manifest_reference",
        "expected_dataset_pair_fingerprint",
        "training_config_reference",
        "expected_config_fingerprint",
        "readiness_evidence_reference",
        "expected_readiness_fingerprint",
        "run_id",
        "output_logical_root",
        "decision_evidence_reference",
    ]
    forbidden = {
        "decision",
        "authorization_id",
        "issuer_id",
        "approver_reference",
        "evidence_reference",
        "issued_at",
        "request_fingerprint",
        "approval",
        "capability",
        "adapter",
        "resolver",
        "journal",
    }
    assert forbidden.isdisjoint(item.name for item in fields(intent))
    with pytest.raises(FrozenInstanceError):
        intent.run_id = "changed"  # type: ignore[misc]
    assert repr(intent) == "ProductionTrainingHostIntent(<redacted>)"
    assert not hasattr(intent, "__dict__")


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("action", "evaluation"),
        ("execution_mode", "resume"),
        ("dataset_version_reference", ""),
        ("dataset_manifest_reference", " value"),
        ("training_config_reference", "C:\\private\\config.yaml"),
        ("readiness_evidence_reference", "value\nsecret"),
        ("run_id", True),
        ("decision_evidence_reference", "../evidence"),
        ("expected_dataset_pair_fingerprint", "sha256:ABC"),
        ("expected_config_fingerprint", object()),
        ("expected_readiness_fingerprint", ""),
        ("output_logical_root", "C:\\private\\run"),
        ("output_logical_root", "../run"),
    ],
)
def test_host_intent_invalid_values_fail_closed_without_echo(
    field: str, invalid: object
) -> None:
    values = _intent_values()
    values[field] = invalid
    with pytest.raises(TrainingError) as caught:
        ProductionTrainingHostIntent(**values)  # type: ignore[arg-type]
    assert caught.value.code == "TRAINING_HOST_INTENT_INVALID"
    if str(invalid).strip():
        assert str(invalid) not in str(caught.value)


def test_host_intent_rejects_authority_and_dependency_injection() -> None:
    signature = inspect.signature(ProductionTrainingHostIntent)
    for name in (
        "decision",
        "approved",
        "capability",
        "adapter",
        "resolver",
        "journal",
        "callback",
        "path",
    ):
        assert name not in signature.parameters
    with pytest.raises(TypeError):
        ProductionTrainingHostIntent(
            **_intent_values(),
            resolver=FakeResolver(),  # type: ignore[arg-type]
        )


def test_resolved_decision_has_exact_seven_immutable_fields() -> None:
    decision = _decision()
    assert [(item.name, item.type) for item in fields(decision)] == [
        ("decision", "TrainingExecutionIssuerDecisionValue"),
        ("authorization_id", "str"),
        ("issuer_id", "str"),
        ("approver_reference", "str"),
        ("evidence_reference", "str"),
        ("request_fingerprint", "str"),
        ("issued_at", "str"),
    ]
    with pytest.raises(FrozenInstanceError):
        decision.authorization_id = "changed"  # type: ignore[misc]
    assert repr(decision) == "ResolvedTrainingExecutionDecision(<redacted>)"
    assert not hasattr(decision, "__dict__")


@pytest.mark.parametrize("missing", tuple(_decision_values()))
def test_each_missing_decision_field_is_rejected(missing: str) -> None:
    values = _decision_values()
    values.pop(missing)
    with pytest.raises(TypeError):
        ResolvedTrainingExecutionDecision(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("decision", "approved"),
        ("decision", SimpleNamespace(value="approved")),
        ("authorization_id", ""),
        ("authorization_id", 1),
        ("issuer_id", " "),
        ("issuer_id", object()),
        ("approver_reference", "approver/path"),
        ("approver_reference", None),
        ("evidence_reference", "../evidence"),
        ("evidence_reference", False),
        ("request_fingerprint", "sha256:" + "A" * 64),
        ("request_fingerprint", 1),
        ("issued_at", "2026-08-13T04:00:00"),
        ("issued_at", "2026-08-12T19:00:00Z"),
        ("issued_at", object()),
    ],
)
def test_each_decision_field_rejects_wrong_or_noncanonical_values(
    field: str, invalid: object
) -> None:
    values = _decision_values()
    values[field] = invalid
    with pytest.raises(TrainingError) as caught:
        ResolvedTrainingExecutionDecision(**values)  # type: ignore[arg-type]
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"
    if str(invalid).strip():
        assert str(invalid) not in str(caught.value)


def test_resolver_valid_result_is_exact_and_request_bound() -> None:
    request = _decision_request()
    resolver = FakeResolver()
    result = foundation._resolve_trusted_training_decision(resolver, request)
    assert result is resolver.result.decision
    assert resolver.calls == [request]


def test_c1_2_decision_and_journal_dtos_are_explicit_and_complete() -> None:
    assert [item.name for item in fields(TrainingDecisionResolutionRequest)] == [
        "intent",
        "decision_authority_id",
        "request_fingerprint",
        "dataset_version_id",
        "dataset_manifest_id",
        "dataset_pair_authority_id",
        "dataset_pair_fingerprint",
        "config_fingerprint",
        "readiness_fingerprint",
        "source_commit",
        "prerequisite_policy_reference",
    ]
    assert [item.name for item in fields(TrainingOrchestrationClaimRequest)] == [
        "identity",
        "intent_fingerprint",
        "orchestration_correlation_id",
        "dataset_version_id",
        "dataset_manifest_id",
        "dataset_pair_fingerprint",
        "config_fingerprint",
        "readiness_fingerprint",
        "source_commit",
        "prerequisite_policy_reference",
        "process_boundary_id",
    ]
    record_names = {item.name for item in fields(TrainingOrchestrationRecord)}
    assert {
        "claim",
        "phase",
        "journal_version",
        "reservation_group_id",
        "authorization_id",
        "issuer_id",
        "approver_reference",
        "evidence_reference",
        "decision_policy_reference",
        "backend_entered",
        "reconciliation_required",
    } <= record_names
    assert {"context", "cache", "connection", "dsn"}.isdisjoint(record_names)


def test_resolver_resolution_and_provenance_are_immutable() -> None:
    resolution = _resolution()
    with pytest.raises(FrozenInstanceError):
        resolution.decision = _decision()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        resolution.provenance.current = False  # type: ignore[misc]
    assert repr(resolution) == "TrustedDecisionResolution(<redacted>)"
    assert repr(resolution.provenance) == "TrustedDecisionProvenance(<redacted>)"


@pytest.mark.parametrize(
    ("binding", "value"),
    [
        ("bound_authorization_id", "authorization-2"),
        ("bound_issuer_id", "issuer-2"),
        ("bound_approver_reference", "approver-2"),
        ("bound_evidence_reference", "decision-evidence-2"),
        ("decision_authority_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("issuer_current", False),
        ("approver_current", False),
        ("current", False),
    ],
)
def test_resolver_rejects_stale_and_wrong_authority_bindings(
    binding: str, value: object
) -> None:
    provenance = _provenance_values()
    provenance[binding] = value
    resolver = FakeResolver(
        TrustedDecisionResolution(
            decision=_decision(),
            provenance=TrustedDecisionProvenance(
                **provenance  # type: ignore[arg-type]
            ),
        )
    )
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(resolver, _decision_request())
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"


def test_resolver_rejects_evidence_reference_and_request_mismatch() -> None:
    decision_values = _decision_values()
    decision_values["evidence_reference"] = "decision-evidence-2"
    provenance = _provenance_values()
    provenance["bound_evidence_reference"] = "decision-evidence-2"
    resolver = FakeResolver(
        TrustedDecisionResolution(
            decision=ResolvedTrainingExecutionDecision(
                **decision_values  # type: ignore[arg-type]
            ),
            provenance=TrustedDecisionProvenance(
                **provenance  # type: ignore[arg-type]
            ),
        )
    )
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_INVALID"):
        foundation._resolve_trusted_training_decision(resolver, _decision_request())

    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            FakeResolver(),
            _decision_request("sha256:" + "9" * 64),
        )
    assert caught.value.code == "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"


@pytest.mark.parametrize(
    "result",
    [None, object(), SimpleNamespace(decision=_decision()), _decision()],
)
def test_resolver_missing_and_duck_typed_results_fail_closed(result: object) -> None:
    resolver = FakeResolver(result=result)
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(resolver, _decision_request())
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"


@pytest.mark.parametrize(
    "error",
    [RuntimeError("C:\\private\\decision.json"), ValueError("secret-token")],
)
def test_resolver_exception_is_sanitized(error: BaseException) -> None:
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            FakeResolver(error=error),
            _decision_request(),
        )
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_UNAVAILABLE"
    assert str(error) not in str(caught.value)
    assert type(error).__name__ not in str(caught.value)


def test_resolver_preserves_explicit_missing_decision_classification() -> None:
    unavailable = TrainingError(
        "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
        "A training execution decision is unavailable.",
    )
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            FakeResolver(error=unavailable),
            _decision_request(),
        )
    assert caught.value is unavailable


def test_resolved_evidence_grants_no_execution_or_issuance_authority() -> None:
    result = foundation._resolve_trusted_training_decision(
        FakeResolver(), _decision_request()
    )
    names = {item.name for item in fields(result)}
    assert {
        "approval",
        "capability",
        "submit",
        "issue",
        "consume",
        "execute",
        "backend",
    }.isdisjoint(names)
    assert not callable(result)


def test_journal_first_claim_and_same_identity_replay() -> None:
    journal = InMemoryJournal()
    request = _claim_request()
    first = journal.claim(request)
    replay = journal.claim(request)
    assert first.status is TrainingOrchestrationClaimStatus.ACQUIRED
    assert replay.status is TrainingOrchestrationClaimStatus.REPLAY
    assert replay.record is first.record


def test_journal_same_run_different_fingerprint_is_conflict_without_mutation() -> None:
    journal = InMemoryJournal()
    original = journal.claim(_claim_request()).record
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        journal.claim(_claim_request("sha256:" + "9" * 64))
    assert journal.read("run-1") is original


def test_journal_concurrent_claim_has_single_winner() -> None:
    journal = InMemoryJournal()
    request = _claim_request()
    barrier = threading.Barrier(9)
    outcomes: list[TrainingOrchestrationClaimStatus] = []

    def worker() -> None:
        barrier.wait()
        outcomes.append(journal.claim(request).status)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert outcomes.count(TrainingOrchestrationClaimStatus.ACQUIRED) == 1
    assert outcomes.count(TrainingOrchestrationClaimStatus.REPLAY) == 7


def test_journal_valid_cas_lifecycle_and_manual_reconciliation() -> None:
    journal = InMemoryJournal()
    identity = _identity()
    request = _claim_request()
    journal.claim(request)
    phases = (
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
        TrainingOrchestrationPhase.DECISION_SUBMITTED,
        TrainingOrchestrationPhase.APPROVAL_CONSUMED,
        TrainingOrchestrationPhase.BACKEND_ENTERED,
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
    )
    expected = TrainingOrchestrationPhase.CLAIMED
    record = journal.read("run-1")
    for next_phase in phases:
        kwargs = {}
        if next_phase is TrainingOrchestrationPhase.DECISION_SUBMITTED:
            kwargs = {
                "authorization_id": "authorization-1",
                "issuer_id": "issuer-1",
                "approver_reference": "approver-1",
                "evidence_reference": "decision-evidence-1",
                "decision_policy_reference": "policy-1",
                "authorization_fingerprint": AUTHORIZATION_FINGERPRINT,
                "decision_evidence_fingerprint": EVIDENCE_FINGERPRINT,
            }
        assert record is not None
        record = journal.transition(
            _transition(
                identity,
                expected,
                next_phase,
                expected_version=record.journal_version,
                **kwargs,
            )
        )
        expected = next_phase
    assert record is not None
    assert record.backend_entered is True
    assert record.reconciliation_required is True
    assert record.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    assert journal.claim(request).status is TrainingOrchestrationClaimStatus.REPLAY


def test_approval_consumed_record_is_not_backend_entered() -> None:
    consumed = _record(TrainingOrchestrationPhase.APPROVAL_CONSUMED)
    assert consumed.backend_entered is False
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        _record(TrainingOrchestrationPhase.APPROVAL_CONSUMED, backend_entered=True)


@pytest.mark.parametrize(
    "phase",
    (
        TrainingOrchestrationPhase.CLAIMED,
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
    ),
)
def test_pre_submission_active_phase_can_require_restart_reconciliation(
    phase: TrainingOrchestrationPhase,
) -> None:
    identity = _identity()
    record = _record(phase)
    reconciled = foundation._next_journal_record(
        record,
        _transition(
            identity,
            phase,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
            expected_version=record.journal_version,
            reason_code="PROCESS_RESTART",
        ),
    )
    assert reconciled.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    assert reconciled.reconciliation_required is True


def test_journal_stale_and_invalid_transition_has_zero_partial_mutation() -> None:
    journal = InMemoryJournal()
    identity = _identity()
    original = journal.claim(_claim_request()).record
    stale = _transition(
        identity,
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        journal.transition(stale)
    assert journal.read("run-1") is original

    journal.transition(
        _transition(
            identity,
            TrainingOrchestrationPhase.CLAIMED,
            TrainingOrchestrationPhase.RESOLVED,
            expected_version=1,
        )
    )
    validated = journal.transition(
        _transition(
            identity,
            TrainingOrchestrationPhase.RESOLVED,
            TrainingOrchestrationPhase.VALIDATED,
            expected_version=2,
        )
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        journal.transition(
            _transition(
                identity,
                TrainingOrchestrationPhase.VALIDATED,
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                expected_version=3,
            )
        )
    assert journal.read("run-1") is validated


def test_journal_terminal_record_cannot_be_overwritten() -> None:
    identity = _identity()
    terminal = _record(
        TrainingOrchestrationPhase.FAILED, reason_code="DECISION_INVALID"
    )
    journal = InMemoryJournal({identity.run_id: terminal})
    assert (
        journal.claim(_claim_request()).status
        is TrainingOrchestrationClaimStatus.REPLAY
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        foundation._next_journal_record(
            terminal,
            object(),  # type: ignore[arg-type]
        )
    assert journal.read(identity.run_id) is terminal


def test_restart_record_restores_no_approval_or_capability() -> None:
    identity = _identity()
    record = _record(
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        authorization_id="authorization-1",
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="decision-evidence-1",
        decision_policy_reference="policy-1",
        authorization_fingerprint=AUTHORIZATION_FINGERPRINT,
        decision_evidence_fingerprint=EVIDENCE_FINGERPRINT,
        backend_entered=True,
        reconciliation_required=True,
        reason_code="OUTCOME_UNKNOWN",
    )
    restarted = InMemoryJournal({identity.run_id: record})
    replay = restarted.claim(_claim_request())
    assert replay.status is TrainingOrchestrationClaimStatus.REPLAY
    assert (
        replay.record.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    )
    names = {item.name for item in fields(replay.record)}
    assert names == {
        "claim",
        "phase",
        "journal_version",
        "reservation_group_id",
        "authorization_id",
        "issuer_id",
        "approver_reference",
        "evidence_reference",
        "decision_policy_reference",
        "authorization_fingerprint",
        "decision_evidence_fingerprint",
        "backend_entered",
        "reconciliation_required",
        "reason_code",
    }
    assert {
        "decision",
        "approval",
        "capability",
        "execute",
        "submit",
        "backend",
    }.isdisjoint(names)
    with pytest.raises(FrozenInstanceError):
        replay.record.phase = TrainingOrchestrationPhase.CLAIMED  # type: ignore[misc]
    assert repr(replay.record) == "TrainingOrchestrationRecord(<redacted>)"
