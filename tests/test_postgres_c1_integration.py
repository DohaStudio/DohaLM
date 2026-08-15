from __future__ import annotations

import json
import hashlib
import platform
import secrets
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
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
        assert sorted(results, key=len) == [(), (1, 2)]
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


def _canonical_payload(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.fixture(scope="session")
def c1_1_authority_mapping(c1_postgres: C1Fixture) -> dict[str, object]:
    mapping = json.loads(
        Path("tests/fixtures/c1_1_authority_mapping.json").read_text(encoding="utf-8")
    )
    assert mapping["schema_version"] == 1
    assert mapping["synthetic_only"] is True
    values = mapping["mappings"]
    config = values["config"]
    readiness = values["readiness"]
    config_payload = _canonical_payload(config["payload"])
    readiness_payload = _canonical_payload(readiness["payload"])
    config_fingerprint = "sha256:" + hashlib.sha256(config_payload).hexdigest()
    readiness_fingerprint = "sha256:" + hashlib.sha256(readiness_payload).hexdigest()

    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_authority_producer")
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_authority_identity "
                "(authority_id, subject_family, domain_key) VALUES (%s, 'config', %s), (%s, 'readiness', %s)",
                (
                    config["authority_id"],
                    config["domain_key"],
                    readiness["authority_id"],
                    readiness["domain_key"],
                ),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_config_authority "
                "(authority_id, payload_bytes, payload_sha256, valid_from, source_commit, config_kind, config_schema_version) "
                "VALUES (%s, %s, %s, %s, %s, 'full_pretraining', 1)",
                (
                    config["authority_id"],
                    config_payload,
                    config_fingerprint,
                    config["valid_from"],
                    config["source_commit"],
                ),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_readiness_authority "
                "(authority_id, payload_bytes, payload_sha256, valid_from, valid_until, source_commit, "
                "dataset_pair_fingerprint, config_fingerprint, evaluated_at, readiness_result) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'READY')",
                (
                    readiness["authority_id"],
                    readiness_payload,
                    readiness_fingerprint,
                    readiness["valid_from"],
                    readiness["valid_until"],
                    readiness["source_commit"],
                    readiness["dataset_pair_fingerprint"],
                    config_fingerprint,
                    readiness["evaluated_at"],
                ),
            )
            for family, record in (("config", config), ("readiness", readiness)):
                connection.execute(
                    f"SELECT ({SCHEMA}.write_training_authority_event(%s, %s, %s, 0, 'published', NULL, %s, %s, %s)).state",
                    (
                        uuid.uuid4(),
                        record["authority_id"],
                        family,
                        record["valid_from"],
                        f"correlation:{family}",
                        f"evidence:{family}",
                    ),
                )
    mapping["computed"] = {
        "config_fingerprint": config_fingerprint,
        "readiness_fingerprint": readiness_fingerprint,
    }
    return mapping


@pytest.mark.integration
def test_c1_1_roles_grants_and_authoritative_mapping(
    c1_postgres: C1Fixture, c1_1_authority_mapping: dict[str, object]
) -> None:
    assert c1_1_authority_mapping["producer"] == {
        "database_role": "dohalm_training_authority_producer",
        "persisted_domain_identifier": "training_authority_producer",
        "workflow": "immutable-row-insert-then-restricted-event-append",
    }
    with c1_postgres.factory.connection() as connection:
        roles = dict(
            connection.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
                (
                    [
                        "dohalm_training_authority_producer",
                        "dohalm_training_resolver",
                        "dohalm_training_journal",
                    ],
                ),
            ).fetchall()
        )
        assert roles == {
            "dohalm_training_authority_producer": True,
            "dohalm_training_resolver": True,
            "dohalm_training_journal": True,
        }
        functions = dict(
            connection.execute(
                "SELECT p.proname, p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=%s AND p.proname = ANY(%s)",
                (
                    SCHEMA,
                    [
                        "write_training_authority_event",
                        "read_training_authority_snapshot",
                        "claim_training_execution_journal",
                        "transition_training_execution_journal",
                        "read_training_execution_journal",
                    ],
                ),
            ).fetchall()
        )
        assert len(functions) == 5 and all(functions.values())


@pytest.mark.integration
def test_c1_1_repeatable_read_only_snapshot_and_direct_table_denial(
    c1_postgres: C1Fixture, c1_1_authority_mapping: dict[str, object]
) -> None:
    ids = [
        value["authority_id"] for value in c1_1_authority_mapping["mappings"].values()
    ]
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            connection.execute("SET LOCAL ROLE dohalm_training_resolver")
            rows = connection.execute(
                f"SELECT snapshot_subject_family, snapshot_state, snapshot_projection_version "
                f"FROM {SCHEMA}.read_training_authority_snapshot(%s)",
                (ids,),
            ).fetchall()
            assert rows == [("config", "scheduled", 1), ("readiness", "scheduled", 1)]
        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE dohalm_training_resolver")
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.read_training_authority_snapshot(%s)",
                    (ids,),
                )
        assert "read-only authority snapshot required" in str(captured.value)
        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE dohalm_training_resolver")
                connection.execute(
                    f"SELECT count(*) FROM {SCHEMA}.training_authority_current"
                )
        assert "C1_POSTGRES_PERMISSION_DENIED" in str(
            map_c1_postgres_error(captured.value)
        )


