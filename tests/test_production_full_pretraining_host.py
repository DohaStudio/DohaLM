from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.training import production_full_pretraining_host as host_module
from src.training import production_host_foundation as foundation
from src.training import production_orchestration_seams as seams
from src.training.dataset_training_entry import DatasetTrainingPermission
from src.training.errors import TrainingError
from src.training.execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
)
from src.training.execution_issuer import TrainingExecutionIssuerDecisionValue
from src.training.production_full_pretraining_host import (
    ProductionFullPretrainingHost,
    ProductionTrainingHostResult,
)
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    ResolvedTrainingExecutionDecision,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationClaimResult,
    TrainingOrchestrationClaimStatus,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrustedDecisionProvenance,
    TrustedDecisionResolution,
)

PAIR = "sha256:" + "1" * 64
CONFIG = "sha256:" + "2" * 64
READINESS = "sha256:" + "3" * 64
REQUEST = "sha256:" + "4" * 64
SOURCE = "5" * 40
MANIFEST_CHECKSUM = "sha256:" + "6" * 64
PROCESS_BOUNDARY_ID = "process-boundary-1"
DECISION_AUTHORITY_ID = "99999999-9999-4999-8999-999999999999"
DATASET_VERSION_AUTHORITY_ID = "11111111-1111-4111-8111-111111111111"
DATASET_MANIFEST_AUTHORITY_ID = "22222222-2222-4222-8222-222222222222"
DATASET_PAIR_AUTHORITY_ID = "33333333-3333-4333-8333-333333333333"
CONFIG_AUTHORITY_ID = "44444444-4444-4444-8444-444444444444"
READINESS_AUTHORITY_ID = "55555555-5555-4555-8555-555555555555"


def _intent() -> ProductionTrainingHostIntent:
    return ProductionTrainingHostIntent(
        action="full_pretraining",
        execution_mode="fresh",
        dataset_version_reference=f"dataset-version:{DATASET_VERSION_AUTHORITY_ID}",
        dataset_manifest_reference=f"dataset-manifest:{DATASET_MANIFEST_AUTHORITY_ID}",
        expected_dataset_pair_fingerprint=PAIR,
        training_config_reference=f"config:{CONFIG_AUTHORITY_ID}",
        expected_config_fingerprint=CONFIG,
        readiness_evidence_reference=f"readiness:{READINESS_AUTHORITY_ID}",
        expected_readiness_fingerprint=READINESS,
        run_id="run-1",
        output_logical_root="experiments/run-1",
        decision_evidence_reference="decision-ref",
    )


def _claim_request() -> TrainingOrchestrationClaimRequest:
    intent = _intent()
    return TrainingOrchestrationClaimRequest(
        identity=TrainingOrchestrationIdentity(
            run_id=intent.run_id, request_fingerprint=REQUEST
        ),
        intent_fingerprint=seams._canonical_training_host_intent_fingerprint(intent),
        orchestration_correlation_id=intent.run_id,
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        dataset_pair_fingerprint=PAIR,
        config_fingerprint=CONFIG,
        readiness_fingerprint=READINESS,
        source_commit=SOURCE,
        prerequisite_policy_reference="prerequisite-policy-1",
        process_boundary_id=PROCESS_BOUNDARY_ID,
    )


def _permission() -> DatasetTrainingPermission:
    return DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        pair_fingerprint=PAIR,
    )


def _report() -> dict[str, object]:
    return {
        "execution_allowed": True,
        "blocking_codes": [],
        "readiness_fingerprint": READINESS,
        "source_commit": SOURCE,
        "source_worktree_clean": True,
        "nested": {"values": [1, "two"]},
    }


class _Config:
    resume_checkpoint = None
    output_dir = "experiments/run-1"

    def to_dict(self) -> dict[str, object]:
        return {"output_dir": self.output_dir, "nested": {"values": [1, 2]}}


class _PrerequisiteResolver:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.error: BaseException | None = None

    def resolve(self, request):
        self.calls += 1
        assert type(request.intent) is ProductionTrainingHostIntent
        assert (
            request.intent_fingerprint
            == seams._canonical_training_host_intent_fingerprint(request.intent)
        )
        if self.error is not None:
            raise self.error
        return self.result


