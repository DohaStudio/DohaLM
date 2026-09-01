from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.training import production_composition as composition
from src.training.errors import TrainingError
from src.training.execution_issuer import TrainingExecutionIssuerDecisionValue
from src.training.production_composition import (
    _PostgresTrainingCompositionConfiguration,
    _compose_postgres_training_host,
)
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    ResolvedTrainingExecutionDecision,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrustedDecisionProvenance,
    TrustedDecisionResolution,
)
from src.training.production_full_pretraining_host import ProductionTrainingHostResult
from src.training.production_intent_authority import (
    TrainingIntentContinuation,
    TrainingIntentDecisionBinding,
    TrainingIntentMode,
    TrainingIntentRecord,
    TrainingIntentSubmission,
    TrainingIntentValidationSnapshot,
    project_training_execution_request,
    training_intent_fingerprint,
)
from src.training.production_training_application import (
    ProductionTrainingApplicationCommand,
    ProductionTrainingApplicationEntrypoint,
    ProductionTrainingCompositionReadiness,
    ProductionTrainingDryRunStatus,
)


SUBMITTER_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
VERSION_ID = "33333333-3333-4333-8333-333333333333"
MANIFEST_ID = "44444444-4444-4444-8444-444444444444"
PAIR_ID = "55555555-5555-4555-8555-555555555555"
CONFIG_ID = "66666666-6666-4666-8666-666666666666"
READINESS_ID = "77777777-7777-4777-8777-777777777777"
DECISION_ID = "88888888-8888-4888-8888-888888888888"
ISSUER_ID = "99999999-9999-4999-8999-999999999999"
APPROVER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SOURCE = "a" * 40
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
TIMESTAMP = "2026-09-01T00:00:00+00:00"


def _submission(**changes: object) -> TrainingIntentSubmission:
    values: dict[str, object] = {
        "client_request_id": "application-request-1",
        "requested_run_id": "production-run-1",
        "execution_mode": TrainingIntentMode.FRESH,
        "dataset_version_authority_id": VERSION_ID,
        "dataset_manifest_authority_id": MANIFEST_ID,
        "dataset_pair_authority_id": PAIR_ID,
        "dataset_version_id": "dataset-version-1",
        "dataset_manifest_id": "dataset-manifest-1",
        "dataset_pair_fingerprint": "sha256:" + "1" * 64,
        "config_authority_id": CONFIG_ID,
        "config_fingerprint": "sha256:" + "2" * 64,
        "readiness_authority_id": READINESS_ID,
        "readiness_fingerprint": "sha256:" + "3" * 64,
        "source_commit": SOURCE,
        "output_logical_root": "production/runs/run-1",
    }
    values.update(changes)
    return TrainingIntentSubmission(**values)  # type: ignore[arg-type]


def _record(submission: TrainingIntentSubmission | None = None) -> TrainingIntentRecord:
    value = submission or _submission()
    return TrainingIntentRecord(
        intent_id=INTENT_ID,
        submitter_authority_id=SUBMITTER_ID,
        submission=value,
        intent_fingerprint=training_intent_fingerprint(SUBMITTER_ID, value),
        created_at=NOW,
    )


def _binding(
    record: TrainingIntentRecord,
    decision: TrainingExecutionIssuerDecisionValue = TrainingExecutionIssuerDecisionValue.APPROVED,
) -> TrainingIntentDecisionBinding:
    return TrainingIntentDecisionBinding(
        intent_id=record.intent_id,
        decision_authority_id=DECISION_ID,
        decision=decision,
        authorization_id="authorization-1",
        issuer_authority_id=ISSUER_ID,
        issuer_id="issuer-1",
        approver_authority_id=APPROVER_ID,
        approver_reference="approver-1",
        evidence_reference="decision:evidence-1",
        request_fingerprint=project_training_execution_request(
            record
        ).request_fingerprint,
        bound_at=NOW,
    )