def _claim(connection: object, run_id: str, request: str, correlation: str):
    fingerprint = "sha256:" + request * 64
    return connection.execute(
        f"SELECT * FROM {SCHEMA}.claim_training_execution_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            run_id,
            fingerprint,
            "sha256:" + "b" * 64,
            correlation,
            "dataset-version:synthetic",
            "dataset-manifest:synthetic",
            "sha256:" + "c" * 64,
            "sha256:" + "d" * 64,
            "sha256:" + "e" * 64,
            "a" * 40,
            "prerequisite-policy:c1-1",
            "process:c1-1",
        ),
    ).fetchone()


@contextmanager
def _restricted_journal_transaction(c1_postgres: C1Fixture) -> Iterator[object]:
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            yield connection


@contextmanager
def _owner_verification_transaction(c1_postgres: C1Fixture) -> Iterator[object]:
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_owner")
            yield connection


@pytest.mark.integration
def test_c1_1_claim_architecture_concurrency_matrix(c1_postgres: C1Fixture) -> None:
    def concurrent_claims(
        claims: list[tuple[str, str, str]],
    ) -> list[tuple[str, object]]:
        barrier = threading.Barrier(len(claims))

        def worker(values: tuple[str, str, str]) -> tuple[str, object]:
            try:
                with _restricted_journal_transaction(c1_postgres) as connection:
                    barrier.wait(timeout=30)
                    return "row", _claim(connection, *values)
            except Exception as error:
                return "error", (
                    getattr(error, "sqlstate", None),
                    getattr(getattr(error, "diag", None), "constraint_name", None),
                )

        with ThreadPoolExecutor(max_workers=len(claims)) as executor:
            return list(executor.map(worker, claims))

    def assert_single_winner(
        outcomes: list[tuple[str, object]], *, expected_losers: int
    ) -> None:
        winners = [value for kind, value in outcomes if kind == "row"]
        losers = [value for kind, value in outcomes if kind == "error"]
        assert len(winners) == 1, outcomes
        assert winners[0][0] == "acquired"
        assert len(losers) == expected_losers
        assert all(value[0] == "40001" for value in losers), outcomes

    matrix_runs: list[str] = []
    same_identity = concurrent_claims(
        [
            ("run:c1-1-same", "2", "correlation:c1-1-same"),
            ("run:c1-1-same", "2", "correlation:c1-1-same"),
        ]
    )
    assert_single_winner(same_identity, expected_losers=1)
    matrix_runs.append("run:c1-1-same")

    different_correlation = concurrent_claims(
        [
            ("run:c1-1-run-collision", "3", "correlation:c1-1-run-a"),
            ("run:c1-1-run-collision", "3", "correlation:c1-1-run-b"),
        ]
    )
    assert_single_winner(different_correlation, expected_losers=1)
    matrix_runs.append("run:c1-1-run-collision")

    different_run = concurrent_claims(
        [
            ("run:c1-1-correlation-a", "4", "correlation:c1-1-collision"),
            ("run:c1-1-correlation-b", "4", "correlation:c1-1-collision"),
        ]
    )
    assert_single_winner(different_run, expected_losers=1)

    different_fingerprint = concurrent_claims(
        [
            ("run:c1-1-fingerprint", "8", "correlation:c1-1-fingerprint"),
            ("run:c1-1-fingerprint", "9", "correlation:c1-1-fingerprint"),
        ]
    )
    assert_single_winner(different_fingerprint, expected_losers=1)
    matrix_runs.append("run:c1-1-fingerprint")

    independent = concurrent_claims(
        [
            ("run:c1-1-independent-a", "a", "correlation:c1-1-independent-a"),
            ("run:c1-1-independent-b", "b", "correlation:c1-1-independent-b"),
        ]
    )
    assert len([value for kind, value in independent if kind == "row"]) == 2
    assert all(value[0] == "acquired" for kind, value in independent if kind == "row")
    matrix_runs.extend(["run:c1-1-independent-a", "run:c1-1-independent-b"])

    for iteration in range(5):
        run_id = f"run:c1-1-four-{iteration}"
        correlation = f"correlation:c1-1-four-{iteration}"
        outcomes = concurrent_claims([(run_id, "5", correlation)] * 4)
        assert_single_winner(outcomes, expected_losers=3)
        matrix_runs.append(run_id)

    rollback_acquired = threading.Event()
    follower_entered = threading.Event()
    release_rollback = threading.Event()

    class ExpectedRollback(RuntimeError):
        pass

    def rolling_back_winner() -> None:
        try:
            with _restricted_journal_transaction(c1_postgres) as connection:
                assert (
                    _claim(
                        connection,
                        "run:c1-1-rollback",
                        "6",
                        "correlation:c1-1-rollback",
                    )[0]
                    == "acquired"
                )
                rollback_acquired.set()
                assert release_rollback.wait(timeout=30)
                raise ExpectedRollback
        except ExpectedRollback:
            return

    def claim_after_rollback() -> object:
        assert rollback_acquired.wait(timeout=30)
        with _restricted_journal_transaction(c1_postgres) as connection:
            follower_entered.set()
            return _claim(
                connection,
                "run:c1-1-rollback",
                "6",
                "correlation:c1-1-rollback",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(rolling_back_winner)
        follower_future = executor.submit(claim_after_rollback)
        assert follower_entered.wait(timeout=30)
        release_rollback.set()
        winner_future.result(timeout=30)
        assert follower_future.result(timeout=30)[0] == "acquired"
    matrix_runs.append("run:c1-1-rollback")

    with pytest.raises(Exception) as repeated:
        with _restricted_journal_transaction(c1_postgres) as connection:
            _claim(
                connection,
                "run:c1-1-same",
                "2",
                "correlation:c1-1-same",
            )
    assert getattr(repeated.value, "sqlstate", None) == "40001"

    with _restricted_journal_transaction(c1_postgres) as connection:
        replay_claim = _claim(
            connection,
            "run:c1-1-replay",
            "c",
            "correlation:c1-1-replay",
        )
        assert replay_claim[0] == "acquired"
    with _restricted_journal_transaction(c1_postgres) as connection:
        connection.execute(
            f"SELECT * FROM {SCHEMA}.transition_training_execution_journal(%s,%s,'claimed',1,'failed',%s,%s)",
            (
                "run:c1-1-replay",
                "sha256:" + "c" * 64,
                "process:c1-1",
                "SYNTHETIC_TERMINAL",
            ),
        )
    with _restricted_journal_transaction(c1_postgres) as connection:
        replay = _claim(
            connection,
            "run:c1-1-replay",
            "c",
            "correlation:c1-1-replay",
        )
        assert replay[0] == "replay"

    with pytest.raises(Exception) as partial_failure:
        with _restricted_journal_transaction(c1_postgres) as connection:
            connection.execute(
                f"SELECT * FROM {SCHEMA}.claim_training_execution_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    "run:c1-1-partial",
                    "sha256:" + "d" * 64,
                    "sha256:" + "e" * 64,
                    "correlation:c1-1-partial",
                    "dataset-version:synthetic",
                    "dataset-manifest:synthetic",
                    "sha256:" + "1" * 64,
                    "sha256:" + "2" * 64,
                    "sha256:" + "3" * 64,
                    "invalid-source-commit",
                    "prerequisite-policy:c1-1",
                    "process:c1-1",
                ),
            )
    assert getattr(partial_failure.value, "sqlstate", None) == "23514"
    with _owner_verification_transaction(c1_postgres) as connection:
        assert connection.execute(
            f"SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation "
            "WHERE owner_run_id=%s",
            ("run:c1-1-partial",),
        ).fetchone() == (0,)

    with _restricted_journal_transaction(c1_postgres) as connection:
        assert (
            _claim(
                connection,
                "run:c1-1-integrity-a",
                "7",
                "correlation:c1-1-integrity-a",
            )[0]
            == "acquired"
        )
        assert (
            _claim(
                connection,
                "run:c1-1-integrity-b",
                "7",
                "correlation:c1-1-integrity-b",
            )[0]
            == "acquired"
        )
    with pytest.raises(Exception) as integrity:
        with _restricted_journal_transaction(c1_postgres) as connection:
            _claim(
                connection,
                "run:c1-1-integrity-a",
                "7",
                "correlation:c1-1-integrity-b",
            )
    assert getattr(integrity.value, "sqlstate", None) == "XX001"

    with pytest.raises(Exception) as unrelated_constraint:
        with _restricted_journal_transaction(c1_postgres) as connection:
            connection.execute(
                f"SELECT * FROM {SCHEMA}.claim_training_execution_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    "run:c1-1-invalid",
                    "not-a-fingerprint",
                    "sha256:" + "b" * 64,
                    "correlation:c1-1-invalid",
                    "dataset-version:synthetic",
                    "dataset-manifest:synthetic",
                    "sha256:" + "c" * 64,
                    "sha256:" + "d" * 64,
                    "sha256:" + "e" * 64,
                    "a" * 40,
                    "prerequisite-policy:c1-1",
                    "process:c1-1",
                ),
            )
    assert getattr(unrelated_constraint.value, "sqlstate", None) == "23514"
    assert getattr(unrelated_constraint.value.diag, "constraint_name", None) is None

    with _owner_verification_transaction(c1_postgres) as connection:
        collision_winner = connection.execute(
            f"SELECT run_id FROM {SCHEMA}.training_execution_journal "
            "WHERE orchestration_correlation_id=%s",
            ("correlation:c1-1-collision",),
        ).fetchone()
        assert collision_winner is not None
        matrix_runs.append(collision_winner[0])

        rows = connection.execute(
            f"SELECT run_id, phase, journal_version FROM {SCHEMA}.training_execution_journal "
            "WHERE run_id = ANY(%s) ORDER BY run_id",
            (matrix_runs,),
        ).fetchall()
        assert len(rows) == len(matrix_runs)
        assert all(row[1:] == ("claimed", 1) for row in rows)
        reservation_counts = connection.execute(
            f"SELECT owner_run_id, count(*), count(DISTINCT reservation_group_id) "
            f"FROM {SCHEMA}.training_execution_claim_reservation WHERE owner_run_id = ANY(%s) "
            "GROUP BY owner_run_id ORDER BY owner_run_id",
            (matrix_runs,),
        ).fetchall()
        assert len(reservation_counts) == len(matrix_runs)
        assert all(row[1:] == (3, 1) for row in reservation_counts)
        event_counts = connection.execute(
            f"SELECT run_id, count(*), min(journal_version), max(journal_version) "
            f"FROM {SCHEMA}.training_execution_phase_event WHERE run_id = ANY(%s) "
            "GROUP BY run_id ORDER BY run_id",
            (matrix_runs,),
        ).fetchall()
        assert len(event_counts) == len(matrix_runs)
        assert all(row[1:] == (1, 1, 1) for row in event_counts)

    with pytest.raises(Exception) as captured:
        with _restricted_journal_transaction(c1_postgres) as connection:
            connection.execute(
                f"UPDATE {SCHEMA}.training_execution_journal SET phase='failed'"
            )
    assert "C1_POSTGRES_PERMISSION_DENIED" in str(map_c1_postgres_error(captured.value))


