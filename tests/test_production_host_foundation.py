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
        "bound_authorization_id": "authorization-1",
        "bound_issuer_id": "issuer-1",
        "bound_approver_reference": "approver-1",
        "bound_evidence_reference": "decision-evidence-1",
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
        self.calls: list[ProductionTrainingHostIntent] = []

    def resolve(
        self, intent: ProductionTrainingHostIntent
    ) -> TrustedDecisionResolution:
        self.calls.append(intent)
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
        self, identity: TrainingOrchestrationIdentity
    ) -> TrainingOrchestrationClaimResult:
        if type(identity) is not TrainingOrchestrationIdentity:
            raise TrainingError(
                "TRAINING_HOST_JOURNAL_CONFLICT",
                "The training orchestration journal state conflicts with this operation.",
            )
        with self._lock:
            current = self._records.get(identity.run_id)
            if current is None:
                record = TrainingOrchestrationRecord(
                    identity=identity,
                    phase=TrainingOrchestrationPhase.CLAIMED,
                )
                self._records[identity.run_id] = record
                status = TrainingOrchestrationClaimStatus.ACQUIRED
            elif current.identity != identity:
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


def _transition(
    identity: TrainingOrchestrationIdentity,
    expected: TrainingOrchestrationPhase,
    next_phase: TrainingOrchestrationPhase,
    **kwargs: object,
) -> TrainingOrchestrationTransition:
    return TrainingOrchestrationTransition(
        identity=identity,
        expected_phase=expected,
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
    intent = _intent()
    resolver = FakeResolver()
    result = foundation._resolve_trusted_training_decision(
        resolver, intent, canonical_request_fingerprint=FINGERPRINT
    )
    assert result is resolver.result.decision
    assert resolver.calls == [intent]


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
        foundation._resolve_trusted_training_decision(
            resolver, _intent(), canonical_request_fingerprint=FINGERPRINT
        )
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
        foundation._resolve_trusted_training_decision(
            resolver, _intent(), canonical_request_fingerprint=FINGERPRINT
        )

    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            FakeResolver(),
            _intent(),
            canonical_request_fingerprint="sha256:" + "9" * 64,
        )
    assert caught.value.code == "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"


@pytest.mark.parametrize(
    "result",
    [None, object(), SimpleNamespace(decision=_decision()), _decision()],
)
def test_resolver_missing_and_duck_typed_results_fail_closed(result: object) -> None:
    resolver = FakeResolver(result=result)
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            resolver, _intent(), canonical_request_fingerprint=FINGERPRINT
        )
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"


@pytest.mark.parametrize(
    "error",
    [RuntimeError("C:\\private\\decision.json"), ValueError("secret-token")],
)
def test_resolver_exception_is_sanitized(error: BaseException) -> None:
    with pytest.raises(TrainingError) as caught:
        foundation._resolve_trusted_training_decision(
            FakeResolver(error=error),
            _intent(),
            canonical_request_fingerprint=FINGERPRINT,
        )
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_UNAVAILABLE"
    assert str(error) not in str(caught.value)
    assert type(error).__name__ not in str(caught.value)


def test_resolved_evidence_grants_no_execution_or_issuance_authority() -> None:
    result = foundation._resolve_trusted_training_decision(
        FakeResolver(), _intent(), canonical_request_fingerprint=FINGERPRINT
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
    identity = _identity()
    first = journal.claim(identity)
    replay = journal.claim(identity)
    assert first.status is TrainingOrchestrationClaimStatus.ACQUIRED
    assert replay.status is TrainingOrchestrationClaimStatus.REPLAY
    assert replay.record is first.record


def test_journal_same_run_different_fingerprint_is_conflict_without_mutation() -> None:
    journal = InMemoryJournal()
    original = journal.claim(_identity()).record
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        journal.claim(_identity("sha256:" + "9" * 64))
    assert journal.read("run-1") is original


def test_journal_concurrent_claim_has_single_winner() -> None:
    journal = InMemoryJournal()
    identity = _identity()
    barrier = threading.Barrier(9)
    outcomes: list[TrainingOrchestrationClaimStatus] = []

    def worker() -> None:
        barrier.wait()
        outcomes.append(journal.claim(identity).status)

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
    journal.claim(identity)
    phases = (
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
        TrainingOrchestrationPhase.DECISION_SUBMITTED,
        TrainingOrchestrationPhase.BACKEND_ENTERED,
        TrainingOrchestrationPhase.APPROVAL_CONSUMED,
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
    )
    expected = TrainingOrchestrationPhase.CLAIMED
    record = journal.read("run-1")
    for next_phase in phases:
        kwargs = {}
        if next_phase is TrainingOrchestrationPhase.DECISION_SUBMITTED:
            kwargs = {
                "authorization_fingerprint": AUTHORIZATION_FINGERPRINT,
                "decision_evidence_fingerprint": EVIDENCE_FINGERPRINT,
            }
        record = journal.transition(
            _transition(identity, expected, next_phase, **kwargs)
        )
        expected = next_phase
    assert record is not None
    assert record.backend_entered is True
    assert record.reconciliation_required is True
    assert record.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    assert journal.claim(identity).status is TrainingOrchestrationClaimStatus.REPLAY


def test_journal_stale_and_invalid_transition_has_zero_partial_mutation() -> None:
    journal = InMemoryJournal()
    identity = _identity()
    original = journal.claim(identity).record
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
        )
    )
    validated = journal.transition(
        _transition(
            identity,
            TrainingOrchestrationPhase.RESOLVED,
            TrainingOrchestrationPhase.VALIDATED,
        )
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        journal.transition(
            _transition(
                identity,
                TrainingOrchestrationPhase.VALIDATED,
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
            )
        )
    assert journal.read("run-1") is validated


def test_journal_terminal_record_cannot_be_overwritten() -> None:
    identity = _identity()
    terminal = TrainingOrchestrationRecord(
        identity=identity,
        phase=TrainingOrchestrationPhase.FAILED,
        reason_code="DECISION_INVALID",
    )
    journal = InMemoryJournal({identity.run_id: terminal})
    assert journal.claim(identity).status is TrainingOrchestrationClaimStatus.REPLAY
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        foundation._next_journal_record(
            terminal,
            object(),  # type: ignore[arg-type]
        )
    assert journal.read(identity.run_id) is terminal


def test_restart_record_restores_no_approval_or_capability() -> None:
    identity = _identity()
    record = TrainingOrchestrationRecord(
        identity=identity,
        phase=TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        authorization_fingerprint=AUTHORIZATION_FINGERPRINT,
        decision_evidence_fingerprint=EVIDENCE_FINGERPRINT,
        backend_entered=True,
        reconciliation_required=True,
        reason_code="OUTCOME_UNKNOWN",
    )
    restarted = InMemoryJournal({identity.run_id: record})
    replay = restarted.claim(identity)
    assert replay.status is TrainingOrchestrationClaimStatus.REPLAY
    assert (
        replay.record.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    )
    names = {item.name for item in fields(replay.record)}
    assert names == {
        "identity",
        "phase",
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
        "evidence",
        "authorization_id",
        "issuer_id",
        "approver_reference",
        "evidence_reference",
    }.isdisjoint(names)
    with pytest.raises(FrozenInstanceError):
        replay.record.phase = TrainingOrchestrationPhase.CLAIMED  # type: ignore[misc]
    assert repr(replay.record) == "TrainingOrchestrationRecord(<redacted>)"
