from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.data.checksums import checksum_value
from src.training.errors import TrainingError
from src.training.execution_issuer import TrainingExecutionIssuerDecisionValue
from src.training.postgres_training_intent_authority import (
    PostgresTrainingIntentAuthority,
)
from src.training.production_intent_authority import (
    ProductionTrainingIntentSubmissionService,
    TrainingIntentContinuation,
    TrainingIntentDecisionBinding,
    TrainingIntentMode,
    TrainingIntentRecord,
    TrainingIntentSubmission,
    TrainingIntentSubmitOutcome,
    TrainingIntentSubmitterAuthorityRecord,
    TrainingIntentValidationSnapshot,
    project_training_execution_request,
    training_intent_fingerprint,
    validate_intent_for_execution,
)


SUBMITTER_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
VERSION_AUTHORITY_ID = "33333333-3333-4333-8333-333333333333"
MANIFEST_AUTHORITY_ID = "44444444-4444-4444-8444-444444444444"
PAIR_AUTHORITY_ID = "55555555-5555-4555-8555-555555555555"
CONFIG_AUTHORITY_ID = "66666666-6666-4666-8666-666666666666"
READINESS_AUTHORITY_ID = "77777777-7777-4777-8777-777777777777"
DECISION_AUTHORITY_ID = "88888888-8888-4888-8888-888888888888"
ISSUER_AUTHORITY_ID = "99999999-9999-4999-8999-999999999999"
APPROVER_AUTHORITY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
SOURCE_COMMIT = "a" * 40
PAIR_FINGERPRINT = "sha256:" + "1" * 64
CONFIG_FINGERPRINT = "sha256:" + "2" * 64
READINESS_FINGERPRINT = "sha256:" + "3" * 64


def _submission(**changes: object) -> TrainingIntentSubmission:
    values: dict[str, object] = {
        "client_request_id": "client-request-0001",
        "requested_run_id": "production-run-0001",
        "execution_mode": TrainingIntentMode.FRESH,
        "dataset_version_authority_id": VERSION_AUTHORITY_ID,
        "dataset_manifest_authority_id": MANIFEST_AUTHORITY_ID,
        "dataset_pair_authority_id": PAIR_AUTHORITY_ID,
        "dataset_version_id": "dataset-version-0001",
        "dataset_manifest_id": "dataset-manifest-0001",
        "dataset_pair_fingerprint": PAIR_FINGERPRINT,
        "config_authority_id": CONFIG_AUTHORITY_ID,
        "config_fingerprint": CONFIG_FINGERPRINT,
        "readiness_authority_id": READINESS_AUTHORITY_ID,
        "readiness_fingerprint": READINESS_FINGERPRINT,
        "source_commit": SOURCE_COMMIT,
        "output_logical_root": "production/runs/run-0001",
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
    record: TrainingIntentRecord | None = None,
    *,
    decision: TrainingExecutionIssuerDecisionValue = TrainingExecutionIssuerDecisionValue.APPROVED,
) -> TrainingIntentDecisionBinding:
    actual = record or _record()
    request = project_training_execution_request(actual)
    return TrainingIntentDecisionBinding(
        intent_id=actual.intent_id,
        decision_authority_id=DECISION_AUTHORITY_ID,
        decision=decision,
        authorization_id="authorization-0001",
        issuer_authority_id=ISSUER_AUTHORITY_ID,
        issuer_id="issuer-0001",
        approver_authority_id=APPROVER_AUTHORITY_ID,
        approver_reference="approver-0001",
        evidence_reference="decision:11111111-1111-4111-8111-111111111111",
        request_fingerprint=request.request_fingerprint,
        bound_at=NOW,
    )


def test_decision_binding_rejects_same_issuer_and_approver_authority() -> None:
    with pytest.raises(TrainingError, match="TRAINING_INTENT_DECISION_BINDING_INVALID"):
        replace(_binding(), approver_authority_id=ISSUER_AUTHORITY_ID)


@pytest.mark.parametrize("role", ("issuer", "approver"))
def test_execution_validation_rejects_submitter_role_collision(role: str) -> None:
    record = _record()
    binding = _binding(record)
    if role == "issuer":
        binding = replace(binding, issuer_authority_id=SUBMITTER_ID)
    else:
        binding = replace(binding, approver_authority_id=SUBMITTER_ID)
    authority = _SnapshotAuthority(_snapshot(intent=record, binding=binding))
    with pytest.raises(TrainingError, match="TRAINING_INTENT_AUTHORITY_ROLE_COLLISION"):
        validate_intent_for_execution(INTENT_ID, SOURCE_COMMIT, authority)


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
    }
    values.update(changes)
    return TrainingIntentValidationSnapshot(**values)  # type: ignore[arg-type]


