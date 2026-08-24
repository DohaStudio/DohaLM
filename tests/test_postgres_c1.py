from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.postgres_c1 import C1PostgresError, C1PostgresSettings, load_c1_migrations


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
        "0004_dataset_proposal_authority.sql",
        "0005_dataset_review_authority.sql",
    ]
    sql = migrations[2].sql
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


def test_dataset_proposal_migration_has_separate_immutable_restricted_authority() -> (
    None
):
    migration = load_c1_migrations()[3]
    assert migration.name == "0004_dataset_proposal_authority.sql"
    sql = migration.sql
    assert "CREATE SCHEMA dohalm_dataset_governance_v1" in sql
    assert "PRIMARY KEY (object_id, dataset_id, dataset_version)" in sql
    assert (
        "ON CONFLICT ON CONSTRAINT dataset_version_proposal_authority_pkey DO NOTHING"
        in sql
    )
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "SECURITY DEFINER" in sql
    assert (
        "CREATE FUNCTION dohalm_dataset_governance_v1.lock_dataset_version_proposal_identity"
        in sql
    )
    assert (
        "CREATE FUNCTION dohalm_dataset_governance_v1.read_dataset_version_proposal"
        in sql
    )
    assert "REVOKE ALL ON ALL TABLES" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "dohalm_training_v1.dataset_version_authority" not in sql


def test_dataset_review_migration_has_bound_immutable_restricted_authority() -> None:
    migration = load_c1_migrations()[-1]
    assert migration.name == "0005_dataset_review_authority.sql"
    sql = migration.sql
    assert (
        "CREATE TABLE dohalm_dataset_governance_v1.dataset_version_review_authority"
        in sql
    )
    assert "PRIMARY KEY (object_id, dataset_id, dataset_version)" in sql
    assert (
        "FOREIGN KEY (object_id, dataset_id, dataset_version, proposal_fingerprint)"
        in sql
    )
    assert (
        "CREATE UNIQUE INDEX dataset_version_proposal_authority_identity_fingerprint_uq"
        in sql
    )
    assert (
        "CREATE FUNCTION dohalm_dataset_governance_v1.compute_dataset_review_record_fingerprint"
        in sql
    )
    assert (
        "CREATE FUNCTION dohalm_dataset_governance_v1.start_dataset_version_review"
        in sql
    )
    assert (
        "CREATE FUNCTION dohalm_dataset_governance_v1.read_dataset_version_review"
        in sql
    )
    assert "pg_catalog.pg_advisory_xact_lock" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = pg_catalog, pg_temp" in sql
    assert "REVOKE ALL ON ALL TABLES" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "dohalm_training_v1.dataset_version_authority" not in sql