@pytest.mark.integration
def test_c1_1_corruption_injection_uses_owner_setup_and_restricted_verification(
    c1_postgres: C1Fixture,
) -> None:
    run_id = "run:c1-1-corrupt"
    request = "e"
    correlation = "correlation:c1-1-corrupt"

    with c1_postgres.factory.connection() as restricted_setup:
        with restricted_setup.transaction():
            restricted_setup.execute("SET LOCAL ROLE dohalm_training_journal")
            assert (
                _claim(restricted_setup, run_id, request, correlation)[0] == "acquired"
            )

    role_inventory_sql = (
        "SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin "
        "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname"
    )
    privilege_inventory_sql = (
        "SELECT grantee, table_name, privilege_type "
        "FROM information_schema.role_table_grants "
        "WHERE table_schema=%s AND grantee = ANY(%s) "
        "UNION ALL "
        "SELECT grantee, routine_name, privilege_type "
        "FROM information_schema.role_routine_grants "
        "WHERE routine_schema=%s AND grantee = ANY(%s) "
        "ORDER BY 1, 2, 3"
    )
    runtime_roles = [
        "dohalm_training_authority_producer",
        "dohalm_training_resolver",
        "dohalm_training_journal",
    ]

    with c1_postgres.factory.connection() as owner_setup:
        with owner_setup.transaction():
            owner_setup.execute("SET LOCAL ROLE dohalm_training_owner")
            before_counts = owner_setup.execute(
                f"SELECT "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal WHERE run_id=%s), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation WHERE owner_run_id=%s), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event WHERE run_id=%s)",
                (run_id, run_id, run_id),
            ).fetchone()
            before_roles = owner_setup.execute(
                role_inventory_sql, (runtime_roles,)
            ).fetchall()
            before_privileges = owner_setup.execute(
                privilege_inventory_sql,
                (SCHEMA, runtime_roles, SCHEMA, runtime_roles),
            ).fetchall()
        try:
            with owner_setup.transaction():
                owner_setup.execute("SET LOCAL ROLE dohalm_training_owner")
                owner_setup.execute(
                    f"ALTER TABLE {SCHEMA}.training_execution_claim_reservation "
                    "DISABLE TRIGGER training_execution_claim_reservation_immutable"
                )
                deleted = owner_setup.execute(
                    f"DELETE FROM {SCHEMA}.training_execution_claim_reservation "
                    "WHERE owner_run_id=%s AND identity_kind='run_request_fingerprint'",
                    (run_id,),
                ).rowcount
                assert deleted == 1
                owner_setup.execute(
                    f"ALTER TABLE {SCHEMA}.training_execution_claim_reservation "
                    "ENABLE TRIGGER training_execution_claim_reservation_immutable"
                )
        finally:
            with owner_setup.transaction():
                owner_setup.execute("SET LOCAL ROLE dohalm_training_owner")
                owner_setup.execute(
                    f"ALTER TABLE {SCHEMA}.training_execution_claim_reservation "
                    "ENABLE TRIGGER training_execution_claim_reservation_immutable"
                )

    with c1_postgres.factory.connection() as restricted_verification:
        with pytest.raises(Exception) as corrupted:
            with restricted_verification.transaction():
                restricted_verification.execute(
                    "SET LOCAL ROLE dohalm_training_journal"
                )
                _claim(restricted_verification, run_id, request, correlation)
    assert getattr(corrupted.value, "sqlstate", None) == "XX001"

    with c1_postgres.factory.connection() as owner_verification:
        with owner_verification.transaction():
            owner_verification.execute("SET LOCAL ROLE dohalm_training_owner")
            after_counts = owner_verification.execute(
                f"SELECT "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal WHERE run_id=%s), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation WHERE owner_run_id=%s), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event WHERE run_id=%s)",
                (run_id, run_id, run_id),
            ).fetchone()
            journal_state = owner_verification.execute(
                f"SELECT phase, journal_version FROM {SCHEMA}.training_execution_journal "
                "WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            trigger_state = owner_verification.execute(
                "SELECT tgenabled FROM pg_trigger "
                "WHERE tgname='training_execution_claim_reservation_immutable' "
                "AND tgrelid=%s::regclass",
                (f"{SCHEMA}.training_execution_claim_reservation",),
            ).fetchone()
            after_roles = owner_verification.execute(
                role_inventory_sql, (runtime_roles,)
            ).fetchall()
            after_privileges = owner_verification.execute(
                privilege_inventory_sql,
                (SCHEMA, runtime_roles, SCHEMA, runtime_roles),
            ).fetchall()

    assert before_counts == (1, 3, 1)
    assert after_counts == (1, 2, 1)
    assert journal_state == ("claimed", 1)
    assert trigger_state == ("O",)
    assert after_roles == before_roles
    assert after_privileges == before_privileges