class _DecisionResolver:
    def __init__(self) -> None:
        self.calls = 0
        self.error: BaseException | None = None
        self.decision = TrainingExecutionIssuerDecisionValue.APPROVED
        self.request_fingerprint = REQUEST
        self.authorization_id = "authorization-1"

    def resolve(self, request):
        self.calls += 1
        assert request.decision_authority_id == DECISION_AUTHORITY_ID
        if self.error is not None:
            raise self.error
        decision = ResolvedTrainingExecutionDecision(
            decision=self.decision,
            authorization_id=self.authorization_id,
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference=request.intent.decision_evidence_reference,
            request_fingerprint=self.request_fingerprint,
            issued_at="2026-08-13T12:00:00+09:00",
        )
        return TrustedDecisionResolution(
            decision=decision,
            provenance=TrustedDecisionProvenance(
                source_identity="decision-store-1",
                policy_reference="decision-policy-1",
                decision_authority_id=DECISION_AUTHORITY_ID,
                issuer_authority_id="77777777-7777-4777-8777-777777777777",
                approver_authority_id="88888888-8888-4888-8888-888888888888",
                bound_authorization_id=decision.authorization_id,
                bound_issuer_id=decision.issuer_id,
                bound_approver_reference=decision.approver_reference,
                bound_evidence_reference=decision.evidence_reference,
                issuer_current=True,
                approver_current=True,
                current=True,
            ),
        )


