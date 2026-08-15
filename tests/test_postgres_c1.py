from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from src.postgres_c1 import C1PostgresError, C1PostgresSettings, load_c1_migrations
from src.training.dataset_training_entry import DatasetTrainingPermission
from src.training.errors import TrainingError
from src.training.postgres_training_adapters import (
    _CLAIM_JOURNAL_COLUMN_MAP,
    _PostgresTrainingConnectionFactory,
    _PostgresTrainingConnectionSettings,
    _PostgresTrainingDecisionResolver,
    _PostgresTrainingExecutionJournal,
    _PostgresTrainingPrerequisiteResolver,
    _map_journal_error,
)
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationTransition,
)
from src.training.production_orchestration_seams import (
    TrainingPrerequisiteResolutionRequest,
)


def _settings(**overrides: object) -> C1PostgresSettings:
    values: dict[str, object] = {
        "environment": "local_ephemeral",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "dohalm_c1_contract",
        "user": "dohalm_c1_admin",
        "password": "synthetic-password-only",
    }
    values.update(overrides)
    return C1PostgresSettings(**values)  # type: ignore[arg-type]


def test_settings_are_explicitly_c1_only_and_redacted() -> None:
    settings = _settings()
    assert repr(settings) == "C1PostgresSettings(<redacted>)"
    assert settings.password not in repr(settings)

    invalid = (
        {"environment": "production"},
        {"host": "database.example.com"},
        {"database": "training"},
        {"user": "postgres"},
        {"password": "short"},
        {"port": 0},
    )
    for overrides in invalid:
        with pytest.raises(C1PostgresError, match="C1_POSTGRES_SETTINGS_INVALID"):
            _settings(**overrides)


def test_migrations_are_ordered_utf8_and_content_addressed() -> None:
    migrations = load_c1_migrations()
    assert [migration.version for migration in migrations] == list(
        range(1, len(migrations) + 1)
    )
    assert all(len(migration.sha256) == 64 for migration in migrations)
    assert all(migration.sql.strip() for migration in migrations)


def test_migration_loader_rejects_an_empty_sequence() -> None:
    with pytest.raises(C1PostgresError, match="C1_POSTGRES_MIGRATION_CONFLICT"):
        load_c1_migrations(Path("tests/fixtures/no-c1-migrations"))


def test_c1_1_authoritative_mapping_is_synthetic_and_exact() -> None:
    fixture = json.loads(
        Path("tests/fixtures/c1_1_authority_mapping.json").read_text(encoding="utf-8")
    )
    assert set(fixture) == {
        "schema_version",
        "fixture_kind",
        "synthetic_only",
        "producer",
        "resolver",
        "journal",
        "mappings",
    }
    assert fixture["fixture_kind"] == "c1_1_authoritative_mapping"
    assert fixture["synthetic_only"] is True
    assert fixture["producer"] == {
        "database_role": "dohalm_training_authority_producer",
        "persisted_domain_identifier": "training_authority_producer",
        "workflow": "immutable-row-insert-then-restricted-event-append",
    }
    assert fixture["resolver"] == {
        "database_role": "dohalm_training_resolver",
        "transaction_isolation": "repeatable_read",
        "transaction_access": "read_only",
    }
    assert fixture["journal"] == {
        "database_role": "dohalm_training_journal",
        "transaction_isolation": "read_committed",
        "ambiguous_outcome": "manual_reconciliation_required",
    }
    assert set(fixture["mappings"]) == {"config", "readiness"}
    assert (
        fixture["mappings"]["readiness"]["config_mapping"]
        == fixture["mappings"]["config"]["reference"]
    )