@pytest.mark.integration
def test_c1_1_journal_expected_version_cas_rollback_and_manual_reconciliation(
    c1_postgres: C1Fixture,
) -> None:
    run_id = "run:c1-1-cas"
    fingerprint = "sha256:" + "1" * 64
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            claim = _claim(connection, run_id, "1", "correlation:c1-1-cas")
            assert claim[:5] == ("acquired", run_id, fingerprint, "claimed", 1)
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            resolved = connection.execute(
                f"SELECT * FROM {SCHEMA}.transition_training_execution_journal(%s,%s,'claimed',1,'resolved',%s)",
                (run_id, fingerprint, "process:c1-1"),
            ).fetchone()
            assert resolved[2:4] == ("resolved", 2)
        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE dohalm_training_journal")
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.transition_training_execution_journal(%s,%s,'claimed',1,'resolved',%s)",
                    (run_id, fingerprint, "process:c1-1"),
                )
        assert "journal transition conflict" in str(captured.value)
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            manual = connection.execute(
                f"SELECT * FROM {SCHEMA}.transition_training_execution_journal(%s,%s,'resolved',2,'manual_reconciliation_required',%s,%s)",
                (run_id, fingerprint, "process:restart", "COMMIT_OUTCOME_AMBIGUOUS"),
            ).fetchone()
            assert manual[2:] == (
                "manual_reconciliation_required",
                3,
                False,
                True,
                "COMMIT_OUTCOME_AMBIGUOUS",
            )
        events = connection.execute(
            f"SELECT from_phase, to_phase, journal_version, reason_code FROM {SCHEMA}.training_execution_phase_event "
            "WHERE run_id=%s ORDER BY journal_version",
            (run_id,),
        ).fetchall()
        assert events == [
            (None, "claimed", 1, None),
            ("claimed", "resolved", 2, None),
            (
                "resolved",
                "manual_reconciliation_required",
                3,
                "COMMIT_OUTCOME_AMBIGUOUS",
            ),
        ]