class _SnapshotAuthority:
    def __init__(self, snapshot: TrainingIntentValidationSnapshot) -> None:
        self.snapshot = snapshot
        self.reads = 0

    def read_validation_snapshot(
        self, intent_id: str
    ) -> TrainingIntentValidationSnapshot:
        assert intent_id == self.snapshot.intent.intent_id
        self.reads += 1
        return self.snapshot


class _RoleOnlyFactory:
    def __init__(self, role: str) -> None:
        self.role = role


def test_postgres_adapter_requires_exact_separated_roles() -> None:
    adapter = PostgresTrainingIntentAuthority(
        producer=_RoleOnlyFactory("dohalm_training_authority_producer"),  # type: ignore[arg-type]
        writer=_RoleOnlyFactory("dohalm_training_intent_writer"),  # type: ignore[arg-type]
        resolver=_RoleOnlyFactory("dohalm_training_resolver"),  # type: ignore[arg-type]
    )
    assert repr(adapter) == "PostgresTrainingIntentAuthority(<redacted>)"
    with pytest.raises(
        TrainingError, match="TRAINING_INTENT_AUTHORITY_CONFIGURATION_INVALID"
    ):
        PostgresTrainingIntentAuthority(
            producer=_RoleOnlyFactory("dohalm_training_runtime"),  # type: ignore[arg-type]
            writer=_RoleOnlyFactory("dohalm_training_intent_writer"),  # type: ignore[arg-type]
            resolver=_RoleOnlyFactory("dohalm_training_resolver"),  # type: ignore[arg-type]
        )


def test_fresh_intent_fingerprint_and_projection_are_canonical() -> None:
    submission = _submission()
    record = _record(submission)
    assert training_intent_fingerprint(SUBMITTER_ID, submission) == (
        "sha256:4971b3c103b5864a2295c770c1181a13726a1156dcd53d1bee3ce0fa3c7b90ea"
    )
    request = project_training_execution_request(record)
    values = {
        "schema_version": request.schema_version,
        "action": request.action,
        "dataset_version_id": request.dataset_version_id,
        "dataset_manifest_id": request.dataset_manifest_id,
        "dataset_pair_fingerprint": request.dataset_pair_fingerprint,
        "config_fingerprint": request.config_fingerprint,
        "readiness_fingerprint": request.readiness_fingerprint,
        "run_id": request.run_id,
        "output_logical_root": request.output_logical_root,
        "source_commit": request.source_commit,
        "execution_mode": request.execution_mode,
    }
    assert len(values) == 11
    assert request.request_fingerprint == checksum_value(values)
    assert request.run_id == submission.requested_run_id
    assert record.intent_id != request.run_id


def test_fingerprint_excludes_client_request_and_created_time() -> None:
    first = _submission(client_request_id="client-request-a")
    second = replace(first, client_request_id="client-request-b")
    assert training_intent_fingerprint(
        SUBMITTER_ID, first
    ) == training_intent_fingerprint(SUBMITTER_ID, second)


@pytest.mark.parametrize(
    "changed",
    [
        {"dataset_version_id": "dataset-version-changed"},
        {"config_fingerprint": "sha256:" + "9" * 64},
        {"readiness_fingerprint": "sha256:" + "8" * 64},
        {"requested_run_id": "production-run-changed"},
        {"source_commit": "b" * 40},
        {"output_logical_root": "production/runs/changed"},
        {
            "execution_mode": TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION,
            "continuation": TrainingIntentContinuation(
                predecessor_run_id="run-r2",
                checkpoint_reference="checkpoint-r2",
                source_step=4_883,
                target_cumulative_steps=29_934,
            ),
        },
        {"dataset_pair_fingerprint": "sha256:" + "7" * 64},
    ],
)
def test_each_idempotency_conflict_field_changes_fingerprint(
    changed: dict[str, object],
) -> None:
    original = _submission(client_request_id="same-client-key")
    conflicting = _submission(client_request_id="same-client-key", **changed)
    assert training_intent_fingerprint(
        SUBMITTER_ID, original
    ) != training_intent_fingerprint(SUBMITTER_ID, conflicting)


def test_mode_and_path_contracts_fail_closed() -> None:
    continuation = TrainingIntentContinuation(
        predecessor_run_id="run-aihub-71748-local-v1-r3",
        checkpoint_reference="checkpoint-4883",
        source_step=4_883,
        target_cumulative_steps=29_934,
    )
    continued = _submission(
        execution_mode=TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION,
        continuation=continuation,
    )
    assert continued.continuation == continuation
    invalid = (
        {"continuation": continuation},
        {
            "execution_mode": TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION,
            "continuation": None,
        },
        {"source_commit": "A" * 40},
        {"output_logical_root": "../outside"},
        {"output_logical_root": "C:/outside"},
        {"output_logical_root": "/absolute"},
        {"output_logical_root": "production/run with space"},
    )
    for changes in invalid:
        with pytest.raises(TrainingError, match="TRAINING_INTENT_SUBMISSION_INVALID"):
            _submission(**changes)