def _snapshot(**changes: object) -> TrainingIntentValidationSnapshot:
    record = changes.pop("intent", _record())
    values: dict[str, object] = {
        "intent": record,
        "binding": _binding(record),
        "submitter_current": True,
        "dataset_version_current": True,
        "dataset_manifest_current": True,
        "dataset_pair_current": True,
        "config_current": True,
        "readiness_current": True,
        "decision_current": True,
        "issuer_current": True,
        "approver_current": True,
        "current_evidence_current": True,
    }
    values.update(changes)
    return TrainingIntentValidationSnapshot(**values)  # type: ignore[arg-type]


class _Authority:
    def __init__(
        self,
        snapshot: TrainingIntentValidationSnapshot,
        *,
        stale_on_recheck: bool = False,
    ) -> None:
        self.snapshot = snapshot
        self.stale_on_recheck = stale_on_recheck

    def read_validation_snapshot(
        self, intent_id: str
    ) -> TrainingIntentValidationSnapshot:
        assert intent_id == self.snapshot.intent.intent_id
        return self.snapshot

    def verify_current_evidence(self, intent: TrainingIntentRecord) -> None:
        assert intent == self.snapshot.intent
        if self.stale_on_recheck:
            raise TrainingError("TRAINING_CURRENT_EVIDENCE_STALE", "stale")


def _host_intent(record: TrainingIntentRecord) -> ProductionTrainingHostIntent:
    submission = record.submission
    return ProductionTrainingHostIntent(
        action=submission.action,
        execution_mode=submission.execution_mode.value,
        dataset_version_reference=f"dataset-version:{VERSION_ID}",
        dataset_manifest_reference=f"dataset-manifest:{MANIFEST_ID}",
        expected_dataset_pair_fingerprint=submission.dataset_pair_fingerprint,
        training_config_reference=f"config:{CONFIG_ID}",
        expected_config_fingerprint=submission.config_fingerprint,
        readiness_evidence_reference=f"readiness:{READINESS_ID}",
        expected_readiness_fingerprint=submission.readiness_fingerprint,
        run_id=submission.requested_run_id,
        output_logical_root=submission.output_logical_root,
        decision_evidence_reference="decision:evidence-1",
    )


class _Composition:
    def __init__(
        self, record: TrainingIntentRecord, *, failure: str | None = None
    ) -> None:
        self.record = record
        self.failure = failure
        self.prepares = 0
        self.preflights = 0
        self.activations = 0
        self.shutdowns = 0
        self.host_run = Mock()
        self.backend = Mock()
        self.journal_write = Mock()
        self.checkpoint_write = Mock()
        self.artifact_write = Mock()

    def preflight(self):
        self.preflights += 1
        return object()

    def prepare_activation(self, validated):
        self.prepares += 1
        if self.failure is not None:
            raise TrainingError(self.failure, "synthetic redacted failure")
        return ProductionTrainingCompositionReadiness(
            host_intent=_host_intent(self.record),
            execution_request=validated.execution_request,
            provider="postgresql",
            process_boundary_id="process:production-1",
            prerequisite_policy_reference="policy:prerequisite-1",
            decision_policy_reference="policy:decision-1",
            prerequisite_evaluated_at=TIMESTAMP,
            decision_issued_at=TIMESTAMP,
            run_unused=True,
            output_available=True,
            continuation_verified=True,
            host_contract_compatible=True,
            mutation_count=0,
        )

    def activate(self, readiness):
        self.activations += 1
        self.journal_write(readiness.execution_request.run_id)
        self.host_run(readiness.host_intent)
        return ProductionTrainingHostResult(
            identity=TrainingOrchestrationIdentity(
                run_id=readiness.execution_request.run_id,
                request_fingerprint=readiness.execution_request.request_fingerprint,
            ),
            phase=TrainingOrchestrationPhase.COMPLETED,
            backend_entered=True,
            reconciliation_required=False,
            replayed=False,
            reason_code=None,
        )

    def shutdown(self) -> None:
        self.shutdowns += 1


class _Factory:
    def __init__(self, composition: _Composition) -> None:
        self.composition = composition
        self.composes = 0

    def compose(self) -> _Composition:
        self.composes += 1
        return self.composition


