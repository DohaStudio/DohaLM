"""C1-only PostgreSQL connection and migration contracts.

This module is intentionally not a production adapter.  It accepts only an
explicit isolated-test configuration and never reads a DSN or credential from
the production environment.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from .errors import TrainingError

if TYPE_CHECKING:
    from psycopg import Connection


_C1_ENVIRONMENTS = frozenset({"local_ephemeral", "ci_ephemeral"})
_C1_NAME_PATTERN = re.compile(r"dohalm_c1_[a-z0-9_]{1,48}")
_C1_DOCKER_HOST_PATTERN = re.compile(r"dohalm-c1-[a-z0-9-]{1,48}")
_MIGRATION_PATTERN = re.compile(r"(?P<version>[0-9]{4})_[a-z0-9_]+\.sql")
_MIGRATION_LOCK_CLASS = 0x444F4841
_MIGRATION_LOCK_KEY = 1
_SCHEMA = "dohalm_training_v1"


class C1PostgresErrorCode(str, Enum):
    """Stable, sanitized C1 database failure classes."""

    CHECK_VIOLATION = "C1_POSTGRES_CHECK_VIOLATION"
    CONNECTION_UNAVAILABLE = "C1_POSTGRES_CONNECTION_UNAVAILABLE"
    FOREIGN_KEY_VIOLATION = "C1_POSTGRES_FOREIGN_KEY_VIOLATION"
    MIGRATION_CONFLICT = "C1_POSTGRES_MIGRATION_CONFLICT"
    PERMISSION_DENIED = "C1_POSTGRES_PERMISSION_DENIED"
    UNIQUE_VIOLATION = "C1_POSTGRES_UNIQUE_VIOLATION"
    UNKNOWN = "C1_POSTGRES_UNKNOWN"


def _failure(code: C1PostgresErrorCode) -> TrainingError:
    return TrainingError(code.value, "The isolated C1 PostgreSQL operation failed.")


def map_c1_postgres_error(error: BaseException) -> TrainingError:
    """Map Psycopg failures without exposing SQL, paths, DSNs, or credentials."""

    try:
        from psycopg import OperationalError, errors
    except ImportError:
        return _failure(C1PostgresErrorCode.CONNECTION_UNAVAILABLE)
    if isinstance(error, errors.ForeignKeyViolation):
        return _failure(C1PostgresErrorCode.FOREIGN_KEY_VIOLATION)
    if isinstance(error, errors.CheckViolation):
        return _failure(C1PostgresErrorCode.CHECK_VIOLATION)
    if isinstance(error, errors.UniqueViolation):
        return _failure(C1PostgresErrorCode.UNIQUE_VIOLATION)
    if isinstance(error, errors.InsufficientPrivilege):
        return _failure(C1PostgresErrorCode.PERMISSION_DENIED)
    if isinstance(error, OperationalError):
        return _failure(C1PostgresErrorCode.CONNECTION_UNAVAILABLE)
    return _failure(C1PostgresErrorCode.UNKNOWN)


@dataclass(frozen=True, slots=True, repr=False)
class C1PostgresSettings:
    """Explicit synthetic connection values for one disposable C1 fixture."""

    environment: str
    host: str
    port: int
    database: str
    user: str
    password: str

    def __post_init__(self) -> None:
        allowed_host = self.host in {"127.0.0.1", "localhost"} or (
            _C1_DOCKER_HOST_PATTERN.fullmatch(self.host) is not None
        )
        if (
            self.environment not in _C1_ENVIRONMENTS
            or not allowed_host
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
            or _C1_NAME_PATTERN.fullmatch(self.database) is None
            or _C1_NAME_PATTERN.fullmatch(self.user) is None
            or type(self.password) is not str
            or not 16 <= len(self.password) <= 128
        ):
            raise TrainingError(
                "C1_POSTGRES_SETTINGS_INVALID",
                "Valid isolated synthetic C1 PostgreSQL settings are required.",
            )

    def __repr__(self) -> str:
        return "C1PostgresSettings(<redacted>)"


class C1PostgresConnectionFactory:
    """Synchronous Psycopg connection lifecycle for isolated C1 tests only."""

    def __init__(self, settings: C1PostgresSettings) -> None:
        if type(settings) is not C1PostgresSettings:
            raise TypeError("settings must be C1PostgresSettings")
        self._settings = settings

    @contextmanager
    def connection(self) -> Iterator[Connection[object]]:
        try:
            import psycopg

            connection = psycopg.connect(
                host=self._settings.host,
                port=self._settings.port,
                dbname=self._settings.database,
                user=self._settings.user,
                password=self._settings.password,
                connect_timeout=5,
                options="-c timezone=UTC -c client_encoding=UTF8",
                autocommit=False,
            )
        except Exception as error:
            raise map_c1_postgres_error(error) from None
        try:
            yield connection
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class C1Migration:
    version: int
    name: str
    sha256: str
    sql: str


def load_c1_migrations(directory: Path | None = None) -> tuple[C1Migration, ...]:
    root = directory or Path(__file__).with_name("postgres_migrations")
    migrations: list[C1Migration] = []
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT)
        raw = path.read_bytes()
        try:
            sql_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT) from None
        if raw.startswith(b"\xef\xbb\xbf") or "\x00" in sql_text:
            raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT)
        migrations.append(
            C1Migration(
                version=int(match.group("version")),
                name=path.name,
                sha256=hashlib.sha256(raw).hexdigest(),
                sql=sql_text,
            )
        )
    versions = [migration.version for migration in migrations]
    if not migrations or versions != list(range(1, len(migrations) + 1)):
        raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT)
    return tuple(migrations)


def apply_c1_migrations(
    connection: Connection[object], directory: Path | None = None
) -> tuple[int, ...]:
    """Apply ordered migrations under a transaction-scoped advisory lock."""

    migrations = load_c1_migrations(directory)
    applied: list[int] = []
    try:
        with connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (_MIGRATION_LOCK_CLASS, _MIGRATION_LOCK_KEY),
            )
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SCHEMA}.schema_migration (
                    version integer PRIMARY KEY CHECK (version >= 1),
                    name text NOT NULL UNIQUE,
                    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
                    applied_at timestamptz NOT NULL DEFAULT transaction_timestamp()
                )
                """
            )
            rows = connection.execute(
                f"SELECT version, name, sha256 FROM {_SCHEMA}.schema_migration ORDER BY version"
            ).fetchall()
            recorded = {int(row[0]): (str(row[1]), str(row[2])) for row in rows}
            if any(
                version not in {item.version for item in migrations}
                for version in recorded
            ):
                raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT)
            for migration in migrations:
                previous = recorded.get(migration.version)
                if previous is not None:
                    if previous != (migration.name, migration.sha256):
                        raise _failure(C1PostgresErrorCode.MIGRATION_CONFLICT)
                    continue
                connection.execute(migration.sql, prepare=False)
                connection.execute(
                    f"INSERT INTO {_SCHEMA}.schema_migration (version, name, sha256) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.sha256),
                )
                applied.append(migration.version)
    except TrainingError:
        raise
    except Exception as error:
        raise map_c1_postgres_error(error) from None
    return tuple(applied)