class _Journal:
    def __init__(self) -> None:
        self.records: dict[str, TrainingOrchestrationRecord] = {}
        self.transitions: list[TrainingOrchestrationPhase] = []
        self.claim_calls = 0
        self.fail_at: TrainingOrchestrationPhase | None = None
        self.lock = threading.RLock()

    def claim(self, request):
        with self.lock:
            self.claim_calls += 1
            identity = request.identity
            current = self.records.get(identity.run_id)
            if current is None:
                current = TrainingOrchestrationRecord(
                    claim=request,
                    phase=TrainingOrchestrationPhase.CLAIMED,
                    journal_version=1,
                    reservation_group_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
                self.records[identity.run_id] = current
                status = TrainingOrchestrationClaimStatus.ACQUIRED
            elif current.claim != request:
                raise TrainingError(
                    "TRAINING_HOST_JOURNAL_CONFLICT",
                    "conflict",
                )
            else:
                status = TrainingOrchestrationClaimStatus.REPLAY
            return TrainingOrchestrationClaimResult(status=status, record=current)

    def read(self, run_id):
        with self.lock:
            return self.records.get(run_id)

    def transition(self, transition):
        with self.lock:
            if transition.next_phase is self.fail_at:
                self.fail_at = None
                raise OSError("D:\\private\\journal")
            current = self.records.get(transition.identity.run_id)
            if current is None:
                raise TrainingError("TRAINING_HOST_JOURNAL_CONFLICT", "conflict")
            updated = foundation._next_journal_record(current, transition)
            self.records[transition.identity.run_id] = updated
            self.transitions.append(updated.phase)
            return updated


class _Context:
    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.intent = _intent()
        self.permission = _permission()
        self.config_path = (tmp_path / "authority" / "config.yaml").resolve()
        self.manifest_path = (tmp_path / "authority" / "manifest.yaml").resolve()
        self.resolved = seams.ResolvedTrainingPrerequisites(
            schema_version=1,
            intent_fingerprint=seams._canonical_training_host_intent_fingerprint(
                self.intent
            ),
            dataset_version_reference=self.intent.dataset_version_reference,
            dataset_manifest_reference=self.intent.dataset_manifest_reference,
            training_config_reference=self.intent.training_config_reference,
            readiness_evidence_reference=self.intent.readiness_evidence_reference,
            dataset_version_authority_id=DATASET_VERSION_AUTHORITY_ID,
            dataset_manifest_authority_id=DATASET_MANIFEST_AUTHORITY_ID,
            dataset_pair_authority_id=DATASET_PAIR_AUTHORITY_ID,
            config_authority_id=CONFIG_AUTHORITY_ID,
            readiness_authority_id=READINESS_AUTHORITY_ID,
            config_path=self.config_path,
            config_snapshot=_Config().to_dict(),
            manifest_path=self.manifest_path,
            readiness_report=_report(),
            dataset_permission=self.permission,
            dataset_version_id=self.permission.dataset_version_id,
            dataset_manifest_id=self.permission.dataset_manifest_id,
            dataset_pair_fingerprint=self.permission.pair_fingerprint,
            config_fingerprint=CONFIG,
            readiness_fingerprint=READINESS,
            source_commit=SOURCE,
            run_id=self.intent.run_id,
            output_logical_root=self.intent.output_logical_root,
            provenance=seams.TrustedPrerequisiteProvenance(
                dataset_source_identity="dataset-store-1",
                config_source_identity="config-store-1",
                readiness_source_identity="readiness-store-1",
                resolution_policy_reference="prerequisite-policy-1",
                evaluated_at="2026-08-13T12:00:00+09:00",
                current=True,
            ),
        )
        self.prerequisite_resolver = _PrerequisiteResolver(self.resolved)
        self.decision_resolver = _DecisionResolver()
        self.journal = _Journal()
        self.request = TrainingExecutionRequest(
            schema_version=1,
            action="full_pretraining",
            dataset_version_id=self.permission.dataset_version_id,
            dataset_manifest_id=self.permission.dataset_manifest_id,
            dataset_pair_fingerprint=PAIR,
            config_fingerprint=CONFIG,
            readiness_fingerprint=READINESS,
            run_id="run-1",
            output_logical_root="experiments/run-1",
            source_commit=SOURCE,
            execution_mode="fresh",
            request_fingerprint=REQUEST,
        )
        self.execution_approval = TrainingExecutionApproval(
            authorization_id="authorization-1",
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference="decision-ref",
            request_fingerprint=REQUEST,
            issued_at="2026-08-13T12:00:00+09:00",
        )
        self.builder_calls = 0
        self.approval_calls = 0
        self.backend_calls = 0
        self.consume_calls = 0
        self.entry_calls = 0
        self.backend_mode = "success"
        self.backend_barrier: threading.Barrier | None = None
        self.backend_runner = self.backend

        monkeypatch.setattr(
            seams,
            "require_dataset_training_activation",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            seams,
            "file_checksum",
            lambda path: CONFIG if path == self.config_path else MANIFEST_CHECKSUM,
        )
        monkeypatch.setattr(
            seams.FullPretrainingConfig,
            "from_yaml",
            lambda _path: _Config(),
        )
        monkeypatch.setattr(
            seams,
            "inspect_full_pretraining_readiness",
            lambda *_args: _report(),
        )
        monkeypatch.setattr(
            seams,
            "require_full_pretraining_technical_readiness",
            lambda _value: None,
        )
        monkeypatch.setattr(
            seams,
            "resolve_full_pretraining_path",
            lambda *_args: Path("D:/authority/experiments/run-1"),
        )
        monkeypatch.setattr(seams, "_verified_source", lambda _commit: None)

        def build(*_args, **_kwargs):
            self.builder_calls += 1
            return self.request

        monkeypatch.setattr(seams, "build_training_execution_request", build)

        def issue(request):
            assert request is self.request
            self.approval_calls += 1
            return self.execution_approval

        monkeypatch.setattr(host_module, "issue_training_execution_approval", issue)

    def backend(
        self, lifecycle, config_path, manifest_path, readiness_report, **kwargs
    ):
        self.backend_calls += 1
        assert config_path == self.config_path
        assert manifest_path == self.manifest_path
        assert type(readiness_report) is dict
        assert type(readiness_report["nested"]) is dict
        assert kwargs["execution_request"] is self.request
        assert kwargs["execution_approval"] is self.execution_approval
        if self.backend_barrier is not None:
            self.backend_barrier.wait()
        if self.backend_mode == "raw-error":
            lifecycle._approval_was_consumed()
            self.consume_calls += 1
            lifecycle._backend_was_entered()
            self.entry_calls += 1
            raise RuntimeError("D:\\private\\backend")
        if self.backend_mode == "base-error":
            raise KeyboardInterrupt()
        if self.backend_mode == "malformed":
            return object()
        lifecycle._approval_was_consumed()
        self.consume_calls += 1
        if self.backend_mode == "entry-failure":
            return lifecycle._finish_failure("SYNTHETIC_ENTRY_FAILURE")
        lifecycle._backend_was_entered()
        self.entry_calls += 1
        if self.backend_mode == "failure":
            return lifecycle._finish_failure("SYNTHETIC_BACKEND_FAILURE")
        if self.backend_mode == "unknown":
            return lifecycle._finish_unknown("TRAINING_BACKEND_OUTCOME_UNKNOWN")
        return lifecycle._finish_success()

    def bootstrap(self) -> ProductionFullPretrainingHost:
        binding = host_module._bind_fake_host_backend_for_tests(self.backend_runner)
        return host_module._bootstrap_production_full_pretraining_host(
            self.prerequisite_resolver,
            self.decision_resolver,
            self.journal,
            process_boundary_id=PROCESS_BOUNDARY_ID,
            decision_authority_id=DECISION_AUTHORITY_ID,
            backend_binding=binding,
        )


@pytest.fixture(autouse=True)
def _isolated_process_registration(monkeypatch):
    import src.training.execution_issuer as issuer

    monkeypatch.setattr(host_module, "_BOOTSTRAP_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_ADAPTER_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_SUBMISSION_BINDINGS", {})
    monkeypatch.setattr(issuer, "_DECISION_PROVENANCE", {})
    monkeypatch.setattr(issuer, "_DECISION_REPLAY_KEYS", set())


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> _Context:
    return _Context(tmp_path, monkeypatch)


def test_import_and_public_construction_have_zero_registration_side_effects() -> None:
    import src.training as package
    import src.training.execution_approval as approval
    import src.training.execution_issuer as issuer

    assert issuer._ADAPTER_REGISTRATION is None
    assert issuer._SUBMISSION_BINDINGS == {}
    assert approval._REQUEST_REGISTRY == {}
    assert approval._APPROVAL_REGISTRY == {}
    assert host_module._BOOTSTRAP_REGISTRATION is None
    with pytest.raises(TrainingError, match="TRAINING_HOST_CONSTRUCTION_UNAUTHORIZED"):
        ProductionFullPretrainingHost()
    assert package.ProductionFullPretrainingHost is ProductionFullPretrainingHost
    assert package.ProductionTrainingHostResult is ProductionTrainingHostResult


def test_bootstrap_is_exact_once_and_identical_replay_returns_same_host(
    context: _Context,
) -> None:
    binding = host_module._bind_fake_host_backend_for_tests(context.backend_runner)
    first = host_module._bootstrap_production_full_pretraining_host(
        context.prerequisite_resolver,
        context.decision_resolver,
        context.journal,
        process_boundary_id=PROCESS_BOUNDARY_ID,
        decision_authority_id=DECISION_AUTHORITY_ID,
        backend_binding=binding,
    )
    second_binding = host_module._bind_fake_host_backend_for_tests(
        context.backend_runner
    )
    replay = host_module._bootstrap_production_full_pretraining_host(
        context.prerequisite_resolver,
        context.decision_resolver,
        context.journal,
        process_boundary_id=PROCESS_BOUNDARY_ID,
        decision_authority_id=DECISION_AUTHORITY_ID,
        backend_binding=second_binding,
    )
    assert replay is first


@pytest.mark.parametrize(
    "dependency",
    ("prerequisite", "decision", "journal", "backend", "decision_authority"),
)
def test_bootstrap_rejects_dependency_replacement_without_partial_mutation(
    context: _Context, dependency: str
) -> None:
    host = context.bootstrap()
    prerequisite = context.prerequisite_resolver
    decision = context.decision_resolver
    journal = context.journal
    decision_authority_id = DECISION_AUTHORITY_ID
    binding = host_module._bind_fake_host_backend_for_tests(context.backend_runner)
    if dependency == "prerequisite":
        prerequisite = _PrerequisiteResolver(context.resolved)
    elif dependency == "decision":
        decision = _DecisionResolver()
    elif dependency == "journal":
        journal = _Journal()
    elif dependency == "backend":
        binding = host_module._bind_fake_host_backend_for_tests(lambda *_a, **_k: None)
    else:
        decision_authority_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with pytest.raises(TrainingError, match="TRAINING_HOST_BOOTSTRAP_CONFLICT"):
        host_module._bootstrap_production_full_pretraining_host(
            prerequisite,
            decision,
            journal,
            process_boundary_id=PROCESS_BOUNDARY_ID,
            decision_authority_id=decision_authority_id,
            backend_binding=binding,
        )
    assert host_module._BOOTSTRAP_REGISTRATION.host is host


def test_concurrent_bootstrap_has_one_host_and_one_issuer_composition(
    context: _Context, monkeypatch
) -> None:
    calls = 0
    original = host_module._compose_production_training_execution_issuer

    def compose():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        host_module, "_compose_production_training_execution_issuer", compose
    )
    binding = host_module._bind_fake_host_backend_for_tests(context.backend_runner)

    def bootstrap(_item):
        return host_module._bootstrap_production_full_pretraining_host(
            context.prerequisite_resolver,
            context.decision_resolver,
            context.journal,
            process_boundary_id=PROCESS_BOUNDARY_ID,
            decision_authority_id=DECISION_AUTHORITY_ID,
            backend_binding=binding,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(bootstrap, range(8)))
    assert len({id(result) for result in results}) == 1
    assert calls == 1