@pytest.mark.integration
def test_c1_1_upgrade_backfills_preexisting_journal(
    c1_postgres: C1Fixture, tmp_path: Path
) -> None:
    upgrade_database = f"dohalm_c1_upgrade_{c1_postgres.correlation[:8]}"
    upgrade_factory = C1PostgresConnectionFactory(
        replace(c1_postgres.settings, database=upgrade_database)
    )
    migration_root = Path("src/postgres_migrations")
    migration_0001 = migration_root / "0001_training_authority_and_journal.sql"
    only_0001 = tmp_path / "only-0001"
    only_0001.mkdir()
    (only_0001 / migration_0001.name).write_bytes(migration_0001.read_bytes())
    run_id = "run:c1-1-upgrade-existing"
    request_fingerprint = "sha256:" + "8" * 64
    correlation = "correlation:c1-1-upgrade-existing"

    _docker(
        "exec",
        c1_postgres.container,
        "createdb",
        f"--username={c1_postgres.settings.user}",
        upgrade_database,
    )
    try:
        with upgrade_factory.connection() as connection:
            assert apply_c1_migrations(connection, directory=only_0001) == (1,)
        with upgrade_factory.connection() as owner_setup:
            with owner_setup.transaction():
                owner_setup.execute("SET LOCAL ROLE dohalm_training_owner")
                owner_setup.execute(
                    f"INSERT INTO {SCHEMA}.training_execution_journal "
                    "(run_id, request_fingerprint, intent_fingerprint, "
                    "orchestration_correlation_id, dataset_version_id, dataset_manifest_id, "
                    "dataset_pair_fingerprint, config_fingerprint, readiness_fingerprint, "
                    "source_commit, prerequisite_resolution_policy_reference, "
                    "phase, journal_version, process_boundary_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'claimed',1,%s)",
                    (
                        run_id,
                        request_fingerprint,
                        "sha256:" + "9" * 64,
                        correlation,
                        "dataset-version:upgrade-synthetic",
                        "dataset-manifest:upgrade-synthetic",
                        "sha256:" + "a" * 64,
                        "sha256:" + "b" * 64,
                        "sha256:" + "c" * 64,
                        "d" * 40,
                        "prerequisite-policy:c1-1-upgrade",
                        "process:c1-1-upgrade",
                    ),
                )
                owner_setup.execute(
                    f"INSERT INTO {SCHEMA}.training_execution_phase_event "
                    "(event_id, run_id, request_fingerprint, journal_version, from_phase, "
                    "to_phase, process_boundary_id) "
                    "VALUES (%s,%s,%s,1,NULL,'claimed',%s)",
                    (uuid.uuid4(), run_id, request_fingerprint, "process:c1-1-upgrade"),
                )
        with upgrade_factory.connection() as connection:
            assert apply_c1_migrations(connection) == (2,)
            migrations = connection.execute(
                f"SELECT version, name, sha256 FROM {SCHEMA}.schema_migration ORDER BY version"
            ).fetchall()
            journal = connection.execute(
                f"SELECT run_id, request_fingerprint, orchestration_correlation_id, "
                "phase, journal_version, process_boundary_id, reservation_group_id "
                f"FROM {SCHEMA}.training_execution_journal WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            reservations = connection.execute(
                f"SELECT identity_kind, owner_run_id, owner_request_fingerprint, "
                "owner_orchestration_correlation_id, reservation_group_id "
                f"FROM {SCHEMA}.training_execution_claim_reservation "
                "WHERE owner_run_id=%s ORDER BY identity_kind",
                (run_id,),
            ).fetchall()
            event = connection.execute(
                f"SELECT run_id, request_fingerprint, journal_version, from_phase, "
                f"to_phase, process_boundary_id FROM {SCHEMA}.training_execution_phase_event "
                "WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            invariant_failures = connection.execute(
                f"SELECT "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation r "
                f"LEFT JOIN {SCHEMA}.training_execution_journal j "
                "ON j.reservation_group_id=r.reservation_group_id "
                "WHERE j.run_id IS NULL), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal j "
                f"LEFT JOIN {SCHEMA}.training_execution_claim_reservation r "
                "ON r.reservation_group_id=j.reservation_group_id "
                "GROUP BY j.run_id HAVING count(r.*) <> 3 LIMIT 1), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation "
                "GROUP BY reservation_group_id "
                "HAVING count(DISTINCT owner_run_id) <> 1 LIMIT 1)"
            ).fetchone()

        assert migrations == [
            (
                1,
                migration_0001.name,
                hashlib.sha256(migration_0001.read_bytes()).hexdigest(),
            ),
            (
                2,
                "0002_c1_1_prerequisite_restricted_operations.sql",
                hashlib.sha256(
                    (
                        migration_root
                        / "0002_c1_1_prerequisite_restricted_operations.sql"
                    ).read_bytes()
                ).hexdigest(),
            ),
        ]
        assert journal[:6] == (
            run_id,
            request_fingerprint,
            correlation,
            "claimed",
            1,
            "process:c1-1-upgrade",
        )
        assert [row[0] for row in reservations] == [
            "orchestration_correlation_id",
            "run_id",
            "run_request_fingerprint",
        ]
        assert all(
            row[1:4] == (run_id, request_fingerprint, correlation)
            for row in reservations
        )
        assert all(row[4] == journal[6] for row in reservations)
        assert event == (
            run_id,
            request_fingerprint,
            1,
            None,
            "claimed",
            "process:c1-1-upgrade",
        )
        assert invariant_failures == (0, None, None)
    finally:
        _docker(
            "exec",
            c1_postgres.container,
            "dropdb",
            "--if-exists",
            f"--username={c1_postgres.settings.user}",
            upgrade_database,
            check=False,
        )