def test_local_selector_is_construction_bound() -> None:
    submitter = TrainingIntentSubmitterAuthorityRecord(
        authority_id=SUBMITTER_ID,
        domain_key="local-operator-primary",
        state="current",
        state_effective_at=NOW,
        created_at=NOW,
        valid_from=NOW,
        valid_until=None,
        projection_version=1,
    )

    class Submitters:
        def resolve_current(self, authority_id: str):
            assert authority_id == SUBMITTER_ID
            return submitter

    class Intents:
        def submit(self, resolved, submission):
            assert resolved is submitter
            return TrainingIntentSubmitOutcome.CREATED, _record(submission)

    service = ProductionTrainingIntentSubmissionService(
        SUBMITTER_ID, Submitters(), Intents()
    )
    outcome, record = service.submit(_submission())
    assert outcome is TrainingIntentSubmitOutcome.CREATED
    assert record.submitter_authority_id == SUBMITTER_ID


def test_validate_only_approved_intent_stops_before_runtime() -> None:
    authority = _SnapshotAuthority(_snapshot())
    host_run = Mock()
    backend = Mock()
    checkpoint_writer = Mock()
    artifact_writer = Mock()
    validated = validate_intent_for_execution(INTENT_ID, SOURCE_COMMIT, authority)
    assert validated.execution_request.run_id == "production-run-0001"
    assert validated.binding.decision is TrainingExecutionIssuerDecisionValue.APPROVED
    assert authority.reads == 1
    host_run.assert_not_called()
    backend.assert_not_called()
    checkpoint_writer.assert_not_called()
    artifact_writer.assert_not_called()


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (_snapshot(binding=None), "TRAINING_INTENT_DECISION_MISSING"),
        (
            _snapshot(
                binding=_binding(decision=TrainingExecutionIssuerDecisionValue.DENIED)
            ),
            "TRAINING_INTENT_DECISION_DENIED",
        ),
        (_snapshot(submitter_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(dataset_version_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(dataset_manifest_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(dataset_pair_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(config_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(readiness_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(decision_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(issuer_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
        (_snapshot(approver_current=False), "TRAINING_INTENT_AUTHORITY_STALE"),
    ],
)
def test_validate_only_rejects_missing_denied_and_stale_authority(
    snapshot: TrainingIntentValidationSnapshot, code: str
) -> None:
    with pytest.raises(TrainingError, match=code):
        validate_intent_for_execution(
            INTENT_ID, SOURCE_COMMIT, _SnapshotAuthority(snapshot)
        )


def test_validate_only_rejects_source_and_binding_mismatch() -> None:
    with pytest.raises(TrainingError, match="TRAINING_INTENT_BINDING_MISMATCH"):
        validate_intent_for_execution(
            INTENT_ID, "b" * 40, _SnapshotAuthority(_snapshot())
        )
    record = _record()
    mismatched = replace(_binding(record), request_fingerprint="sha256:" + "f" * 64)
    with pytest.raises(TrainingError, match="TRAINING_INTENT_BINDING_MISMATCH"):
        validate_intent_for_execution(
            INTENT_ID,
            SOURCE_COMMIT,
            _SnapshotAuthority(_snapshot(intent=record, binding=mismatched)),
        )


def test_durable_models_are_redacted_and_have_no_capability_field() -> None:
    record = _record()
    binding = _binding(record)
    assert repr(record) == "TrainingIntentRecord(<redacted>)"
    assert repr(binding) == "TrainingIntentDecisionBinding(<redacted>)"
    assert "capability" not in record.__dataclass_fields__
    assert "capability" not in binding.__dataclass_fields__
    forbidden = {"password", "dsn", "token", "secret", "capability"}
    assert forbidden.isdisjoint(record.submission.__dataclass_fields__)


def test_required_ci_classifiers_cover_intent_foundation_paths() -> None:
    expected = (
        "src/training/production_intent_authority.py",
        "src/training/postgres_training_intent_authority.py",
        "src/postgres_migrations/*",
        "tests/test_training_intent_authority.py",
    )
    root = Path(__file__).resolve().parents[1]
    for relative in (
        ".github/workflows/c1-postgres-contract.yml",
        ".github/workflows/c2-postgres-training-adapters.yml",
        ".github/workflows/local-training-activation.yml",
    ):
        workflow = (root / relative).read_text(encoding="utf-8")
        assert all(path in workflow for path in expected), relative