def test_bootstrap_failure_publishes_no_partial_host(
    context: _Context, monkeypatch
) -> None:
    monkeypatch.setattr(
        host_module,
        "_compose_production_training_execution_issuer",
        lambda: (_ for _ in ()).throw(RuntimeError("raw-bootstrap")),
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_BOOTSTRAP_FAILED") as caught:
        context.bootstrap()
    assert "raw-bootstrap" not in str(caught.value)
    assert host_module._BOOTSTRAP_REGISTRATION is None


@pytest.mark.parametrize(
    "value", (None, object(), SimpleNamespace(action="full_pretraining"))
)
def test_invalid_intent_has_zero_dependency_calls(
    context: _Context, value: object
) -> None:
    host = context.bootstrap()
    with pytest.raises(TrainingError, match="TRAINING_HOST_INTENT_INVALID"):
        host.run(value)  # type: ignore[arg-type]
    assert context.prerequisite_resolver.calls == 0
    assert context.builder_calls == 0
    assert context.decision_resolver.calls == 0
    assert context.journal.claim_calls == 0
    assert context.backend_calls == 0


@pytest.mark.parametrize("result", (None, object(), SimpleNamespace(schema_version=1)))
def test_invalid_prerequisite_has_zero_downstream_calls(
    context: _Context, result: object
) -> None:
    context.prerequisite_resolver.result = result
    host = context.bootstrap()
    with pytest.raises(TrainingError, match="TRAINING_HOST_PREREQUISITE_INVALID"):
        host.run(context.intent)
    assert context.prerequisite_resolver.calls == 1
    assert context.builder_calls == 0
    assert context.decision_resolver.calls == 0
    assert context.journal.claim_calls == 0
    assert context.backend_calls == 0


def test_approved_orchestration_has_exact_order_and_no_input_mutation(
    context: _Context,
) -> None:
    host = context.bootstrap()
    intent_snapshot = tuple(
        getattr(context.intent, item.name) for item in fields(context.intent)
    )
    permission_snapshot = context.permission.__dict__.copy()
    result = host.run(context.intent)
    assert result.phase is TrainingOrchestrationPhase.COMPLETED
    assert result.backend_entered is True
    assert result.reconciliation_required is False
    assert result.replayed is False
    assert context.prerequisite_resolver.calls == 1
    assert context.builder_calls == 1
    assert context.decision_resolver.calls == 1
    assert context.backend_calls == 1
    assert context.approval_calls == 1
    assert context.consume_calls == context.entry_calls == 1
    assert context.journal.transitions == [
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
        TrainingOrchestrationPhase.DECISION_SUBMITTED,
        TrainingOrchestrationPhase.APPROVAL_CONSUMED,
        TrainingOrchestrationPhase.BACKEND_ENTERED,
        TrainingOrchestrationPhase.COMPLETED,
    ]
    assert (
        tuple(getattr(context.intent, item.name) for item in fields(context.intent))
        == intent_snapshot
    )
    assert context.permission.__dict__ == permission_snapshot
    assert repr(result) == "ProductionTrainingHostResult(<redacted>)"


def test_denied_decision_prevents_journal_claim_and_backend(
    context: _Context,
) -> None:
    context.decision_resolver.decision = TrainingExecutionIssuerDecisionValue.DENIED
    host = context.bootstrap()
    result = host.run(context.intent)
    assert result.phase is TrainingOrchestrationPhase.FAILED
    assert result.reason_code == "TRAINING_EXECUTION_APPROVAL_DENIED"
    assert result.backend_entered is False
    assert context.backend_calls == context.consume_calls == context.entry_calls == 0
    assert context.journal.claim_calls == 0
    assert context.journal.transitions == []


@pytest.mark.parametrize(
    "error",
    (
        RuntimeError("D:\\private\\decision"),
        ValueError("sensitive-decision-detail"),
    ),
)
def test_decision_unavailable_is_sanitized_and_never_calls_backend(
    context: _Context, error: Exception
) -> None:
    context.decision_resolver.error = error
    host = context.bootstrap()
    with pytest.raises(TrainingError) as caught:
        host.run(context.intent)
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_UNAVAILABLE"
    assert str(error) not in str(caught.value)
    assert context.backend_calls == 0
    assert context.approval_calls == 0
    assert context.journal.claim_calls == 0
    assert context.journal.transitions == []


def test_decision_request_mismatch_never_submits_or_calls_backend(
    context: _Context,
) -> None:
    context.decision_resolver.request_fingerprint = "sha256:" + "9" * 64
    host = context.bootstrap()
    with pytest.raises(
        TrainingError, match="TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"
    ):
        host.run(context.intent)
    assert context.backend_calls == 0
    assert context.journal.claim_calls == 0
    assert context.journal.transitions == []


def test_same_identity_replay_never_resubmits_or_reenters_backend(
    context: _Context,
) -> None:
    host = context.bootstrap()
    first = host.run(context.intent)
    replay = host.run(context.intent)
    assert first.phase is replay.phase is TrainingOrchestrationPhase.COMPLETED
    assert replay.replayed is True
    assert context.backend_calls == 1
    assert context.decision_resolver.calls == 1
    assert context.prerequisite_resolver.calls == 2
    assert context.builder_calls == 2


def test_same_run_different_request_fingerprint_is_conflict(context: _Context) -> None:
    host = context.bootstrap()
    host.run(context.intent)
    context.request = TrainingExecutionRequest(
        **{
            **context.request.__dict__,
            "request_fingerprint": "sha256:" + "9" * 64,
        }
    )
    context.decision_resolver.request_fingerprint = context.request.request_fingerprint
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
        host.run(context.intent)
    assert context.backend_calls == 1
    assert context.decision_resolver.calls == 1


def test_concurrent_identical_calls_have_one_backend_winner(context: _Context) -> None:
    host = context.bootstrap()
    context.backend_barrier = threading.Barrier(2)

    def release_backend():
        context.backend_barrier.wait()

    releaser = threading.Thread(target=release_backend)
    releaser.start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _item: host.run(context.intent), range(8)))
    releaser.join()
    assert context.backend_calls == context.consume_calls == context.entry_calls == 1
    assert sum(result.replayed is False for result in results) == 1
    assert sum(result.replayed is True for result in results) == 7