def _canonical_restore_inventory(connection: object) -> tuple[object, ...]:
    columns = connection.execute(
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema=%s "
        "ORDER BY table_name, ordinal_position",
        (SCHEMA,),
    ).fetchall()
    constraints = connection.execute(
        "SELECT conrelid::regclass::text, conname, contype, condeferrable, condeferred "
        "FROM pg_constraint WHERE connamespace=%s::regnamespace ORDER BY 1, 2",
        (SCHEMA,),
    ).fetchall()
    triggers = connection.execute(
        "SELECT tgrelid::regclass::text, tgname, tgenabled "
        "FROM pg_trigger WHERE tgrelid IN "
        "(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s) AND NOT tgisinternal ORDER BY 1, 2",
        (SCHEMA,),
    ).fetchall()
    functions = connection.execute(
        "SELECT p.oid::regprocedure::text, p.prosecdef, p.provolatile, p.proowner::regrole::text "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname=%s ORDER BY 1",
        (SCHEMA,),
    ).fetchall()
    grants = connection.execute(
        "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE table_schema=%s "
        "UNION ALL SELECT grantee, routine_name, privilege_type "
        "FROM information_schema.role_routine_grants WHERE routine_schema=%s "
        "ORDER BY 1, 2, 3",
        (SCHEMA, SCHEMA),
    ).fetchall()
    data_counts = connection.execute(
        f"SELECT "
        f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal), "
        f"(SELECT count(*) FROM {SCHEMA}.training_execution_claim_reservation), "
        f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event)"
    ).fetchone()
    return columns, constraints, triggers, functions, grants, data_counts


@dataclass(frozen=True)
class RestoreClaimInput:
    run_id: str
    request_fingerprint: str
    intent_fingerprint: str
    orchestration_correlation_id: str
    dataset_version_id: str
    dataset_manifest_id: str
    dataset_pair_fingerprint: str
    config_fingerprint: str
    readiness_fingerprint: str
    source_commit: str
    prerequisite_policy_reference: str
    process_boundary_id: str
    next_phase: str


@dataclass(frozen=True)
class JournalClaimReceipt:
    status: str
    run_id: str
    request_fingerprint: str
    phase: str
    version: int
    backend_entered: bool
    reconciliation_required: bool
    reconciliation_reason_code: str | None
    orchestration_correlation_id: str
    process_boundary_id: str


@dataclass(frozen=True)
class JournalTransitionReceipt:
    run_id: str
    request_fingerprint: str
    phase: str
    version: int
    backend_entered: bool
    reconciliation_required: bool
    reconciliation_reason_code: str | None


