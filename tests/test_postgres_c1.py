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