def _entrypoint(
    snapshot: TrainingIntentValidationSnapshot | None = None,
    *,
    failure: str | None = None,
) -> tuple[ProductionTrainingApplicationEntrypoint, _Composition]:
    actual = snapshot or _snapshot()
    root = _Composition(actual.intent, failure=failure)
    return ProductionTrainingApplicationEntrypoint(
        _Authority(actual), _Factory(root)
    ), root


def test_approved_fresh_intent_builds_immutable_transient_plan_without_side_effects() -> (
    None
):
    entrypoint, root = _entrypoint()
    result = entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    plan = result.plan
    assert result.status is ProductionTrainingDryRunStatus.READY_FOR_ACTIVATION
    assert result.currentness_must_be_revalidated is True
    assert plan.intent_id == INTENT_ID
    assert plan.execution_request == project_training_execution_request(_record())
    assert plan.host_intent.run_id == plan.execution_request.run_id
    assert plan.plan_fingerprint.startswith("sha256:")
    assert root.prepares == root.shutdowns == 1
    for spy in (
        root.host_run,
        root.backend,
        root.journal_write,
        root.checkpoint_write,
        root.artifact_write,
    ):
        spy.assert_not_called()
    with pytest.raises(FrozenInstanceError):
        plan.intent_id = "override"  # type: ignore[misc]


def test_activate_revalidates_then_invokes_only_composition_host_boundary() -> None:
    entrypoint, root = _entrypoint()
    result = entrypoint.activate(
        ProductionTrainingApplicationCommand(INTENT_ID, SOURCE)
    )
    assert result.plan.intent_id == INTENT_ID
    assert result.execution.phase is TrainingOrchestrationPhase.COMPLETED
    assert root.preflights == root.prepares == root.activations == root.shutdowns == 1
    root.journal_write.assert_called_once_with("production-run-1")
    root.host_run.assert_called_once()
    root.backend.assert_not_called()
    root.checkpoint_write.assert_not_called()
    root.artifact_write.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"binding": None},
        {"submitter_current": False},
        {"dataset_pair_current": False},
        {"config_current": False},
        {"readiness_current": False},
        {"decision_current": False},
    ],
)
def test_activate_stale_or_missing_authority_stops_before_journal_and_host(
    changes: dict[str, object],
) -> None:
    entrypoint, root = _entrypoint(_snapshot(**changes))
    with pytest.raises(TrainingError):
        entrypoint.activate(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert root.preflights == root.prepares == root.activations == 0
    root.journal_write.assert_not_called()
    root.host_run.assert_not_called()


def test_approved_r3_continuation_is_preserved_exactly() -> None:
    continuation = TrainingIntentContinuation(
        predecessor_run_id="run-aihub-71748-local-v1-r3",
        checkpoint_reference="checkpoint-4883",
        source_step=4_883,
        target_cumulative_steps=34_817,
    )
    record = _record(
        _submission(
            execution_mode=TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION,
            continuation=continuation,
        )
    )
    snapshot = _snapshot(intent=record, binding=_binding(record))
    entrypoint, _ = _entrypoint(snapshot)
    result = entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert result.plan.continuation == continuation
    assert result.plan.execution_request.execution_mode == "r3_one_epoch_continuation"


def test_activate_stops_stale_rights_before_journal_and_host() -> None:
    snapshot = _snapshot()
    root = _Composition(snapshot.intent)
    entrypoint = ProductionTrainingApplicationEntrypoint(
        _Authority(snapshot, stale_on_recheck=True), _Factory(root)
    )
    with pytest.raises(TrainingError, match="TRAINING_CURRENT_EVIDENCE_STALE"):
        entrypoint.activate(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert root.activations == 0
    root.journal_write.assert_not_called()
    root.host_run.assert_not_called()


def test_activation_plan_fingerprint_is_deterministic() -> None:
    first = _entrypoint()[0].dry_run(
        ProductionTrainingApplicationCommand(INTENT_ID, SOURCE)
    )
    second = _entrypoint()[0].dry_run(
        ProductionTrainingApplicationCommand(INTENT_ID, SOURCE)
    )
    assert first.plan == second.plan
    assert first.plan.plan_fingerprint == second.plan.plan_fingerprint


def test_host_projection_mismatch_fails_closed() -> None:
    snapshot = _snapshot()
    mismatched = _record(_submission(output_logical_root="production/runs/other"))
    root = _Composition(mismatched)
    entrypoint = ProductionTrainingApplicationEntrypoint(
        _Authority(snapshot), _Factory(root)
    )
    with pytest.raises(TrainingError, match="TRAINING_APPLICATION_HOST_INCOMPATIBLE"):
        entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert root.shutdowns == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"binding": None}, "TRAINING_INTENT_DECISION_MISSING"),
        ({"submitter_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"dataset_version_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"dataset_manifest_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"dataset_pair_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"config_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"readiness_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"decision_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"issuer_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"approver_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
        ({"current_evidence_current": False}, "TRAINING_INTENT_AUTHORITY_STALE"),
    ],
)
def test_entrypoint_reuses_fail_closed_foundation(
    changes: dict[str, object], code: str
) -> None:
    snapshot = _snapshot(**changes)
    entrypoint, root = _entrypoint(snapshot)
    with pytest.raises(TrainingError, match=code):
        entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert root.prepares == root.shutdowns == 0