@dataclass(frozen=True)
class RestoreSmokeResult:
    claim: JournalClaimReceipt
    transition: JournalTransitionReceipt
    read: JournalTransitionReceipt
    reservation_group_id: uuid.UUID
    reservation_count: int
    event_count: int

    def contract_projection(self) -> tuple[object, ...]:
        return (
            self.claim.status,
            self.claim.phase,
            self.claim.version,
            self.transition.phase,
            self.transition.version,
            self.read.phase,
            self.read.version,
            self.reservation_count,
            self.event_count,
        )


def _restore_claim_input(scope: str, fingerprint_character: str) -> RestoreClaimInput:
    return RestoreClaimInput(
        run_id=f"run:c1-1-restore-{scope}",
        request_fingerprint="sha256:" + fingerprint_character * 64,
        intent_fingerprint="sha256:" + "b" * 64,
        orchestration_correlation_id=f"correlation:c1-1-restore-{scope}",
        dataset_version_id="dataset-version:restore-synthetic",
        dataset_manifest_id="dataset-manifest:restore-synthetic",
        dataset_pair_fingerprint="sha256:" + "c" * 64,
        config_fingerprint="sha256:" + "d" * 64,
        readiness_fingerprint="sha256:" + "e" * 64,
        source_commit="a" * 40,
        prerequisite_policy_reference="prerequisite-policy:c1-1-restore",
        process_boundary_id=f"process:c1-1-restore-{scope}",
        next_phase="resolved",
    )


def _fetch_named(
    cursor: object, expected_columns: tuple[str, ...]
) -> dict[str, object]:
    actual_columns = tuple(column.name for column in cursor.description or ())
    assert actual_columns == expected_columns
    row = cursor.fetchone()
    assert row is not None
    return dict(zip(actual_columns, row, strict=True))


