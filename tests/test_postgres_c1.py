from __future__ import annotations

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
    from pathlib import Path

    with pytest.raises(C1PostgresError, match="C1_POSTGRES_MIGRATION_CONFLICT"):
        load_c1_migrations(Path("tests/fixtures/no-c1-migrations"))
