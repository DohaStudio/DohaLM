from __future__ import annotations

import json
import platform
import secrets
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Iterator

import pytest

from src.postgres_c1 import (
    C1PostgresConnectionFactory,
    C1PostgresError,
    C1PostgresSettings,
    apply_c1_migrations,
    map_c1_postgres_error,
)


IMAGE = (
    "postgres:16.15-alpine@"
    "sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571"
)
LABEL_KEY = "com.dohastudio.c1.correlation"
SCHEMA = "dohalm_training_v1"


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _wait_healthy(container: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = _docker(
            "inspect", "--format", "{{.State.Health.Status}}", container, check=False
        )
        if result.returncode == 0 and result.stdout.strip() == "healthy":
            return
        time.sleep(1)
    logs = _docker("logs", container, check=False).stderr[-2000:]
    raise AssertionError(f"isolated PostgreSQL fixture did not become healthy: {logs}")


def _assert_loopback_listener(container: str, port: int) -> None:
    published = _docker("port", container, "5432/tcp").stdout.strip().splitlines()
    assert published == [f"127.0.0.1:{port}"]
    if platform.system() == "Windows":
        command = (
            "$listeners = Get-NetTCPConnection -State Listen -LocalPort "
            f"{port} -ErrorAction Stop; "
            "$listeners | Select-Object -ExpandProperty LocalAddress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        addresses = {
            line.strip() for line in result.stdout.splitlines() if line.strip()
        }
        assert addresses == {"127.0.0.1"}
    else:
        result = subprocess.run(
            ["ss", "-H", "-ltn", "sport", "=", f":{port}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        listeners = [line for line in result.stdout.splitlines() if line.strip()]
        assert listeners
        local_addresses = [line.split()[3] for line in listeners]
        assert local_addresses == [f"127.0.0.1:{port}"]


@dataclass(frozen=True)
class C1Fixture:
    correlation: str
    container: str
    volume: str
    network: str
    settings: C1PostgresSettings
    factory: C1PostgresConnectionFactory
    concurrent_results: tuple[tuple[int, ...], ...]


@pytest.fixture(scope="session")
def c1_postgres() -> Iterator[C1Fixture]:
    correlation = uuid.uuid4().hex
    container = f"dohalm-c1-postgres-{correlation[:12]}"
    volume = f"dohalm-c1-pgdata-{correlation[:12]}"
    network = f"dohalm-c1-network-{correlation[:12]}"
    database = f"dohalm_c1_{correlation[:12]}"
    user = f"dohalm_c1_{correlation[12:24]}"
    password = secrets.token_urlsafe(32)

    _docker(
        "network",
        "create",
        "--label",
        f"{LABEL_KEY}={correlation}",
        network,
    )
    _docker("volume", "create", "--label", f"{LABEL_KEY}={correlation}", volume)
    try:
        _docker(
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            f"{LABEL_KEY}={correlation}",
            "--network",
            network,
            "--mount",
            f"type=volume,source={volume},target=/var/lib/postgresql/data",
            "--publish",
            "127.0.0.1:0:5432",
            "--env",
            f"POSTGRES_DB={database}",
            "--env",
            f"POSTGRES_USER={user}",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "--env",
            "POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C",
            "--health-cmd",
            f"pg_isready -U {user} -d {database}",
            "--health-interval",
            "1s",
            "--health-timeout",
            "5s",
            "--health-retries",
            "60",
            IMAGE,
        )
        _wait_healthy(container)
        inspect = json.loads(_docker("inspect", container).stdout)[0]
        binding = inspect["NetworkSettings"]["Ports"]["5432/tcp"][0]
        assert binding["HostIp"] == "127.0.0.1"
        _assert_loopback_listener(container, int(binding["HostPort"]))
        settings = C1PostgresSettings(
            environment="local_ephemeral",
            host="127.0.0.1",
            port=int(binding["HostPort"]),
            database=database,
            user=user,
            password=password,
        )
        factory = C1PostgresConnectionFactory(settings)

        def migrate() -> tuple[int, ...]:
            with factory.connection() as connection:
                return apply_c1_migrations(connection)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: migrate(), range(2)))
        assert sorted(results, key=len) == [(), (1,)]
        yield C1Fixture(
            correlation,
            container,
            volume,
            network,
            settings,
            factory,
            results,
        )
    finally:
        _docker("rm", "--force", container, check=False)
        _docker("volume", "rm", volume, check=False)
        _docker("network", "rm", network, check=False)
        for resource, noun in (
            ("ps", "container"),
            ("volume ls", "volume"),
            ("network ls", "network"),
        ):
            args = resource.split()
            residue = _docker(
                *args, "--quiet", "--filter", f"label={LABEL_KEY}={correlation}"
            )
            assert not residue.stdout.strip(), f"C1 {noun} residue remains"


@pytest.mark.integration
def test_exact_versions_locale_and_private_binding(c1_postgres: C1Fixture) -> None:
    import psycopg
    from psycopg import pq

    assert psycopg.__version__ == "3.3.4"
    assert pq.__impl__ == "binary"
    assert pq.version() >= 180000
    inspect = json.loads(_docker("inspect", c1_postgres.container).stdout)[0]
    repo_digests = json.loads(_docker("image", "inspect", IMAGE).stdout)[0][
        "RepoDigests"
    ]
    assert any(item.endswith("@" + IMAGE.rsplit("@", 1)[1]) for item in repo_digests)
    assert inspect["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] == "127.0.0.1"

    with c1_postgres.factory.connection() as connection:
        row = connection.execute(
            "SELECT current_setting('server_version_num'), current_setting('server_encoding'), "
            "current_setting('TimeZone'), "
            "(SELECT datcollate FROM pg_database WHERE datname = current_database())"
        ).fetchone()
    assert row == ("160015", "UTF8", "UTC", "C")


@pytest.mark.integration
def test_parameter_binding_transactions_and_sanitized_errors(
    c1_postgres: C1Fixture,
) -> None:
    with c1_postgres.factory.connection() as connection:
        connection.execute(
            "CREATE TEMP TABLE binding_test (value text CHECK (value <> 'blocked'))"
        )
        payload = "quoted ' value; DROP TABLE binding_test; --"
        connection.execute("INSERT INTO binding_test (value) VALUES (%s)", (payload,))
        assert connection.execute("SELECT value FROM binding_test").fetchone() == (
            payload,
        )
        connection.rollback()

        with connection.transaction():
            connection.execute(
                "CREATE TABLE IF NOT EXISTS c1_restart_probe (value integer PRIMARY KEY)"
            )
            connection.execute(
                "INSERT INTO c1_restart_probe VALUES (1) ON CONFLICT DO NOTHING"
            )

        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute(
                    "CREATE TEMP TABLE check_test (value integer CHECK (value > 0))"
                )
                connection.execute("INSERT INTO check_test VALUES (%s)", (-1,))
        failure = map_c1_postgres_error(captured.value)
        assert "C1_POSTGRES_CHECK_VIOLATION" in str(failure)
        assert "INSERT" not in str(failure)


@pytest.mark.integration
def test_schema_envelopes_roles_and_immutable_boundary(c1_postgres: C1Fixture) -> None:
    families = (
        "training_config_authority",
        "training_readiness_authority",
        "dataset_version_authority",
        "dataset_manifest_authority",
        "dataset_pair_authority",
        "training_issuer_registry",
        "training_approver_registry",
        "training_execution_decision_authority",
    )
    envelope = {
        "schema_version",
        "payload_bytes",
        "payload_sha256",
        "created_at",
        "valid_from",
        "valid_until",
        "source_commit",
    }
    with c1_postgres.factory.connection() as connection:
        rows = connection.execute(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = ANY(%s) AND column_name = ANY(%s)",
            (SCHEMA, list(families), list(envelope)),
        ).fetchall()
        by_table: dict[str, dict[str, str]] = {name: {} for name in families}
        for table, column, nullable in rows:
            by_table[str(table)][str(column)] = str(nullable)
        assert all(set(columns) == envelope for columns in by_table.values())
        assert all(
            columns["valid_until"] == "YES"
            and all(
                value == "NO" for key, value in columns.items() if key != "valid_until"
            )
            for columns in by_table.values()
        )

        roles = dict(
            connection.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
                (["dohalm_training_owner", "dohalm_training_runtime"],),
            ).fetchall()
        )
        assert roles == {
            "dohalm_training_owner": False,
            "dohalm_training_runtime": True,
        }
        function = connection.execute(
            "SELECT p.prosecdef, p.proconfig FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = %s AND p.proname = 'read_authority_state'",
            (SCHEMA,),
        ).fetchone()
        assert function is not None and function[0] is True
        assert function[1] == ["search_path=pg_catalog, pg_temp"]

        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE dohalm_training_runtime")
                assert connection.execute(
                    f"SELECT {SCHEMA}.read_authority_state(%s)",
                    (uuid.uuid4(),),
                ).fetchone() == (None,)
                connection.execute(
                    f"SELECT count(*) FROM {SCHEMA}.training_authority_identity"
                )
        assert "C1_POSTGRES_PERMISSION_DENIED" in str(
            map_c1_postgres_error(captured.value)
        )


@pytest.mark.integration
def test_logical_restore_preserves_migration_contract(c1_postgres: C1Fixture) -> None:
    restored_database = f"dohalm_c1_restore_{c1_postgres.correlation[:8]}"
    dump_path = f"/tmp/dohalm-c1-{c1_postgres.correlation[:12]}.dump"
    _docker(
        "exec",
        c1_postgres.container,
        "pg_dump",
        "--format=custom",
        f"--file={dump_path}",
        f"--username={c1_postgres.settings.user}",
        c1_postgres.settings.database,
    )
    try:
        _docker(
            "exec",
            c1_postgres.container,
            "createdb",
            f"--username={c1_postgres.settings.user}",
            restored_database,
        )
        _docker(
            "exec",
            c1_postgres.container,
            "pg_restore",
            f"--username={c1_postgres.settings.user}",
            f"--dbname={restored_database}",
            "--exit-on-error",
            dump_path,
        )
        restore_factory = C1PostgresConnectionFactory(
            replace(c1_postgres.settings, database=restored_database)
        )
        with restore_factory.connection() as connection:
            rows = connection.execute(
                f"SELECT version, name, sha256 FROM {SCHEMA}.schema_migration"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == 1
            assert rows[0][1] == "0001_training_authority_and_journal.sql"
            assert len(rows[0][2]) == 64
            assert apply_c1_migrations(connection) == ()
    finally:
        _docker(
            "exec",
            c1_postgres.container,
            "dropdb",
            "--if-exists",
            f"--username={c1_postgres.settings.user}",
            restored_database,
            check=False,
        )
        _docker("exec", c1_postgres.container, "rm", "-f", dump_path, check=False)


@pytest.mark.integration
def test_migration_idempotency_advisory_lock_and_restart(
    c1_postgres: C1Fixture,
) -> None:
    with (
        c1_postgres.factory.connection() as first,
        c1_postgres.factory.connection() as second,
    ):
        assert apply_c1_migrations(first) == ()
        first.execute("SELECT pg_advisory_lock(%s, %s)", (0x444F4841, 1))
        assert second.execute(
            "SELECT pg_try_advisory_lock(%s, %s)", (0x444F4841, 1)
        ).fetchone() == (False,)
        first.execute("SELECT pg_advisory_unlock(%s, %s)", (0x444F4841, 1))

    _docker("restart", c1_postgres.container)
    _wait_healthy(c1_postgres.container)
    inspect = json.loads(_docker("inspect", c1_postgres.container).stdout)[0]
    binding = inspect["NetworkSettings"]["Ports"]["5432/tcp"][0]
    assert binding["HostIp"] == "127.0.0.1"
    restart_port = int(binding["HostPort"])
    _assert_loopback_listener(c1_postgres.container, restart_port)
    restart_factory = C1PostgresConnectionFactory(
        replace(c1_postgres.settings, port=restart_port)
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            with restart_factory.connection():
                break
        except C1PostgresError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    with restart_factory.connection() as connection:
        assert connection.execute("SELECT value FROM c1_restart_probe").fetchone() == (
            1,
        )
        assert apply_c1_migrations(connection) == ()