def test_submission_cas_failure_is_manual_and_never_calls_backend(
    context: _Context,
) -> None:
    context.journal.fail_at = TrainingOrchestrationPhase.DECISION_SUBMITTED
    host = context.bootstrap()
    result = host.run(context.intent)
    assert result.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    assert result.reconciliation_required is True
    assert context.backend_calls == 0
    assert (
        context.journal.transitions[-1]
        is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    )


def test_capability_issuance_failure_is_terminal_before_backend(
    context: _Context, monkeypatch
) -> None:
    monkeypatch.setattr(
        host_module,
        "issue_training_execution_approval",
        lambda _request: (_ for _ in ()).throw(
            TrainingError("TRAINING_EXECUTION_DECISION_REPLAYED", "redacted")
        ),
    )
    host = context.bootstrap()
    with pytest.raises(TrainingError) as caught:
        host.run(context.intent)
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_REPLAYED"
    assert context.backend_calls == 0
    assert context.journal.transitions[-2:] == [
        TrainingOrchestrationPhase.DECISION_SUBMITTED,
        TrainingOrchestrationPhase.FAILED,
    ]
    record = context.journal.read(context.intent.run_id)
    assert record is not None
    assert record.reason_code == "TRAINING_EXECUTION_DECISION_REPLAYED"