def test_denied_and_source_mismatch_fail_before_composition() -> None:
    record = _record()
    denied = _snapshot(
        intent=record,
        binding=_binding(record, TrainingExecutionIssuerDecisionValue.DENIED),
    )
    entrypoint, root = _entrypoint(denied)
    with pytest.raises(TrainingError, match="TRAINING_INTENT_DECISION_DENIED"):
        entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    with pytest.raises(TrainingError, match="TRAINING_INTENT_BINDING_MISMATCH"):
        _entrypoint()[0].dry_run(
            ProductionTrainingApplicationCommand(INTENT_ID, "b" * 40)
        )
    assert root.prepares == 0


@pytest.mark.parametrize(
    "code",
    [
        "TRAINING_APPLICATION_RUN_COLLISION",
        "TRAINING_APPLICATION_OUTPUT_UNAVAILABLE",
        "TRAINING_APPLICATION_CONTINUATION_MISMATCH",
        "TRAINING_APPLICATION_COMPOSITION_UNAVAILABLE",
    ],
)
def test_read_only_preflight_failure_categories_are_stable(code: str) -> None:
    entrypoint, root = _entrypoint(failure=code)
    with pytest.raises(TrainingError, match=code):
        entrypoint.dry_run(ProductionTrainingApplicationCommand(INTENT_ID, SOURCE))
    assert root.shutdowns == 1


def test_command_has_no_training_override_or_transport_surface() -> None:
    assert tuple(ProductionTrainingApplicationCommand.__dataclass_fields__) == (
        "intent_id",
        "expected_source_commit",
        "schema_version",
    )
    source = Path("src/training/production_training_application.py").read_text(
        encoding="utf-8"
    )
    assert "argparse" not in source
    assert "FastAPI" not in source
    assert "websocket" not in source
    assert "http" not in source.lower()


def _configuration() -> _PostgresTrainingCompositionConfiguration:
    return _PostgresTrainingCompositionConfiguration(
        provider="postgresql",
        environment="isolated_test",
        host="127.0.0.1",
        port=5432,
        database="dohalm_application_contract",
        resolver_password="resolver-only",
        journal_password="journal-only",
        application_name="dohalm-application",
        process_boundary_id="process:application-1",
        decision_authority_id=DECISION_ID,
        prerequisite_policy_reference="policy:prerequisite-1",
        decision_policy_reference="policy:decision-1",
        activation_authority_reference="activation:application-1",
        activation_evidence_reference="evidence:application-1",
        connect_timeout_seconds=5,
        statement_timeout_ms=15_000,
        transaction_timeout_ms=30_000,
        sslmode="disable",
        sslrootcert=None,
    )