def _exercise_restore_smoke(
    factory: C1PostgresConnectionFactory, claim_input: RestoreClaimInput
) -> RestoreSmokeResult:
    claim_columns = (
        "claim_status",
        "claimed_run_id",
        "claimed_request_fingerprint",
        "claimed_phase",
        "claimed_journal_version",
        "claimed_backend_entered",
        "claimed_reconciliation_required",
        "claimed_reconciliation_reason_code",
    )
    transition_columns = (
        "transitioned_run_id",
        "transitioned_request_fingerprint",
        "transitioned_phase",
        "transitioned_journal_version",
        "transitioned_backend_entered",
        "transitioned_reconciliation_required",
        "transitioned_reconciliation_reason_code",
    )
    read_columns = (
        "journal_run_id",
        "journal_request_fingerprint",
        "journal_phase",
        "journal_record_version",
        "journal_backend_entered",
        "journal_reconciliation_required",
        "journal_reconciliation_reason_code",
    )

    with factory.connection() as runtime_connection:
        with runtime_connection.transaction():
            runtime_connection.execute("SET LOCAL ROLE dohalm_training_journal")
            claim_row = _fetch_named(
                runtime_connection.execute(
                    f"SELECT {', '.join(claim_columns)} "
                    f"FROM {SCHEMA}.claim_training_execution_journal"
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        claim_input.run_id,
                        claim_input.request_fingerprint,
                        claim_input.intent_fingerprint,
                        claim_input.orchestration_correlation_id,
                        claim_input.dataset_version_id,
                        claim_input.dataset_manifest_id,
                        claim_input.dataset_pair_fingerprint,
                        claim_input.config_fingerprint,
                        claim_input.readiness_fingerprint,
                        claim_input.source_commit,
                        claim_input.prerequisite_policy_reference,
                        claim_input.process_boundary_id,
                    ),
                ),
                claim_columns,
            )
        claim = JournalClaimReceipt(
            status=str(claim_row["claim_status"]),
            run_id=str(claim_row["claimed_run_id"]),
            request_fingerprint=str(claim_row["claimed_request_fingerprint"]),
            phase=str(claim_row["claimed_phase"]),
            version=int(claim_row["claimed_journal_version"]),
            backend_entered=bool(claim_row["claimed_backend_entered"]),
            reconciliation_required=bool(claim_row["claimed_reconciliation_required"]),
            reconciliation_reason_code=claim_row["claimed_reconciliation_reason_code"],
            orchestration_correlation_id=claim_input.orchestration_correlation_id,
            process_boundary_id=claim_input.process_boundary_id,
        )
        assert claim.status == "acquired"
        assert claim.run_id == claim_input.run_id
        assert claim.request_fingerprint == claim_input.request_fingerprint
        assert claim.process_boundary_id == claim_input.process_boundary_id

        transition_parameters = (
            claim.run_id,
            claim.request_fingerprint,
            claim.phase,
            claim.version,
            claim_input.next_phase,
            claim.process_boundary_id,
        )
        assert transition_parameters[:2] == (claim.run_id, claim.request_fingerprint)
        assert transition_parameters[2:4] == (claim.phase, claim.version)
        assert transition_parameters[5] == claim.process_boundary_id
        with runtime_connection.transaction():
            runtime_connection.execute("SET LOCAL ROLE dohalm_training_journal")
            transition_row = _fetch_named(
                runtime_connection.execute(
                    f"SELECT {', '.join(transition_columns)} "
                    f"FROM {SCHEMA}.transition_training_execution_journal"
                    "(%s,%s,%s,%s,%s,%s)",
                    transition_parameters,
                ),
                transition_columns,
            )
        transition = JournalTransitionReceipt(
            run_id=str(transition_row["transitioned_run_id"]),
            request_fingerprint=str(transition_row["transitioned_request_fingerprint"]),
            phase=str(transition_row["transitioned_phase"]),
            version=int(transition_row["transitioned_journal_version"]),
            backend_entered=bool(transition_row["transitioned_backend_entered"]),
            reconciliation_required=bool(
                transition_row["transitioned_reconciliation_required"]
            ),
            reconciliation_reason_code=transition_row[
                "transitioned_reconciliation_reason_code"
            ],
        )
        assert transition.run_id == claim.run_id
        assert transition.request_fingerprint == claim.request_fingerprint
        assert transition.phase == claim_input.next_phase
        assert transition.version == claim.version + 1

        with runtime_connection.transaction():
            runtime_connection.execute("SET LOCAL ROLE dohalm_training_journal")
            read_row = _fetch_named(
                runtime_connection.execute(
                    f"SELECT {', '.join(read_columns)} "
                    f"FROM {SCHEMA}.read_training_execution_journal(%s)",
                    (claim.run_id,),
                ),
                read_columns,
            )
        read = JournalTransitionReceipt(
            run_id=str(read_row["journal_run_id"]),
            request_fingerprint=str(read_row["journal_request_fingerprint"]),
            phase=str(read_row["journal_phase"]),
            version=int(read_row["journal_record_version"]),
            backend_entered=bool(read_row["journal_backend_entered"]),
            reconciliation_required=bool(read_row["journal_reconciliation_required"]),
            reconciliation_reason_code=read_row["journal_reconciliation_reason_code"],
        )
        assert read == transition

    with factory.connection() as verification_connection:
        journal = verification_connection.execute(
            f"SELECT run_id, request_fingerprint, orchestration_correlation_id, "
            f"process_boundary_id, phase, journal_version, reservation_group_id "
            f"FROM {SCHEMA}.training_execution_journal WHERE run_id=%s",
            (claim.run_id,),
        ).fetchone()
        reservations = verification_connection.execute(
            f"SELECT identity_kind, reservation_group_id, owner_run_id, "
            f"owner_request_fingerprint, owner_orchestration_correlation_id "
            f"FROM {SCHEMA}.training_execution_claim_reservation "
            "WHERE owner_run_id=%s ORDER BY identity_kind",
            (claim.run_id,),
        ).fetchall()
        events = verification_connection.execute(
            f"SELECT event_id, run_id, request_fingerprint, journal_version, "
            f"from_phase, to_phase, process_boundary_id "
            f"FROM {SCHEMA}.training_execution_phase_event "
            "WHERE run_id=%s ORDER BY journal_version",
            (claim.run_id,),
        ).fetchall()

    assert journal is not None
    assert journal[:6] == (
        claim.run_id,
        claim.request_fingerprint,
        claim.orchestration_correlation_id,
        claim.process_boundary_id,
        transition.phase,
        transition.version,
    )
    reservation_group_id = journal[6]
    assert [reservation[0] for reservation in reservations] == [
        "orchestration_correlation_id",
        "run_id",
        "run_request_fingerprint",
    ]
    assert all(
        reservation[1:]
        == (
            reservation_group_id,
            claim.run_id,
            claim.request_fingerprint,
            claim.orchestration_correlation_id,
        )
        for reservation in reservations
    )
    assert len(events) == 2
    assert len({event[0] for event in events}) == 2
    assert [event[1:] for event in events] == [
        (
            claim.run_id,
            claim.request_fingerprint,
            claim.version,
            None,
            claim.phase,
            claim.process_boundary_id,
        ),
        (
            claim.run_id,
            claim.request_fingerprint,
            transition.version,
            claim.phase,
            transition.phase,
            claim.process_boundary_id,
        ),
    ]
    return RestoreSmokeResult(
        claim=claim,
        transition=transition,
        read=read,
        reservation_group_id=reservation_group_id,
        reservation_count=len(reservations),
        event_count=len(events),
    )


@pytest.mark.integration
def test_logical_restore_preserves_migration_contract(c1_postgres: C1Fixture) -> None:
    restored_database = f"dohalm_c1_restore_{c1_postgres.correlation[:8]}"
    dump_path = f"/tmp/dohalm-c1-{c1_postgres.correlation[:12]}.dump"
    source_result = _exercise_restore_smoke(
        c1_postgres.factory, _restore_claim_input("source", "5")
    )
    with c1_postgres.factory.connection() as source_connection:
        source_inventory = _canonical_restore_inventory(source_connection)
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
            assert _canonical_restore_inventory(connection) == source_inventory
            rows = connection.execute(
                f"SELECT version, name, sha256 FROM {SCHEMA}.schema_migration"
            ).fetchall()
            assert [(row[0], row[1]) for row in rows] == [
                (1, "0001_training_authority_and_journal.sql"),
                (2, "0002_c1_1_prerequisite_restricted_operations.sql"),
            ]
            assert all(len(row[2]) == 64 for row in rows)
            assert apply_c1_migrations(connection) == ()
        restored_result = _exercise_restore_smoke(
            restore_factory, _restore_claim_input("restored", "6")
        )
        assert (
            restored_result.contract_projection() == source_result.contract_projection()
        )
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