@pytest.mark.parametrize(
    ("mode", "phase", "consumed", "entered"),
    (
        ("entry-failure", TrainingOrchestrationPhase.FAILED, 1, 0),
        ("failure", TrainingOrchestrationPhase.FAILED, 1, 1),
        ("unknown", TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED, 1, 1),
        ("raw-error", TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED, 1, 1),
        ("malformed", TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED, 0, 0),
    ),
)
def test_backend_failure_and_unknown_matrix(
    context: _Context,
    mode: str,
    phase: TrainingOrchestrationPhase,
    consumed: int,
    entered: int,
) -> None:
    context.backend_mode = mode
    host = context.bootstrap()
    result = host.run(context.intent)
    assert result.phase is phase
    assert context.backend_calls == 1
    assert context.consume_calls == consumed
    assert context.entry_calls == entered
    assert "private" not in repr(result)


def test_backend_base_exception_is_not_swallowed(context: _Context) -> None:
    context.backend_mode = "base-error"
    host = context.bootstrap()
    with pytest.raises(KeyboardInterrupt):
        host.run(context.intent)
    assert context.backend_calls == 1


@pytest.mark.parametrize(
    "phase",
    (
        TrainingOrchestrationPhase.CLAIMED,
        TrainingOrchestrationPhase.RESOLVED,
        TrainingOrchestrationPhase.VALIDATED,
        TrainingOrchestrationPhase.DECISION_SUBMITTED,
        TrainingOrchestrationPhase.APPROVAL_CONSUMED,
        TrainingOrchestrationPhase.BACKEND_ENTERED,
    ),
)
def test_restart_active_record_requires_manual_reconciliation(
    context: _Context, phase: TrainingOrchestrationPhase
) -> None:
    identity = TrainingOrchestrationIdentity(
        run_id="run-1", request_fingerprint=REQUEST
    )
    context.journal.records[identity.run_id] = TrainingOrchestrationRecord(
        claim=_claim_request(),
        phase=phase,
        journal_version=1,
        reservation_group_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        authorization_id=(
            "authorization-1"
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        issuer_id=(
            "issuer-1"
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        approver_reference=(
            "approver-1"
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        evidence_reference=(
            "decision-ref"
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        decision_policy_reference=(
            "decision-policy-1"
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        authorization_fingerprint=(
            "sha256:" + "7" * 64
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        decision_evidence_fingerprint=(
            "sha256:" + "8" * 64
            if phase
            in {
                TrainingOrchestrationPhase.DECISION_SUBMITTED,
                TrainingOrchestrationPhase.APPROVAL_CONSUMED,
                TrainingOrchestrationPhase.BACKEND_ENTERED,
            }
            else None
        ),
        backend_entered=phase is TrainingOrchestrationPhase.BACKEND_ENTERED,
    )
    host = context.bootstrap()
    result = host.run(context.intent)
    assert result.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    assert result.reconciliation_required is True
    assert context.decision_resolver.calls == 0
    assert context.backend_calls == 0


def test_public_surface_accepts_only_intent_and_exposes_no_authority() -> None:
    parameters = inspect.signature(ProductionFullPretrainingHost.run).parameters
    assert tuple(parameters) == ("self", "intent")
    assert host_module.__all__ == [
        "ProductionFullPretrainingHost",
        "ProductionTrainingHostResult",
    ]
    assert {
        "config_path",
        "readiness_report",
        "dataset_permission",
        "resolver",
        "journal",
        "backend",
        "callback",
        "approval",
        "capability",
        "decision_source",
    }.isdisjoint(parameters)
    assert {item.name for item in fields(ProductionTrainingHostResult)} == {
        "identity",
        "phase",
        "backend_entered",
        "reconciliation_required",
        "replayed",
        "reason_code",
    }
    with pytest.raises(FrozenInstanceError):
        result = ProductionTrainingHostResult(
            identity=TrainingOrchestrationIdentity(
                run_id="run-1", request_fingerprint=REQUEST
            ),
            phase=TrainingOrchestrationPhase.FAILED,
            backend_entered=False,
            reconciliation_required=False,
            replayed=False,
            reason_code="FAILED",
        )
        result.phase = TrainingOrchestrationPhase.COMPLETED  # type: ignore[misc]
