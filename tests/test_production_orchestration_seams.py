from __future__ import annotations

import inspect
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src.training import full_pretraining_backend as backend
from src.training import production_host_foundation as foundation
from src.training import production_orchestration_seams as seams
from src.training.dataset_training_entry import (
    DatasetTrainingPermission,
    evaluate_dataset_training_entry,
    require_dataset_training_activation,
)
from src.training.errors import TrainingError
from src.training.execution_approval import TrainingExecutionRequest
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
)


PAIR = "sha256:" + "1" * 64
CONFIG = "sha256:" + "2" * 64
READINESS = "sha256:" + "3" * 64
READINESS_EVIDENCE = "sha256:" + "8" * 64
SOURCE = "4" * 40
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


def _permission() -> DatasetTrainingPermission:
    return DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        pair_fingerprint=PAIR,
    )


def _issued_permission(tmp_path: Path) -> DatasetTrainingPermission:
    fixture_path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location(
        "_seam_publication_fixtures", fixture_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("publication fixtures unavailable")
    fixtures = importlib.util.module_from_spec(spec)
    assert isinstance(fixtures, ModuleType)
    spec.loader.exec_module(fixtures)
    published = fixtures.publish(tmp_path / "synthetic-publication")
    manifest = published.dataset_manifest
    return evaluate_dataset_training_entry(
        published.dataset_version,
        manifest,
        upstream_objects=fixtures.upstream(),
        evaluated_at="2026-08-11T12:00:00Z",
        readiness_report={
            "execution_allowed": True,
            "inspection_only": True,
            "training_started": False,
            "blocking_codes": [],
        },
        expected_split_id=manifest["split_id"],
        artifact_references=manifest["object_file_artifact_refs"],
    )


def _report() -> dict[str, object]:
    return {
        "execution_allowed": True,
        "blocking_codes": [],
        "readiness_fingerprint": READINESS_EVIDENCE,
        "source_commit": SOURCE,
        "source_worktree_clean": True,
        "nested": {"values": [1, "two", True, None]},
    }


class _Config:
    resume_checkpoint = None
    output_dir = "experiments/run-1"

    def to_dict(self) -> dict[str, object]:
        return {"output_dir": self.output_dir, "nested": {"values": [1, 2]}}


def _resolved(
    tmp_path: Path,
    *,
    config_snapshot: dict[str, object] | None = None,
    readiness_report: dict[str, object] | None = None,
) -> seams.ResolvedTrainingPrerequisites:
    config = _Config()
    return seams.ResolvedTrainingPrerequisites(
        schema_version=1,
        intent_fingerprint=seams._canonical_training_host_intent_fingerprint(_intent()),
        dataset_version_reference=f"dataset-version:{DATASET_VERSION_AUTHORITY_ID}",
        dataset_manifest_reference=f"dataset-manifest:{DATASET_MANIFEST_AUTHORITY_ID}",
        training_config_reference=f"config:{CONFIG_AUTHORITY_ID}",
        readiness_evidence_reference=f"readiness:{READINESS_AUTHORITY_ID}",
        dataset_version_authority_id=DATASET_VERSION_AUTHORITY_ID,
        dataset_manifest_authority_id=DATASET_MANIFEST_AUTHORITY_ID,
        dataset_pair_authority_id=DATASET_PAIR_AUTHORITY_ID,
        config_authority_id=CONFIG_AUTHORITY_ID,
        readiness_authority_id=READINESS_AUTHORITY_ID,
        config_path=(tmp_path / "config.yaml").resolve(),
        config_snapshot=config.to_dict()
        if config_snapshot is None
        else config_snapshot,
        manifest_path=(tmp_path / "manifest.yaml").resolve(),
        readiness_report=_report() if readiness_report is None else readiness_report,
        dataset_permission=_permission(),
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        dataset_pair_fingerprint=PAIR,
        config_fingerprint=CONFIG,
        readiness_fingerprint=READINESS,
        source_commit=SOURCE,
        run_id="run-1",
        output_logical_root="experiments/run-1",
        provenance=seams.TrustedPrerequisiteProvenance(
            dataset_source_identity="dataset-store-1",
            config_source_identity="config-store-1",
            readiness_source_identity="readiness-store-1",
            resolution_policy_reference="policy-1",
            evaluated_at="2026-08-13T09:00:00+09:00",
            current=True,
        ),
    )


def _patch_prerequisite_inspection(
    monkeypatch, resolved, *, exact_permission: bool = False
) -> list[str]:
    calls: list[str] = []
    config = _Config()

    def permission_check(*args, **kwargs):
        calls.append("permission")
        if exact_permission:
            require_dataset_training_activation(*args, **kwargs)

    monkeypatch.setattr(seams, "require_dataset_training_activation", permission_check)
    monkeypatch.setattr(
        seams,
        "file_checksum",
        lambda path: CONFIG if path == resolved.config_path else "sha256:" + "9" * 64,
    )
    monkeypatch.setattr(seams.FullPretrainingConfig, "from_yaml", lambda _path: config)
    monkeypatch.setattr(
        seams,
        "inspect_full_pretraining_readiness",
        lambda *_a: _report(),
    )
    monkeypatch.setattr(
        seams,
        "require_full_pretraining_technical_readiness",
        lambda _report: calls.append("readiness"),
    )
    monkeypatch.setattr(
        seams,
        "resolve_full_pretraining_path",
        lambda *_a: Path("D:/authority/experiments/run-1"),
    )
    monkeypatch.setattr(
        seams, "_verified_source", lambda _commit: calls.append("source")
    )
    return calls


class _Resolver:
    def __init__(self, result=None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def resolve(self, request):
        self.calls += 1
        assert request.intent is _INTENT
        assert (
            request.intent_fingerprint
            == seams._canonical_training_host_intent_fingerprint(request.intent)
        )
        if self.error is not None:
            raise self.error
        return self.result


_INTENT = _intent()


def test_exact_prerequisite_result_is_deeply_immutable_and_redacted(
    tmp_path: Path,
) -> None:
    config_snapshot = {"output_dir": "experiments/run-1", "nested": {"values": [1, 2]}}
    readiness = _report()
    resolved = _resolved(
        tmp_path,
        config_snapshot=config_snapshot,
        readiness_report=readiness,
    )
    config_snapshot["nested"]["values"].append(3)  # type: ignore[index,union-attr]
    readiness["nested"]["values"].append("changed")  # type: ignore[index,union-attr]
    assert resolved.config_snapshot["nested"]["values"] == (1, 2)  # type: ignore[index]
    assert resolved.readiness_report["nested"]["values"] == (1, "two", True, None)  # type: ignore[index]
    with pytest.raises(TypeError):
        resolved.config_snapshot["new"] = "forged"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        resolved.run_id = "forged"  # type: ignore[misc]
    assert repr(resolved) == "ResolvedTrainingPrerequisites(<redacted>)"
    assert "D:\\" not in repr(resolved)
    assert {
        "dataset_version_authority_id",
        "dataset_manifest_authority_id",
        "dataset_pair_authority_id",
        "config_authority_id",
        "readiness_authority_id",
        "dataset_pair_fingerprint",
        "config_fingerprint",
        "readiness_fingerprint",
        "source_commit",
        "provenance",
    } <= {item.name for item in fields(resolved)}


def test_stale_provenance_fails_before_authority_inspection(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = _resolved(tmp_path)
    object.__setattr__(resolved.provenance, "current", False)
    calls = _patch_prerequisite_inspection(monkeypatch, resolved)
    with pytest.raises(TrainingError, match="TRAINING_HOST_PREREQUISITE_INVALID"):
        seams._validate_training_prerequisites(_INTENT, resolved)
    assert calls == []


def test_malformed_exact_result_fails_closed(tmp_path: Path, monkeypatch) -> None:
    resolved = _resolved(tmp_path)
    object.__setattr__(resolved, "readiness_report", object())
    calls = _patch_prerequisite_inspection(monkeypatch, resolved)
    with pytest.raises(TrainingError, match="TRAINING_HOST_PREREQUISITE_INVALID"):
        seams._validate_training_prerequisites(_INTENT, resolved)
    assert calls == ["permission", "readiness"]


@pytest.mark.parametrize("result", [None, object(), SimpleNamespace(schema_version=1)])
def test_resolver_rejects_missing_arbitrary_and_duck_results(
    tmp_path: Path, monkeypatch, result: object
) -> None:
    resolved = _resolved(tmp_path)
    _patch_prerequisite_inspection(monkeypatch, resolved)
    resolver = _Resolver(result)
    with pytest.raises(TrainingError) as caught:
        seams._resolve_training_prerequisites(resolver, _INTENT)
    assert caught.value.code == "TRAINING_HOST_PREREQUISITE_INVALID"


@pytest.mark.parametrize(
    "error", [RuntimeError("D:\\private\\payload"), ValueError("secret-token")]
)
def test_resolver_exception_is_sanitized(
    tmp_path: Path, monkeypatch, error: Exception
) -> None:
    resolved = _resolved(tmp_path)
    _patch_prerequisite_inspection(monkeypatch, resolved)
    with pytest.raises(TrainingError) as caught:
        seams._resolve_training_prerequisites(_Resolver(error=error), _INTENT)
    assert caught.value.code == "TRAINING_HOST_PREREQUISITE_UNAVAILABLE"
    assert str(error) not in str(caught.value)
    assert type(error).__name__ not in str(caught.value)


def test_resolver_does_not_swallow_base_exception(tmp_path: Path, monkeypatch) -> None:
    resolved = _resolved(tmp_path)
    _patch_prerequisite_inspection(monkeypatch, resolved)
    with pytest.raises(KeyboardInterrupt):
        seams._resolve_training_prerequisites(
            _Resolver(error=KeyboardInterrupt()), _INTENT
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("intent_fingerprint", "sha256:" + "8" * 64),
        ("dataset_version_reference", "wrong-ref"),
        ("dataset_manifest_reference", "wrong-ref"),
        ("run_id", "wrong-run"),
        ("dataset_pair_fingerprint", "sha256:" + "8" * 64),
        ("config_fingerprint", "sha256:" + "8" * 64),
        ("readiness_fingerprint", "sha256:" + "8" * 64),
    ),
)
def test_prerequisite_binding_mismatch_has_zero_inspection_side_effects(
    tmp_path: Path, monkeypatch, field: str, value: str
) -> None:
    resolved = _resolved(tmp_path)
    object.__setattr__(resolved, field, value)
    calls = _patch_prerequisite_inspection(monkeypatch, resolved)
    with pytest.raises(TrainingError, match="TRAINING_HOST_PREREQUISITE_INVALID"):
        seams._validate_training_prerequisites(_INTENT, resolved)
    assert calls == []


def test_forged_permission_fails_before_request_builder(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = _resolved(tmp_path)
    monkeypatch.setattr(seams, "file_checksum", lambda _path: CONFIG)
    calls: list[str] = []
    monkeypatch.setattr(
        seams,
        "build_training_execution_request",
        lambda *_a, **_k: calls.append("builder"),
    )
    with pytest.raises(TrainingError, match="TRAINING_HOST_PREREQUISITE_INVALID"):
        seams._build_training_execution_request_from_prerequisites(_INTENT, resolved)
    assert calls == []


def test_validated_result_uses_canonical_builder_once_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = _resolved(tmp_path)
    object.__setattr__(resolved, "dataset_permission", _issued_permission(tmp_path))
    object.__setattr__(
        resolved, "dataset_version_id", resolved.dataset_permission.dataset_version_id
    )
    object.__setattr__(
        resolved, "dataset_manifest_id", resolved.dataset_permission.dataset_manifest_id
    )
    object.__setattr__(
        resolved,
        "dataset_pair_fingerprint",
        resolved.dataset_permission.pair_fingerprint,
    )
    intent = _intent()
    object.__setattr__(
        intent, "expected_dataset_pair_fingerprint", resolved.dataset_pair_fingerprint
    )
    object.__setattr__(
        resolved,
        "intent_fingerprint",
        seams._canonical_training_host_intent_fingerprint(intent),
    )
    calls = _patch_prerequisite_inspection(monkeypatch, resolved, exact_permission=True)
    permission_snapshot = resolved.dataset_permission.__dict__.copy()
    request = TrainingExecutionRequest(
        schema_version=1,
        action="full_pretraining",
        dataset_version_id=resolved.dataset_version_id,
        dataset_manifest_id=resolved.dataset_manifest_id,
        dataset_pair_fingerprint=resolved.dataset_pair_fingerprint,
        config_fingerprint=CONFIG,
        readiness_fingerprint=READINESS,
        run_id="run-1",
        output_logical_root="experiments/run-1",
        source_commit=SOURCE,
        execution_mode="fresh",
        request_fingerprint="sha256:" + "5" * 64,
    )
    builder_calls: list[tuple[object, ...]] = []

    def build(*args, **kwargs):
        builder_calls.append((args, kwargs))
        return request

    monkeypatch.setattr(seams, "build_training_execution_request", build)
    assert (
        seams._build_training_execution_request_from_prerequisites(intent, resolved)
        is request
    )
    assert len(builder_calls) == 1
    assert calls == ["permission", "readiness", "source"]
    assert resolved.dataset_permission.__dict__ == permission_snapshot


class _Journal:
    def __init__(self, identity: TrainingOrchestrationIdentity) -> None:
        self.record = TrainingOrchestrationRecord(
            claim=TrainingOrchestrationClaimRequest(
                identity=identity,
                intent_fingerprint="sha256:" + "7" * 64,
                orchestration_correlation_id=identity.run_id,
                dataset_version_id="dataset-version-1",
                dataset_manifest_id="dataset-manifest-1",
                dataset_pair_fingerprint=PAIR,
                config_fingerprint=CONFIG,
                readiness_fingerprint=READINESS,
                source_commit=SOURCE,
                prerequisite_policy_reference="policy-1",
                process_boundary_id="process-boundary-1",
            ),
            phase=TrainingOrchestrationPhase.DECISION_SUBMITTED,
            journal_version=4,
            reservation_group_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            authorization_id="authorization-1",
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference="decision-ref",
            decision_policy_reference="policy-1",
            authorization_fingerprint="sha256:" + "8" * 64,
            decision_evidence_fingerprint="sha256:" + "9" * 64,
        )
        self.transitions: list[TrainingOrchestrationPhase] = []
        self.fail_once_at: TrainingOrchestrationPhase | None = None
        self.lock = threading.Lock()

    def read(self, run_id: str):
        return self.record if run_id == self.record.identity.run_id else None

    def transition(self, transition):
        with self.lock:
            if transition.next_phase is self.fail_once_at:
                self.fail_once_at = None
                raise OSError("D:\\private\\journal")
            self.record = foundation._next_journal_record(self.record, transition)
            self.transitions.append(transition.next_phase)
            return self.record


def _lifecycle():
    identity = TrainingOrchestrationIdentity(
        run_id="run-1", request_fingerprint="sha256:" + "6" * 64
    )
    journal = _Journal(identity)
    return seams._HostFullPretrainingBackendLifecycle(journal, identity), journal


def _run_lifecycle(lifecycle):
    return seams._run_host_full_pretraining(
        lifecycle,
        Path("config"),
        Path("manifest"),
        {},
        dataset_permission=_permission(),
        dataset_version_id="dataset-version-1",
        dataset_manifest_id="dataset-manifest-1",
        dataset_pair_fingerprint=PAIR,
        execution_request=TrainingExecutionRequest(
            1,
            "full_pretraining",
            "dataset-version-1",
            "dataset-manifest-1",
            PAIR,
            CONFIG,
            READINESS,
            "run-1",
            "experiments/run-1",
            SOURCE,
            "fresh",
            "sha256:" + "6" * 64,
        ),
    )


def test_lifecycle_success_orders_consume_entry_terminal_once(monkeypatch) -> None:
    lifecycle, journal = _lifecycle()
    calls: list[str] = []

    def execute(*_args, _lifecycle, **_kwargs):
        calls.append("issue-consume")
        _lifecycle._approval_was_consumed()
        calls.append("entry")
        _lifecycle._backend_was_entered()
        calls.append("body")
        return {"raw": "not exposed"}

    monkeypatch.setattr(backend, "_run_full_pretraining", execute)
    result = _run_lifecycle(lifecycle)
    assert result.outcome is seams._FullPretrainingLifecycleOutcome.SUCCEEDED
    assert result.approval_consumed is result.backend_entered is True
    assert result.terminal_recorded is True and result.reason_code is None
    assert calls == ["issue-consume", "entry", "body"]
    assert journal.transitions == [
        TrainingOrchestrationPhase.APPROVAL_CONSUMED,
        TrainingOrchestrationPhase.BACKEND_ENTERED,
        TrainingOrchestrationPhase.COMPLETED,
    ]
    assert {item.name for item in fields(result)} == {
        "identity",
        "outcome",
        "approval_consumed",
        "backend_entered",
        "terminal_recorded",
        "reason_code",
    }


@pytest.mark.parametrize(
    ("kind", "expected", "consumed", "entered"),
    (
        ("denied", seams._FullPretrainingLifecycleOutcome.FAILED, False, False),
        ("consume", seams._FullPretrainingLifecycleOutcome.FAILED, False, False),
        ("entry", seams._FullPretrainingLifecycleOutcome.FAILED, True, False),
        ("body", seams._FullPretrainingLifecycleOutcome.FAILED, True, True),
        ("unknown", seams._FullPretrainingLifecycleOutcome.OUTCOME_UNKNOWN, True, True),
    ),
)
def test_lifecycle_failure_matrix(
    monkeypatch, kind: str, expected, consumed: bool, entered: bool
) -> None:
    lifecycle, journal = _lifecycle()
    calls = {"backend": 0, "consume": 0, "entry": 0}

    def execute(*_args, _lifecycle, **_kwargs):
        calls["backend"] += 1
        if kind in {"denied", "consume"}:
            raise TrainingError("TRAINING_EXECUTION_APPROVAL_DENIED", "raw-secret")
        _lifecycle._approval_was_consumed()
        calls["consume"] += 1
        if kind == "entry":
            raise TrainingError("SYNTHETIC_ENTRY_FAILED", "raw-path")
        _lifecycle._backend_was_entered()
        calls["entry"] += 1
        if kind == "body":
            raise TrainingError("SYNTHETIC_BODY_FAILED", "raw-payload")
        raise RuntimeError("D:\\private\\backend")

    monkeypatch.setattr(backend, "_run_full_pretraining", execute)
    result = _run_lifecycle(lifecycle)
    assert result.outcome is expected
    assert result.approval_consumed is consumed
    assert result.backend_entered is entered
    assert calls["backend"] == 1
    assert calls["consume"] == int(consumed)
    assert calls["entry"] == int(entered)
    assert "raw" not in repr(result) and "D:\\" not in repr(result)
    assert journal.record.phase in {
        TrainingOrchestrationPhase.FAILED,
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
    }


def test_lifecycle_journal_failure_is_unknown_without_backend_reentry(
    monkeypatch,
) -> None:
    lifecycle, journal = _lifecycle()
    journal.fail_once_at = TrainingOrchestrationPhase.APPROVAL_CONSUMED
    calls = 0

    def execute(*_args, _lifecycle, **_kwargs):
        nonlocal calls
        calls += 1
        _lifecycle._approval_was_consumed()

    monkeypatch.setattr(backend, "_run_full_pretraining", execute)
    result = _run_lifecycle(lifecycle)
    assert result.outcome is seams._FullPretrainingLifecycleOutcome.OUTCOME_UNKNOWN
    assert result.approval_consumed is True
    assert result.backend_entered is False
    assert calls == 1
    assert (
        journal.record.phase
        is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    )


def test_success_terminal_write_failure_never_returns_success(monkeypatch) -> None:
    lifecycle, journal = _lifecycle()
    journal.fail_once_at = TrainingOrchestrationPhase.COMPLETED

    def execute(*_args, _lifecycle, **_kwargs):
        _lifecycle._approval_was_consumed()
        _lifecycle._backend_was_entered()

    monkeypatch.setattr(backend, "_run_full_pretraining", execute)
    result = _run_lifecycle(lifecycle)
    assert result.outcome is seams._FullPretrainingLifecycleOutcome.OUTCOME_UNKNOWN
    assert result.approval_consumed is result.backend_entered is True
    assert result.terminal_recorded is True
    assert (
        journal.record.phase
        is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED
    )


def test_lifecycle_replay_and_concurrency_have_single_backend_winner(
    monkeypatch,
) -> None:
    lifecycle, _journal = _lifecycle()
    calls = 0
    lock = threading.Lock()

    def execute(*_args, _lifecycle, **_kwargs):
        nonlocal calls
        with lock:
            calls += 1
        _lifecycle._approval_was_consumed()
        _lifecycle._backend_was_entered()

    monkeypatch.setattr(backend, "_run_full_pretraining", execute)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _item: _run_lifecycle(lifecycle), range(8)))
    assert calls == 1
    assert (
        sum(
            result.outcome is seams._FullPretrainingLifecycleOutcome.SUCCEEDED
            for result in results
        )
        == 1
    )
    assert (
        sum(
            result.reason_code == "TRAINING_HOST_LIFECYCLE_REPLAY" for result in results
        )
        == 7
    )


def test_lifecycle_does_not_swallow_base_exception(monkeypatch) -> None:
    lifecycle, journal = _lifecycle()
    monkeypatch.setattr(
        backend,
        "_run_full_pretraining",
        lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        _run_lifecycle(lifecycle)
    assert journal.transitions == []


def test_public_surface_does_not_expose_resolver_lifecycle_or_injection() -> None:
    assert seams.__all__ == []
    parameters = inspect.signature(backend.run_full_pretraining).parameters
    assert "_lifecycle" not in parameters
    assert {
        "journal",
        "observer",
        "callback",
        "decision_source",
        "execution_approval",
    }.isdisjoint(parameters)
    assert not hasattr(seams._FullPretrainingLifecycleResult, "approval")
    assert not hasattr(seams._FullPretrainingLifecycleResult, "capability")