def test_c1_2_c2_mapping_and_restricted_sql_are_complete() -> None:
    fixture = json.loads(
        Path("tests/fixtures/c1_2_c2_authority_mapping.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["schema_version"] == 1
    assert fixture["synthetic_only"] is True
    assert set(fixture["canonical_producers"]) == {
        "run_id",
        "request_fingerprint",
        "intent_fingerprint",
        "orchestration_correlation_id",
        "dataset_version_authority_id",
        "dataset_manifest_authority_id",
        "dataset_pair_authority_id",
        "dataset_pair_fingerprint",
        "config_fingerprint",
        "readiness_fingerprint",
        "source_commit",
        "prerequisite_policy_reference",
        "decision_authority_id",
        "authorization_state",
        "issuer_authority_id",
        "approver_authority_id",
        "process_boundary_id",
        "journal_phase",
        "journal_version",
        "reservation_group_id",
    }
    assert fixture["forbidden"] == {
        "hidden_mutable_context": False,
        "direct_table_sql": False,
        "adapter_generated_authority_id": False,
        "adapter_generated_fingerprint": False,
    }
    migrations = load_c1_migrations()
    assert [migration.name for migration in migrations] == [
        "0001_training_authority_and_journal.sql",
        "0002_c1_1_prerequisite_restricted_operations.sql",
        "0003_c1_2_c2_typed_snapshot_and_journal_contracts.sql",
    ]
    sql = migrations[-1].sql
    for function_name in (
        "read_c2_training_prerequisite_snapshot",
        "read_c2_training_decision_snapshot",
        "claim_c2_training_execution_journal",
        "transition_c2_training_execution_journal",
        "read_c2_training_execution_journal",
    ):
        assert f"CREATE FUNCTION dohalm_training_v1.{function_name}" in sql
        assert f"REVOKE ALL ON FUNCTION dohalm_training_v1.{function_name}" in sql
    assert "REPEATABLE READ" not in sql
    assert "repeatable read" in sql
    assert "read committed" in sql


class _C2Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.description = (
            tuple(SimpleNamespace(name=name) for name in rows[0])
            if rows
            else (SimpleNamespace(name="empty_result"),)
        )

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [tuple(row.values()) for row in self._rows]


class _C2Connection:
    def __init__(self, rows: list[dict[str, Any]] | BaseException) -> None:
        self._rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> _C2Cursor:
        self.calls.append((sql, params))
        if isinstance(self._rows, BaseException):
            raise self._rows
        return _C2Cursor(self._rows)


class _C2Factory:
    def __init__(self, role: str, rows: list[dict[str, Any]] | BaseException) -> None:
        self.role = role
        self.connection = _C2Connection(rows)
        self.boundaries: list[tuple[str, bool]] = []

    @contextmanager
    def transaction(self, *, isolation: str, read_only: bool):
        self.boundaries.append((isolation, read_only))
        yield self.connection


def _c2_intent() -> ProductionTrainingHostIntent:
    return ProductionTrainingHostIntent(
        action="full_pretraining",
        execution_mode="fresh",
        dataset_version_reference="dataset-version:11111111-1111-4111-8111-111111111111",
        dataset_manifest_reference="dataset-manifest:22222222-2222-4222-8222-222222222222",
        expected_dataset_pair_fingerprint="sha256:" + "3" * 64,
        training_config_reference="config:33333333-3333-4333-8333-333333333333",
        expected_config_fingerprint="sha256:" + "4" * 64,
        readiness_evidence_reference="readiness:44444444-4444-4444-8444-444444444444",
        expected_readiness_fingerprint="sha256:" + "5" * 64,
        run_id="run:c2-unit",
        output_logical_root="experiments/full-pretraining-candidate-a",
        decision_evidence_reference="decision:55555555-5555-4555-8555-555555555555",
    )


def _c2_claim() -> TrainingOrchestrationClaimRequest:
    return TrainingOrchestrationClaimRequest(
        identity=TrainingOrchestrationIdentity(
            run_id="run:c2-unit", request_fingerprint="sha256:" + "6" * 64
        ),
        intent_fingerprint="sha256:" + "7" * 64,
        orchestration_correlation_id="run:c2-unit",
        dataset_version_id="dataset-version-object:c2-unit",
        dataset_manifest_id="dataset-manifest-object:c2-unit",
        dataset_pair_fingerprint="sha256:" + "3" * 64,
        config_fingerprint="sha256:" + "4" * 64,
        readiness_fingerprint="sha256:" + "5" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="prerequisite-policy:c2",
        process_boundary_id="process:c2",
    )


def _c2_journal_row(*, prefixed: bool, status: str | None = None) -> dict[str, Any]:
    claim = _c2_claim()
    values = {
        "run_id": claim.identity.run_id,
        "request_fingerprint": claim.identity.request_fingerprint,
        "intent_fingerprint": claim.intent_fingerprint,
        "host_schema_version": 1,
        "host_lifecycle_version": 1,
        "orchestration_correlation_id": claim.orchestration_correlation_id,
        "dataset_version_id": claim.dataset_version_id,
        "dataset_manifest_id": claim.dataset_manifest_id,
        "dataset_pair_fingerprint": claim.dataset_pair_fingerprint,
        "config_fingerprint": claim.config_fingerprint,
        "readiness_fingerprint": claim.readiness_fingerprint,
        "source_commit": claim.source_commit,
        "prerequisite_resolution_policy_reference": claim.prerequisite_policy_reference,
        "authorization_id": None,
        "issuer_id": None,
        "approver_reference": None,
        "evidence_reference": None,
        "authorization_fingerprint": None,
        "decision_evidence_fingerprint": None,
        "decision_policy_reference": None,
        "phase": "claimed",
        "journal_version": 1,
        "backend_entered": False,
        "reconciliation_required": False,
        "reconciliation_reason_code": None,
        "process_boundary_id": claim.process_boundary_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "reservation_group_id": UUID("99999999-9999-4999-8999-999999999999"),
    }
    row = {
        f"journal_{key}" if prefixed else key: value for key, value in values.items()
    }
    if prefixed:
        row["journal_prerequisite_policy_reference"] = row.pop(
            "journal_prerequisite_resolution_policy_reference"
        )
        row["journal_version"] = row.pop("journal_journal_version")
    return {"claim_status": status, **row} if status is not None else row


def test_c2_connection_configuration_is_role_scoped_tls_explicit_and_redacted() -> None:
    settings = _PostgresTrainingConnectionSettings(
        environment="production",
        host="training-db.internal",
        port=5432,
        database="dohalm_training",
        user="dohalm_training_resolver",
        password="not-logged",
        role="dohalm_training_resolver",
        application_name="dohalm-c2-resolver",
        sslrootcert=Path("C:/protected/root.crt"),
    )
    assert repr(settings) == "_PostgresTrainingConnectionSettings(<redacted>)"
    assert settings.password not in repr(settings)
    with pytest.raises(TrainingError, match="TRAINING_DATABASE_CONFIGURATION_INVALID"):
        _PostgresTrainingConnectionSettings(
            environment="production",
            host="training-db.internal",
            port=5432,
            database="dohalm_training",
            user="postgres",
            password="not-logged",
            role="dohalm_training_resolver",
            application_name="dohalm-c2-resolver",
            sslmode="disable",
        )


def test_c2_connection_factory_commits_rolls_back_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Transaction:
        def __init__(self) -> None:
            self.exit_error: type[BaseException] | None = None

        def __enter__(self):
            return self

        def __exit__(self, error_type, *_: object) -> None:
            self.exit_error = error_type

    class Result:
        def fetchone(self):
            return ("dohalm_training_journal",)

    class Connection:
        def __init__(self) -> None:
            self.tx = Transaction()
            self.closed = False

        def transaction(self) -> Transaction:
            return self.tx

        def execute(self, *_: object, **__: object) -> Result:
            return Result()

        def close(self) -> None:
            self.closed = True

    connections: list[Connection] = []

    def connect(**_: object) -> Connection:
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    settings = _PostgresTrainingConnectionSettings(
        environment="isolated_test",
        host="127.0.0.1",
        port=5432,
        database="dohalm_training",
        user="dohalm_training_journal",
        password="synthetic-only",
        role="dohalm_training_journal",
        application_name="dohalm-c2-journal",
        sslmode="disable",
    )
    factory = _PostgresTrainingConnectionFactory(settings)
    with factory.transaction(isolation="READ COMMITTED", read_only=False):
        pass
    assert connections[-1].tx.exit_error is None
    assert connections[-1].closed is True
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with factory.transaction(isolation="READ COMMITTED", read_only=False):
            raise RuntimeError("synthetic failure")
    assert connections[-1].tx.exit_error is RuntimeError
    assert connections[-1].closed is True


def test_c2_journal_uses_named_complete_records_and_separate_transactions() -> None:
    factory = _C2Factory(
        "dohalm_training_journal", [_c2_journal_row(prefixed=True, status="acquired")]
    )
    result = _PostgresTrainingExecutionJournal(factory).claim(_c2_claim())
    assert result.status.value == "acquired"
    assert result.record.claim == _c2_claim()
    assert result.record.reservation_group_id == "99999999-9999-4999-8999-999999999999"
    assert factory.boundaries == [("READ COMMITTED", False)]
    sql, parameters = factory.connection.calls[0]
    assert "claim_c2_training_execution_journal" in sql
    assert parameters[0] == "run:c2-unit"
    assert parameters[-1] == "process:c2"
    assert set(_c2_journal_row(prefixed=True, status="acquired")) == {
        "claim_status",
        *_CLAIM_JOURNAL_COLUMN_MAP.values(),
    }


def test_c2_journal_read_and_transition_preserve_canonical_record() -> None:
    read_factory = _C2Factory(
        "dohalm_training_journal", [_c2_journal_row(prefixed=False)]
    )
    record = _PostgresTrainingExecutionJournal(read_factory).read("run:c2-unit")
    assert record is not None and record.identity == _c2_claim().identity
    assert read_factory.boundaries == [("READ COMMITTED", True)]

    transitioned = _c2_journal_row(prefixed=False)
    transitioned["phase"] = "resolved"
    transitioned["journal_version"] = 2
    transition_factory = _C2Factory("dohalm_training_journal", [transitioned])
    transition = TrainingOrchestrationTransition(
        identity=_c2_claim().identity,
        process_boundary_id="process:c2",
        expected_phase=TrainingOrchestrationPhase.CLAIMED,
        expected_version=1,
        next_phase=TrainingOrchestrationPhase.RESOLVED,
    )
    result = _PostgresTrainingExecutionJournal(transition_factory).transition(
        transition
    )
    assert result.phase is TrainingOrchestrationPhase.RESOLVED
    assert result.journal_version == 2
    assert transition_factory.boundaries == [("READ COMMITTED", False)]


def test_c2_journal_sqlstate_mapping_is_deterministic_and_not_message_based() -> None:
    expected = {
        "XX001": "TRAINING_HOST_JOURNAL_INTEGRITY_FAILURE",
        "23514": "TRAINING_HOST_JOURNAL_CONFLICT",
        "42501": "TRAINING_DATABASE_PERMISSION_DENIED",
        "57014": "TRAINING_DATABASE_TIMEOUT",
        "08006": "TRAINING_HOST_JOURNAL_UNAVAILABLE",
    }
    for state, code in expected.items():
        error = RuntimeError("localized arbitrary text")
        error.sqlstate = state  # type: ignore[attr-defined]
        assert _map_journal_error(error).code == code


def test_c2_adapter_failure_is_not_automatically_retried() -> None:
    error = RuntimeError("connection lost")
    error.sqlstate = "08006"  # type: ignore[attr-defined]
    factory = _C2Factory("dohalm_training_journal", error)
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_UNAVAILABLE"):
        _PostgresTrainingExecutionJournal(factory).read("run:c2-unit")
    assert factory.boundaries == [("READ COMMITTED", True)]


def test_c2_missing_and_malformed_results_fail_closed() -> None:
    missing_journal = _PostgresTrainingExecutionJournal(
        _C2Factory("dohalm_training_journal", [])
    )
    assert missing_journal.read("run:c2-missing") is None

    malformed = _c2_journal_row(prefixed=False)
    malformed.pop("reservation_group_id")
    with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_INTEGRITY_FAILURE"):
        _PostgresTrainingExecutionJournal(
            _C2Factory("dohalm_training_journal", [malformed])
        ).read("run:c2-unit")

    decision_request = TrainingDecisionResolutionRequest(
        intent=_c2_intent(),
        decision_authority_id="55555555-5555-4555-8555-555555555555",
        request_fingerprint="sha256:" + "6" * 64,
        dataset_version_id="dataset-version-object:c2-unit",
        dataset_manifest_id="dataset-manifest-object:c2-unit",
        dataset_pair_authority_id="88888888-8888-4888-8888-888888888888",
        dataset_pair_fingerprint="sha256:" + "3" * 64,
        config_fingerprint="sha256:" + "4" * 64,
        readiness_fingerprint="sha256:" + "5" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="prerequisite-policy:c2",
    )
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_UNAVAILABLE"):
        _PostgresTrainingDecisionResolver(
            _C2Factory("dohalm_training_resolver", []),
            policy_reference="decision-policy:c2",
        ).resolve(decision_request)
    prerequisite = _PostgresTrainingPrerequisiteResolver(
        _C2Factory("dohalm_training_resolver", []),
        policy_reference="prerequisite-policy:c2",
    )
    try:
        intent = _c2_intent()
        with pytest.raises(
            TrainingError, match="TRAINING_HOST_PREREQUISITE_UNAVAILABLE"
        ):
            prerequisite.resolve(
                TrainingPrerequisiteResolutionRequest(
                    intent=intent,
                    intent_fingerprint="sha256:" + "9" * 64,
                    dataset_version_authority_id="11111111-1111-4111-8111-111111111111",
                    dataset_manifest_authority_id="22222222-2222-4222-8222-222222222222",
                    config_authority_id="33333333-3333-4333-8333-333333333333",
                    readiness_authority_id="44444444-4444-4444-8444-444444444444",
                )
            )
    finally:
        prerequisite.close()


def test_c2_decision_snapshot_maps_named_authority_and_currentness() -> None:
    now = datetime.now(timezone.utc)
    payload = b"{}\n"
    checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
    row = {
        "snapshot_at": now,
        "decision_authority_id": UUID("55555555-5555-4555-8555-555555555555"),
        "decision_reference": "decision:55555555-5555-4555-8555-555555555555",
        "decision_payload": payload,
        "decision_payload_sha256": checksum,
        "decision_source_commit": "a" * 40,
        "decision_state": "published",
        "decision_state_effective_at": now,
        "decision_valid_until": datetime(2090, 1, 1, tzinfo=timezone.utc),
        "decision_value": "approved",
        "authorization_id": "authorization:c2",
        "request_fingerprint": "sha256:" + "6" * 64,
        "evidence_reference": "decision:55555555-5555-4555-8555-555555555555",
        "decision_policy_reference": "decision-policy:c2",
        "issued_at": now,
        "issuer_authority_id": UUID("66666666-6666-4666-8666-666666666666"),
        "issuer_id": "issuer:c2",
        "issuer_payload": payload,
        "issuer_payload_sha256": checksum,
        "issuer_adapter_kind": "same_process_training_execution_issuer",
        "issuer_active_from": now,
        "issuer_active_until": None,
        "issuer_state": "published",
        "issuer_state_effective_at": now,
        "approver_authority_id": UUID("77777777-7777-4777-8777-777777777777"),
        "approver_reference": "approver:c2",
        "approver_payload": payload,
        "approver_payload_sha256": checksum,
        "approver_active_from": now,
        "approver_active_until": None,
        "approver_state": "published",
        "approver_state_effective_at": now,
    }
    request = TrainingDecisionResolutionRequest(
        intent=_c2_intent(),
        decision_authority_id="55555555-5555-4555-8555-555555555555",
        request_fingerprint="sha256:" + "6" * 64,
        dataset_version_id="dataset-version-object:c2-unit",
        dataset_manifest_id="dataset-manifest-object:c2-unit",
        dataset_pair_authority_id="88888888-8888-4888-8888-888888888888",
        dataset_pair_fingerprint="sha256:" + "3" * 64,
        config_fingerprint="sha256:" + "4" * 64,
        readiness_fingerprint="sha256:" + "5" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="prerequisite-policy:c2",
    )
    factory = _C2Factory("dohalm_training_resolver", [row])
    resolution = _PostgresTrainingDecisionResolver(
        factory, policy_reference="decision-policy:c2"
    ).resolve(request)
    assert resolution.decision.decision.value == "approved"
    assert (
        resolution.provenance.issuer_authority_id
        == "66666666-6666-4666-8666-666666666666"
    )
    assert resolution.provenance.approver_current is True
    assert factory.boundaries == [("REPEATABLE READ", True)]


def test_c2_prerequisite_maps_named_snapshot_and_cleans_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.training.postgres_training_adapters as adapters
    from src.data.checksums import canonical_json_bytes

    now = datetime.now(timezone.utc)
    config = b"output_dir: experiments/full-pretraining-candidate-a\n"
    readiness = b"schema_version: '1.0'\n"
    config_fingerprint = "sha256:" + hashlib.sha256(config).hexdigest()
    readiness_fingerprint = "sha256:" + hashlib.sha256(readiness).hexdigest()
    intent = ProductionTrainingHostIntent(
        action="full_pretraining",
        execution_mode="fresh",
        dataset_version_reference="dataset-version:11111111-1111-4111-8111-111111111111",
        dataset_manifest_reference="dataset-manifest:22222222-2222-4222-8222-222222222222",
        expected_dataset_pair_fingerprint="sha256:" + "3" * 64,
        training_config_reference="config:33333333-3333-4333-8333-333333333333",
        expected_config_fingerprint=config_fingerprint,
        readiness_evidence_reference="readiness:44444444-4444-4444-8444-444444444444",
        expected_readiness_fingerprint=readiness_fingerprint,
        run_id="run:c2-unit",
        output_logical_root="experiments/full-pretraining-candidate-a",
        decision_evidence_reference="decision:55555555-5555-4555-8555-555555555555",
    )

    def payload(name: str, value: bytes) -> dict[str, Any]:
        return {
            f"{name}_payload": value,
            f"{name}_payload_sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
        }

    row: dict[str, Any] = {
        "snapshot_at": now,
        "dataset_version_authority_id": UUID("11111111-1111-4111-8111-111111111111"),
        "dataset_version_reference": intent.dataset_version_reference,
        "dataset_version_source_commit": "a" * 40,
        "dataset_version_state": "published",
        "dataset_version_state_effective_at": now,
        "dataset_manifest_authority_id": UUID("22222222-2222-4222-8222-222222222222"),
        "dataset_manifest_reference": intent.dataset_manifest_reference,
        "dataset_manifest_source_commit": "a" * 40,
        "dataset_manifest_state": "published",
        "dataset_manifest_state_effective_at": now,
        "dataset_pair_authority_id": UUID("88888888-8888-4888-8888-888888888888"),
        "dataset_pair_reference": "dataset-pair:c2-unit",
        "dataset_pair_source_commit": "a" * 40,
        "dataset_pair_fingerprint": intent.expected_dataset_pair_fingerprint,
        "dataset_pair_publication_scenario": "synthetic-contract",
        "dataset_pair_state": "published",
        "dataset_pair_state_effective_at": now,
        "config_authority_id": UUID("33333333-3333-4333-8333-333333333333"),
        "config_reference": intent.training_config_reference,
        "config_source_commit": "a" * 40,
        "config_kind": "full_pretraining",
        "config_schema_version": 1,
        "config_state": "published",
        "config_state_effective_at": now,
        "readiness_authority_id": UUID("44444444-4444-4444-8444-444444444444"),
        "readiness_reference": intent.readiness_evidence_reference,
        "readiness_source_commit": "a" * 40,
        "readiness_pair_fingerprint": intent.expected_dataset_pair_fingerprint,
        "readiness_config_fingerprint": config_fingerprint,
        "readiness_evaluated_at": now,
        "readiness_valid_until": datetime(2090, 1, 1, tzinfo=timezone.utc),
        "readiness_result": "READY",
        "readiness_state": "published",
        "readiness_state_effective_at": now,
        **payload(
            "dataset_version",
            canonical_json_bytes({"object_id": "dataset-version-object:c2-unit"}),
        ),
        **payload(
            "dataset_manifest",
            canonical_json_bytes({"object_id": "dataset-manifest-object:c2-unit"}),
        ),
        **payload(
            "dataset_pair",
            canonical_json_bytes(
                {
                    "upstream_objects": [],
                    "evaluated_at": now.isoformat(),
                    "expected_split_id": "split:c2",
                    "artifact_references": [],
                }
            ),
        ),
        **payload("config", config),
        **payload("readiness", readiness),
    }
    request = TrainingPrerequisiteResolutionRequest(
        intent=intent,
        intent_fingerprint="sha256:" + "9" * 64,
        dataset_version_authority_id="11111111-1111-4111-8111-111111111111",
        dataset_manifest_authority_id="22222222-2222-4222-8222-222222222222",
        config_authority_id="33333333-3333-4333-8333-333333333333",
        readiness_authority_id="44444444-4444-4444-8444-444444444444",
    )
    fake_config = SimpleNamespace(
        output_dir=intent.output_logical_root, to_dict=lambda: {"validated": True}
    )
    permission = DatasetTrainingPermission(
        allowed=True,
        reason_codes=(),
        dataset_version_id="dataset-version-object:c2-unit",
        dataset_manifest_id="dataset-manifest-object:c2-unit",
        pair_fingerprint=intent.expected_dataset_pair_fingerprint,
    )
    monkeypatch.setattr(
        adapters.FullPretrainingConfig, "from_yaml", lambda _: fake_config
    )
    monkeypatch.setattr(
        adapters,
        "inspect_full_pretraining_readiness",
        lambda *_: {"execution_allowed": True},
    )
    monkeypatch.setattr(
        adapters, "evaluate_dataset_training_entry", lambda *_, **__: permission
    )
    factory = _C2Factory("dohalm_training_resolver", [row])
    resolver = _PostgresTrainingPrerequisiteResolver(
        factory, policy_reference="prerequisite-policy:c2"
    )
    root = resolver._materialization_root
    result = resolver.resolve(request)
    assert result.dataset_pair_authority_id == "88888888-8888-4888-8888-888888888888"
    assert result.config_path.read_bytes() == config
    assert result.manifest_path.read_bytes() == readiness
    assert factory.boundaries == [("REPEATABLE READ", True)]
    resolver.release(result)
    assert not result.config_path.parent.exists()
    resolver.close()
    assert not root.exists()