def test_c3_real_intent_prepare_is_read_only_and_host_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    binding = _binding(record)
    snapshot = _snapshot(intent=record, binding=binding)
    from src.training.production_intent_authority import validate_intent_for_execution

    validated = validate_intent_for_execution(INTENT_ID, SOURCE, _Authority(snapshot))
    root = _compose_postgres_training_host(_configuration())
    resolved = SimpleNamespace(
        dataset_version_id=record.submission.dataset_version_id,
        dataset_manifest_id=record.submission.dataset_manifest_id,
        dataset_pair_authority_id=PAIR_ID,
        dataset_pair_fingerprint=record.submission.dataset_pair_fingerprint,
        config_fingerprint=record.submission.config_fingerprint,
        readiness_fingerprint=record.submission.readiness_fingerprint,
        source_commit=SOURCE,
        provenance=SimpleNamespace(
            resolution_policy_reference="policy:prerequisite-1",
            evaluated_at=TIMESTAMP,
        ),
    )
    decision = ResolvedTrainingExecutionDecision(
        decision=binding.decision,
        authorization_id=binding.authorization_id,
        issuer_id=binding.issuer_id,
        approver_reference=binding.approver_reference,
        evidence_reference=binding.evidence_reference,
        request_fingerprint=binding.request_fingerprint,
        issued_at=TIMESTAMP,
    )
    provenance = TrustedDecisionProvenance(
        source_identity="decision-source-1",
        policy_reference="policy:decision-1",
        decision_authority_id=DECISION_ID,
        issuer_authority_id=ISSUER_ID,
        approver_authority_id=APPROVER_ID,
        bound_authorization_id=binding.authorization_id,
        bound_issuer_id=binding.issuer_id,
        bound_approver_reference=binding.approver_reference,
        bound_evidence_reference=binding.evidence_reference,
        issuer_current=True,
        approver_current=True,
        current=True,
    )
    monkeypatch.setattr(
        composition, "_resolve_training_prerequisites", lambda *_: resolved
    )
    monkeypatch.setattr(
        composition,
        "_build_training_execution_request_from_prerequisites",
        lambda *_: validated.execution_request,
    )
    monkeypatch.setattr(composition, "_output_available", lambda *_: True)
    monkeypatch.setattr(composition, "_continuation_verified", lambda *_: True)
    monkeypatch.setattr(
        composition,
        "_resolve_trusted_training_decision_resolution",
        lambda *_: TrustedDecisionResolution(decision, provenance),
    )
    monkeypatch.setattr(root._journal, "read", lambda _run_id: None)
    monkeypatch.setattr(root._prerequisite_resolver, "release", lambda _resolved: None)
    monkeypatch.setattr(root._prerequisite_resolver, "close", lambda: None)
    monkeypatch.setattr(
        composition,
        "_bootstrap_production_full_pretraining_host",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Host bootstrap")),
    )
    try:
        readiness = root.prepare_activation(validated)
        assert readiness.execution_request == validated.execution_request
        assert readiness.host_intent.run_id == record.submission.requested_run_id
        assert readiness.mutation_count == 0
        assert root._host is None
    finally:
        root.shutdown()


def test_c3_requested_run_collision_fails_without_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    snapshot = _snapshot(intent=record, binding=_binding(record))
    from src.training.production_intent_authority import validate_intent_for_execution

    validated = validate_intent_for_execution(INTENT_ID, SOURCE, _Authority(snapshot))
    root = _compose_postgres_training_host(_configuration())
    resolved = SimpleNamespace()
    monkeypatch.setattr(
        composition, "_resolve_training_prerequisites", lambda *_: resolved
    )
    monkeypatch.setattr(
        composition,
        "_build_training_execution_request_from_prerequisites",
        lambda *_: validated.execution_request,
    )
    monkeypatch.setattr(root._journal, "read", lambda _run_id: object())
    monkeypatch.setattr(root._prerequisite_resolver, "release", lambda _resolved: None)
    monkeypatch.setattr(root._prerequisite_resolver, "close", lambda: None)
    claim = Mock()
    transition = Mock()
    monkeypatch.setattr(root._journal, "claim", claim)
    monkeypatch.setattr(root._journal, "transition", transition)
    with pytest.raises(TrainingError, match="TRAINING_APPLICATION_RUN_COLLISION"):
        root.prepare_activation(validated)
    claim.assert_not_called()
    transition.assert_not_called()
