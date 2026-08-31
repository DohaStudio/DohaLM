from __future__ import annotations

import hashlib
import json
import platform
import re
import secrets
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import pytest

from src.postgres_c1 import (
    C1PostgresConnectionFactory,
    C1PostgresSettings,
    apply_c1_migrations,
    map_c1_postgres_error,
)

if TYPE_CHECKING:
    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
    )
    from src.data.postgres_dataset_review_authority import (
        PostgresDatasetReviewAuthority,
    )


IMAGE = (
    "postgres:16.15-alpine@"
    "sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571"
)
LABEL_KEY = "com.dohastudio.c1.correlation"
SCHEMA = "dohalm_training_v1"
POSTGRES_READINESS_TIMEOUT_SECONDS = 30.0
POSTGRES_READINESS_POLL_INTERVAL_SECONDS = 0.25
POSTGRES_DIAGNOSTIC_LOG_TAIL_LINES = 100
_POSTGRES_DSN = re.compile(r"postgres(?:ql)?://[^\s]+", re.IGNORECASE)
_SENSITIVE_FIELD = re.compile(r"(?i)((?:password|secret|token)\s*[=:]\s*)[^\s,;]+")
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]+\b")


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _wait_healthy(
    container: str,
    *,
    docker: Callable[..., subprocess.CompletedProcess[str]] = _docker,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 90.0,
    poll_interval_seconds: float = 1.0,
    redactions: tuple[str, ...] = (),
) -> None:
    started_at = clock()
    deadline = started_at + timeout_seconds
    attempts = 0
    last_status = "unknown"
    while clock() < deadline:
        attempts += 1
        result = docker(
            "inspect", "--format", "{{.State.Health.Status}}", container, check=False
        )
        last_status = result.stdout.strip() or f"inspect_exit_{result.returncode}"
        if result.returncode == 0 and last_status == "healthy":
            return
        sleep(poll_interval_seconds)
    now = clock()
    diagnostics = _container_diagnostics(
        container, docker=docker, redactions=redactions
    )
    suffix = "" if not diagnostics else "\n" + "\n".join(diagnostics)
    raise AssertionError(
        "isolated PostgreSQL fixture did not become healthy; "
        "POSTGRES_READINESS_DIAGNOSTIC phase=docker_health "
        f"attempts={attempts} elapsed_seconds={max(0.0, now - started_at):.2f} "
        f"timeout_seconds={timeout_seconds:g} "
        f"poll_interval_seconds={poll_interval_seconds:g} "
        f"exception_type=none sqlstate=none last_health_status={last_status}{suffix}"
    )


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


def _is_retryable_postgres_readiness_error(error: BaseException) -> bool:
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str):
        return sqlstate.startswith("08") or sqlstate == "57P03"
    try:
        from psycopg import OperationalError
    except ImportError:
        return False
    return isinstance(error, OperationalError)


def _sanitize_diagnostic(value: object, redactions: tuple[str, ...]) -> str:
    text = str(value)
    for secret in redactions:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _POSTGRES_DSN.sub("postgresql://[REDACTED]", text)
    text = _SENSITIVE_FIELD.sub(r"\1[REDACTED]", text)
    return _GITHUB_TOKEN.sub("[REDACTED]", text)


def _container_diagnostics(
    container: str,
    *,
    docker: Callable[..., subprocess.CompletedProcess[str]] = _docker,
    redactions: tuple[str, ...] = (),
) -> tuple[str, ...]:
    lines: list[str] = []
    try:
        inspected = json.loads(docker("inspect", container).stdout)[0]
        state = inspected.get("State", {})
        health = state.get("Health") or {}
        bindings = (inspected.get("NetworkSettings", {}).get("Ports", {}) or {}).get(
            "5432/tcp"
        )
        published = "none"
        if isinstance(bindings, list) and len(bindings) == 1:
            binding = bindings[0]
            published = f"{binding.get('HostIp', 'unknown')}:{binding.get('HostPort', 'unknown')}"
        correlation = (inspected.get("Config", {}).get("Labels", {}) or {}).get(
            LABEL_KEY, "none"
        )
        lines.append(
            "POSTGRES_CONTAINER_DIAGNOSTIC "
            f"container_id={str(inspected.get('Id', 'unknown'))[:12]} "
            f"container_status={state.get('Status', 'unknown')} "
            f"running={str(state.get('Running', False)).lower()} "
            f"exit_code={state.get('ExitCode', 'unknown')} "
            f"health_status={health.get('Status', 'none')} "
            f"published_binding={published} container_port=5432 "
            f"ownership_correlation={correlation}"
        )
    except Exception as error:
        lines.append(
            f"POSTGRES_CONTAINER_DIAGNOSTIC inspect_warning={type(error).__name__}"
        )
    try:
        result = docker(
            "logs",
            "--tail",
            str(POSTGRES_DIAGNOSTIC_LOG_TAIL_LINES),
            container,
            check=False,
        )
        raw_lines = (result.stdout + "\n" + result.stderr).splitlines()
        bounded = raw_lines[-POSTGRES_DIAGNOSTIC_LOG_TAIL_LINES:]
        lines.append(
            "POSTGRES_LOG_TAIL_DIAGNOSTIC "
            f"tail_limit={POSTGRES_DIAGNOSTIC_LOG_TAIL_LINES} lines={len(bounded)}"
        )
        lines.extend(
            "POSTGRES_LOG_TAIL " + _sanitize_diagnostic(line, redactions)
            for line in bounded
        )
    except Exception as error:
        lines.append(
            f"POSTGRES_LOG_TAIL_DIAGNOSTIC collection_warning={type(error).__name__}"
        )
    return tuple(lines)


def _wait_for_postgres_connection(
    settings: C1PostgresSettings,
    *,
    connect: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = POSTGRES_READINESS_TIMEOUT_SECONDS,
    poll_interval_seconds: float = POSTGRES_READINESS_POLL_INTERVAL_SECONDS,
    terminal_diagnostics: Callable[[], tuple[str, ...]] | None = None,
) -> None:
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("PostgreSQL readiness timing must be positive")
    if connect is None:
        import psycopg

        connect = psycopg.connect

    started_at = clock()
    deadline = started_at + timeout_seconds
    attempts = 0
    while True:
        attempts += 1
        try:
            with connect(
                host=settings.host,
                port=settings.port,
                dbname=settings.database,
                user=settings.user,
                password=settings.password,
                connect_timeout=5,
                options="-c timezone=UTC -c client_encoding=UTF8",
                autocommit=True,
            ) as connection:
                assert connection.execute("SELECT 1").fetchone() == (1,)
            return
        except Exception as error:
            if not _is_retryable_postgres_readiness_error(error):
                raise
            now = clock()
            if now >= deadline:
                error_type = type(error).__name__
                sqlstate = getattr(error, "sqlstate", None)
                diagnostic_lines: tuple[str, ...] = ()
                if terminal_diagnostics is not None:
                    try:
                        diagnostic_lines = terminal_diagnostics()
                    except Exception as diagnostic_error:
                        diagnostic_lines = (
                            "POSTGRES_CONTAINER_DIAGNOSTIC "
                            f"collection_warning={type(diagnostic_error).__name__}",
                        )
                suffix = (
                    "" if not diagnostic_lines else "\n" + "\n".join(diagnostic_lines)
                )
                raise AssertionError(
                    "isolated PostgreSQL host readiness probe timed out after "
                    f"{timeout_seconds:g}s; POSTGRES_READINESS_DIAGNOSTIC "
                    f"attempts={attempts} elapsed_seconds={max(0.0, now - started_at):.2f} "
                    f"timeout_seconds={timeout_seconds:g} "
                    f"poll_interval_seconds={poll_interval_seconds:g} "
                    f"exception_type={error_type} sqlstate={sqlstate or 'none'} "
                    f"host=loopback published_port={settings.port} container_port=5432"
                    f"{suffix}"
                ) from None
            sleep(min(poll_interval_seconds, deadline - now))


class _ReadinessProbeError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        super().__init__("synthetic readiness failure")


class _ReadinessProbeResult:
    def __init__(self, queries: list[str]) -> None:
        self._queries = queries

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str) -> _ReadinessProbeResult:
        self._queries.append(query)
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


class _ReadinessProbeConnector:
    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[dict[str, object]] = []
        self.queries: list[str] = []

    def __call__(self, **kwargs: object) -> _ReadinessProbeResult:
        self.calls.append(kwargs)
        outcome = next(self._outcomes)
        if outcome is not None:
            raise outcome
        return _ReadinessProbeResult(self.queries)


class _ReadinessProbeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _readiness_settings() -> C1PostgresSettings:
    return C1PostgresSettings(
        environment="local_ephemeral",
        host="127.0.0.1",
        port=54321,
        database="dohalm_c1_readiness",
        user="dohalm_c1_readiness_owner",
        password="synthetic-readiness-password",
    )


def test_postgres_readiness_retries_only_transient_failures_before_query() -> None:
    from psycopg import OperationalError

    connector = _ReadinessProbeConnector(
        [
            OperationalError("synthetic connection refusal"),
            _ReadinessProbeError("57P03"),
            None,
        ]
    )
    clock = _ReadinessProbeClock()

    _wait_for_postgres_connection(
        _readiness_settings(),
        connect=connector,
        clock=clock,
        sleep=clock.sleep,
        timeout_seconds=1.0,
        poll_interval_seconds=0.25,
    )

    assert len(connector.calls) == 3
    assert connector.queries == ["SELECT 1"]
    assert clock.sleeps == [0.25, 0.25]
    assert connector.calls[-1]["user"] == "dohalm_c1_readiness_owner"
    assert connector.calls[-1]["autocommit"] is True


def test_postgres_readiness_fails_authentication_without_retry() -> None:
    authentication_error = _ReadinessProbeError("28P01")
    connector = _ReadinessProbeConnector([authentication_error])
    clock = _ReadinessProbeClock()

    with pytest.raises(_ReadinessProbeError) as captured:
        _wait_for_postgres_connection(
            _readiness_settings(),
            connect=connector,
            clock=clock,
            sleep=clock.sleep,
        )

    assert captured.value is authentication_error
    assert len(connector.calls) == 1
    assert clock.sleeps == []


def test_postgres_readiness_deadline_is_bounded_and_sanitized() -> None:
    connector = _ReadinessProbeConnector(
        [
            _ReadinessProbeError("08006"),
            _ReadinessProbeError("08006"),
            _ReadinessProbeError("08006"),
        ]
    )
    clock = _ReadinessProbeClock()
    secret = "super-secret-test-password"

    def diagnostic_docker(
        *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        del check
        if arguments[0] == "inspect":
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "a" * 64,
                            "State": {
                                "Status": "running",
                                "Running": True,
                                "ExitCode": 0,
                                "Health": {"Status": "unhealthy"},
                            },
                            "NetworkSettings": {
                                "Ports": {
                                    "5432/tcp": [
                                        {"HostIp": "127.0.0.1", "HostPort": "54321"}
                                    ]
                                }
                            },
                            "Config": {"Labels": {LABEL_KEY: "synthetic-correlation"}},
                        }
                    ]
                ),
                stderr="",
            )
        assert arguments[:3] == ("logs", "--tail", "100")
        lines = [f"postgres-log-{index}" for index in range(104)]
        lines.append(
            f"password={secret} token=super-secret-test-token "
            f"postgresql://owner:{secret}@127.0.0.1/db ghp_SyntheticTokenValue"
        )
        return subprocess.CompletedProcess(
            arguments, 0, stdout="\n".join(lines), stderr=""
        )

    diagnostics = _container_diagnostics(
        "synthetic-container",
        docker=diagnostic_docker,
        redactions=(secret,),
    )

    with pytest.raises(
        AssertionError, match="host readiness probe timed out"
    ) as captured:
        _wait_for_postgres_connection(
            _readiness_settings(),
            connect=connector,
            clock=clock,
            sleep=clock.sleep,
            timeout_seconds=0.5,
            poll_interval_seconds=0.25,
            terminal_diagnostics=lambda: diagnostics,
        )

    assert len(connector.calls) == 3
    assert clock.sleeps == [0.25, 0.25]
    message = str(captured.value)
    assert "POSTGRES_READINESS_DIAGNOSTIC attempts=3 elapsed_seconds=0.50" in message
    assert "exception_type=_ReadinessProbeError sqlstate=08006" in message
    assert "published_port=54321 container_port=5432" in message
    assert "health_status=unhealthy" in message
    assert "tail_limit=100 lines=100" in message
    assert "postgres-log-0" not in message
    assert secret not in message
    assert "super-secret-test-token" not in message
    assert "ghp_SyntheticTokenValue" not in message
    assert "postgresql://owner" not in message

    health_clock = _ReadinessProbeClock()

    def unhealthy_docker(
        *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ("inspect", "--format"):
            return subprocess.CompletedProcess(
                arguments, 0, stdout="starting\n", stderr=""
            )
        return diagnostic_docker(*arguments, check=check)

    with pytest.raises(AssertionError, match="phase=docker_health") as unhealthy:
        _wait_healthy(
            "synthetic-container",
            docker=unhealthy_docker,
            clock=health_clock,
            sleep=health_clock.sleep,
            timeout_seconds=2.0,
            poll_interval_seconds=1.0,
            redactions=(secret,),
        )
    health_message = str(unhealthy.value)
    assert "attempts=2 elapsed_seconds=2.00" in health_message
    assert "timeout_seconds=2 poll_interval_seconds=1" in health_message
    assert "last_health_status=starting" in health_message
    assert secret not in health_message

    def unavailable_docker(
        *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        del arguments, check
        raise subprocess.CalledProcessError(1, "docker")

    warnings = _container_diagnostics("synthetic-container", docker=unavailable_docker)
    assert warnings == (
        "POSTGRES_CONTAINER_DIAGNOSTIC inspect_warning=CalledProcessError",
        "POSTGRES_LOG_TAIL_DIAGNOSTIC collection_warning=CalledProcessError",
    )

    isolated_connector = _ReadinessProbeConnector(
        [_ReadinessProbeError("08006"), _ReadinessProbeError("08006")]
    )
    isolated_clock = _ReadinessProbeClock()
    with pytest.raises(
        AssertionError, match="POSTGRES_READINESS_DIAGNOSTIC"
    ) as isolated:
        _wait_for_postgres_connection(
            _readiness_settings(),
            connect=isolated_connector,
            clock=isolated_clock,
            sleep=isolated_clock.sleep,
            timeout_seconds=0.25,
            poll_interval_seconds=0.25,
            terminal_diagnostics=lambda: (_ for _ in ()).throw(
                RuntimeError("diagnostic collector unavailable")
            ),
        )
    assert "collection_warning=RuntimeError" in str(isolated.value)


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
        _wait_healthy(container, redactions=(password,))
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
        _wait_for_postgres_connection(
            settings,
            terminal_diagnostics=lambda: _container_diagnostics(
                container, redactions=(password,)
            ),
        )
        factory = C1PostgresConnectionFactory(settings)

        def migrate() -> tuple[int, ...]:
            with factory.connection() as connection:
                return apply_c1_migrations(connection)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: migrate(), range(2)))
        assert sorted(results, key=len) == [(), (1, 2, 3, 4, 5)]
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
            resources = residue.stdout.split()
            assert not resources, (
                "POSTGRES_CLEANUP_RESIDUE "
                f"label={LABEL_KEY}={correlation} {noun}s={','.join(resources)}"
            )


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


@pytest.mark.integration
def test_c1_2_typed_snapshots_and_complete_journal_contract(
    c1_postgres: C1Fixture, c1_1_authority_mapping: dict[str, object]
) -> None:
    authority_ids = {
        "version": "33333333-3333-4333-8333-333333333333",
        "manifest": "44444444-4444-4444-8444-444444444444",
        "pair": "55555555-5555-4555-8555-555555555555",
        "issuer": "66666666-6666-4666-8666-666666666666",
        "approver": "77777777-7777-4777-8777-777777777777",
        "decision": "88888888-8888-4888-8888-888888888888",
    }
    source_commit = "a" * 40
    request_fingerprint = "sha256:" + "7" * 64
    pair_fingerprint = c1_1_authority_mapping["mappings"]["readiness"][
        "dataset_pair_fingerprint"
    ]
    config_id = c1_1_authority_mapping["mappings"]["config"]["authority_id"]
    readiness_id = c1_1_authority_mapping["mappings"]["readiness"]["authority_id"]
    config_fingerprint = c1_1_authority_mapping["computed"]["config_fingerprint"]
    readiness_fingerprint = c1_1_authority_mapping["computed"]["readiness_fingerprint"]

    def payload(name: str) -> tuple[bytes, str]:
        raw = _canonical_payload({"fixture": "c1-2", "kind": name})
        return raw, "sha256:" + hashlib.sha256(raw).hexdigest()

    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_authority_producer")
            identities = [
                (authority_ids["version"], "dataset_version", "dataset-version:c1-2"),
                (
                    authority_ids["manifest"],
                    "dataset_manifest",
                    "dataset-manifest:c1-2",
                ),
                (authority_ids["pair"], "dataset_pair", "dataset-pair:c1-2"),
                (authority_ids["issuer"], "issuer", "issuer:c1-2"),
                (authority_ids["approver"], "approver", "approver:c1-2"),
                (authority_ids["decision"], "decision", "decision:c1-2"),
            ]
            for identity in identities:
                connection.execute(
                    f"INSERT INTO {SCHEMA}.training_authority_identity "
                    "(authority_id, subject_family, domain_key) VALUES (%s,%s,%s)",
                    identity,
                )
            version_payload = payload("dataset_version")
            manifest_payload = payload("dataset_manifest")
            pair_payload = payload("dataset_pair")
            issuer_payload = payload("issuer")
            approver_payload = payload("approver")
            decision_payload = payload("decision")
            connection.execute(
                f"INSERT INTO {SCHEMA}.dataset_version_authority "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,common_object_id) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,'dataset-version-object:c1-2')",
                (authority_ids["version"], *version_payload, source_commit),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.dataset_manifest_authority "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,common_object_id) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,'dataset-manifest-object:c1-2')",
                (authority_ids["manifest"], *manifest_payload, source_commit),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.dataset_pair_authority "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,"
                "dataset_version_authority_id,dataset_manifest_authority_id,pair_fingerprint,publication_scenario) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,%s,%s,%s,'synthetic-contract')",
                (
                    authority_ids["pair"],
                    *pair_payload,
                    source_commit,
                    authority_ids["version"],
                    authority_ids["manifest"],
                    pair_fingerprint,
                ),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_issuer_registry "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,issuer_id,adapter_kind,active_from) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,'issuer:c1-2',"
                "'same_process_training_execution_issuer','2090-01-01T00:00:00Z')",
                (authority_ids["issuer"], *issuer_payload, source_commit),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_approver_registry "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,approver_reference,active_from) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,'approver:c1-2','2090-01-01T00:00:00Z')",
                (authority_ids["approver"], *approver_payload, source_commit),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_execution_decision_authority "
                "(authority_id,payload_bytes,payload_sha256,valid_from,valid_until,source_commit,decision,"
                "authorization_id,issuer_authority_id,issuer_id,approver_authority_id,approver_reference,"
                "evidence_reference,request_fingerprint,issued_at) VALUES "
                "(%s,%s,%s,'2090-01-01T00:00:00Z','2090-01-02T00:00:00Z',%s,'approved',"
                "%s,%s,'issuer:c1-2',%s,'approver:c1-2',%s,%s,'2090-01-01T00:00:00Z')",
                (
                    authority_ids["decision"],
                    *decision_payload,
                    source_commit,
                    "authorization:c1-2",
                    authority_ids["issuer"],
                    authority_ids["approver"],
                    "decision:99999999-9999-4999-8999-999999999999",
                    request_fingerprint,
                ),
            )
            for family, authority_id in (
                ("dataset_version", authority_ids["version"]),
                ("dataset_manifest", authority_ids["manifest"]),
                ("dataset_pair", authority_ids["pair"]),
                ("issuer", authority_ids["issuer"]),
                ("approver", authority_ids["approver"]),
                ("decision", authority_ids["decision"]),
            ):
                connection.execute(
                    f"SELECT ({SCHEMA}.write_training_authority_event(%s,%s,%s,0,'published',NULL,"
                    "'2090-01-01T00:00:00Z',%s,%s)).state",
                    (
                        uuid.uuid4(),
                        authority_id,
                        family,
                        f"correlation:{family}",
                        f"evidence:{family}",
                    ),
                )

    def named(cursor: object) -> dict[str, object]:
        row = cursor.fetchone()
        assert row is not None
        names = [column.name for column in cursor.description]
        assert len(names) == len(set(names))
        return dict(zip(names, row, strict=True))

    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            connection.execute("SET LOCAL ROLE dohalm_training_resolver")
            prerequisite = named(
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.read_c2_training_prerequisite_snapshot(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        authority_ids["version"],
                        authority_ids["manifest"],
                        config_id,
                        readiness_id,
                        pair_fingerprint,
                        config_fingerprint,
                        readiness_fingerprint,
                    ),
                )
            )
            assert (
                str(prerequisite["dataset_pair_authority_id"]) == authority_ids["pair"]
            )
            assert prerequisite["dataset_pair_fingerprint"].strip() == pair_fingerprint
            assert prerequisite["config_payload_sha256"].strip() == config_fingerprint
            assert (
                prerequisite["readiness_payload_sha256"].strip()
                == readiness_fingerprint
            )
            assert {
                prerequisite["dataset_version_state"],
                prerequisite["dataset_manifest_state"],
                prerequisite["dataset_pair_state"],
                prerequisite["config_state"],
                prerequisite["readiness_state"],
            } == {"scheduled"}
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            connection.execute("SET LOCAL ROLE dohalm_training_resolver")
            missing = connection.execute(
                f"SELECT * FROM {SCHEMA}.read_c2_training_prerequisite_snapshot(%s,%s,%s,%s,%s,%s,%s)",
                (
                    authority_ids["version"],
                    authority_ids["manifest"],
                    config_id,
                    readiness_id,
                    "sha256:" + "0" * 64,
                    config_fingerprint,
                    readiness_fingerprint,
                ),
            ).fetchall()
            assert missing == []
        conflicting_pair_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        conflicting_payload = payload("dataset_pair_conflict")
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_authority_producer")
            connection.execute(
                f"INSERT INTO {SCHEMA}.training_authority_identity "
                "(authority_id,subject_family,domain_key) VALUES (%s,'dataset_pair','dataset-pair:c1-2-conflict')",
                (conflicting_pair_id,),
            )
            connection.execute(
                f"INSERT INTO {SCHEMA}.dataset_pair_authority "
                "(authority_id,payload_bytes,payload_sha256,valid_from,source_commit,"
                "dataset_version_authority_id,dataset_manifest_authority_id,pair_fingerprint,publication_scenario) "
                "VALUES (%s,%s,%s,'2090-01-01T00:00:00Z',%s,%s,%s,%s,'synthetic-conflict')",
                (
                    conflicting_pair_id,
                    *conflicting_payload,
                    source_commit,
                    authority_ids["version"],
                    authority_ids["manifest"],
                    pair_fingerprint,
                ),
            )
            connection.execute(
                f"SELECT ({SCHEMA}.write_training_authority_event(%s,%s,'dataset_pair',0,'published',NULL,"
                "'2090-01-01T00:00:00Z','correlation:pair-conflict','evidence:pair-conflict')).state",
                (uuid.uuid4(), conflicting_pair_id),
            )
        with pytest.raises(Exception) as captured:
            with connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                connection.execute("SET LOCAL ROLE dohalm_training_resolver")
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.read_c2_training_prerequisite_snapshot(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        authority_ids["version"],
                        authority_ids["manifest"],
                        config_id,
                        readiness_id,
                        pair_fingerprint,
                        config_fingerprint,
                        readiness_fingerprint,
                    ),
                ).fetchall()
        assert captured.value.sqlstate == "21000"
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            connection.execute("SET LOCAL ROLE dohalm_training_resolver")
            decision = named(
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.read_c2_training_decision_snapshot(%s,%s,%s)",
                    (
                        authority_ids["decision"],
                        request_fingerprint,
                        "decision-policy:c1-2",
                    ),
                )
            )
            assert decision["decision_value"] == "approved"
            assert str(decision["issuer_authority_id"]) == authority_ids["issuer"]
            assert str(decision["approver_authority_id"]) == authority_ids["approver"]
            assert decision["request_fingerprint"].strip() == request_fingerprint
            assert decision["decision_policy_reference"] == "decision-policy:c1-2"
            assert {
                decision["decision_state"],
                decision["issuer_state"],
                decision["approver_state"],
            } == {"scheduled"}

    run_id = "run:c1-2-contract"
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            claim = named(
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.claim_c2_training_execution_journal("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run_id,
                        request_fingerprint,
                        "sha256:" + "8" * 64,
                        run_id,
                        "dataset-version:c1-2",
                        "dataset-manifest:c1-2",
                        pair_fingerprint,
                        config_fingerprint,
                        readiness_fingerprint,
                        source_commit,
                        "prerequisite-policy:c1-2",
                        "process:c1-2",
                    ),
                )
            )
            assert claim["claim_status"] == "acquired"
            assert claim["journal_run_id"] == run_id
            assert claim["journal_phase"] == "claimed"
            assert claim["journal_version"] == 1
            assert claim["journal_reservation_group_id"] is not None
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            transitioned = named(
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.transition_c2_training_execution_journal("
                    "%s,%s,'claimed',1,'resolved',%s)",
                    (run_id, request_fingerprint, "process:c1-2"),
                )
            )
            assert transitioned["phase"] == "resolved"
            assert transitioned["journal_version"] == 2
    with c1_postgres.factory.connection() as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE dohalm_training_journal")
            journal = named(
                connection.execute(
                    f"SELECT * FROM {SCHEMA}.read_c2_training_execution_journal(%s)",
                    (run_id,),
                )
            )
            assert journal["phase"] == "resolved"
            assert journal["journal_version"] == 2
            assert journal["process_boundary_id"] == "process:c1-2"
            assert (
                journal["reservation_group_id"] == claim["journal_reservation_group_id"]
            )
            grants = connection.execute(
                "SELECT has_function_privilege(current_user, %s, 'EXECUTE'), "
                "has_table_privilege(current_user, %s, 'SELECT')",
                (
                    f"{SCHEMA}.read_c2_training_execution_journal(character varying)",
                    f"{SCHEMA}.training_execution_journal",
                ),
            ).fetchone()
            assert grants == (True, False)


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
            assert apply_c1_migrations(connection) == (2, 3, 4, 5)
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
            (
                3,
                "0003_c1_2_c2_typed_snapshot_and_journal_contracts.sql",
                hashlib.sha256(
                    (
                        migration_root
                        / "0003_c1_2_c2_typed_snapshot_and_journal_contracts.sql"
                    ).read_bytes()
                ).hexdigest(),
            ),
            (
                4,
                "0004_dataset_proposal_authority.sql",
                hashlib.sha256(
                    (
                        migration_root / "0004_dataset_proposal_authority.sql"
                    ).read_bytes()
                ).hexdigest(),
            ),
            (
                5,
                "0005_dataset_review_authority.sql",
                hashlib.sha256(
                    (migration_root / "0005_dataset_review_authority.sql").read_bytes()
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
                (3, "0003_c1_2_c2_typed_snapshot_and_journal_contracts.sql"),
                (4, "0004_dataset_proposal_authority.sql"),
                (5, "0005_dataset_review_authority.sql"),
            ]
            assert all(len(row[2]) == 64 for row in rows)
            assert apply_c1_migrations(connection) == ()
            assert connection.execute(
                "SELECT to_regclass(%s), has_function_privilege(%s, %s, 'EXECUTE'), "
                "to_regclass(%s), has_function_privilege(%s, %s, 'EXECUTE')",
                (
                    "dohalm_dataset_governance_v1.dataset_version_proposal_authority",
                    "dohalm_dataset_proposal_authority",
                    (
                        "dohalm_dataset_governance_v1."
                        "compare_and_create_dataset_version_proposal"
                        "(varchar,varchar,varchar,char,bytea)"
                    ),
                    "dohalm_dataset_governance_v1.dataset_version_review_authority",
                    "dohalm_dataset_review_authority",
                    (
                        "dohalm_dataset_governance_v1."
                        "start_dataset_version_review"
                        "(varchar,varchar,varchar,char,varchar,timestamptz,varchar,char)"
                    ),
                ),
            ).fetchone() == (
                "dohalm_dataset_governance_v1.dataset_version_proposal_authority",
                True,
                "dohalm_dataset_governance_v1.dataset_version_review_authority",
                True,
            )
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
    _wait_for_postgres_connection(replace(c1_postgres.settings, port=restart_port))
    with restart_factory.connection() as connection:
        assert connection.execute("SELECT value FROM c1_restart_probe").fetchone() == (
            1,
        )
        assert apply_c1_migrations(connection) == ()


@contextmanager
def _dataset_proposal_adapter(
    c1_postgres: C1Fixture,
) -> Iterator[PostgresDatasetProposalAuthority]:
    from psycopg import sql

    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
        PostgresDatasetProposalAuthoritySettings,
    )

    password = secrets.token_urlsafe(32)
    with c1_postgres.factory.connection() as owner:
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_dataset_proposal_authority PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        owner.commit()
    try:
        settings = PostgresDatasetProposalAuthoritySettings(
            environment="isolated_test",
            host=c1_postgres.settings.host,
            port=c1_postgres.settings.port,
            database=c1_postgres.settings.database,
            user="dohalm_dataset_proposal_authority",
            password=password,
            application_name="dohalm-dataset-proposal-contract",
            sslmode="disable",
        )
        yield PostgresDatasetProposalAuthority(settings)
    finally:
        with c1_postgres.factory.connection() as owner:
            owner.execute("ALTER ROLE dohalm_dataset_proposal_authority PASSWORD NULL")
            owner.commit()


def _proposal_payload(suffix: str, **updates: object) -> dict[str, object]:
    from test_dataset_proposal_authority import _payload

    payload = _payload(
        object_id=f"dataset_version_product_{suffix}",
        dataset_id=f"dataset_product_{suffix}",
        dataset_version="1.0.0",
    )
    payload.update(updates)
    return payload


def _check_dataset_proposal_authority_roles_schema_and_direct_dml_denial(
    c1_postgres: C1Fixture,
) -> None:
    with c1_postgres.factory.connection() as owner:
        roles = dict(
            owner.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
                (
                    [
                        "dohalm_dataset_proposal_owner",
                        "dohalm_dataset_proposal_authority",
                    ],
                ),
            ).fetchall()
        )
        assert roles == {
            "dohalm_dataset_proposal_owner": False,
            "dohalm_dataset_proposal_authority": True,
        }
        owner_name = owner.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname=%s AND tablename=%s",
            (
                "dohalm_dataset_governance_v1",
                "dataset_version_proposal_authority",
            ),
        ).fetchone()
        assert owner_name == ("dohalm_dataset_proposal_owner",)
        read_function = owner.execute(
            "SELECT p.prosecdef, p.provolatile, p.proconfig, "
            "has_function_privilege(%s, p.oid, 'EXECUTE'), "
            "has_function_privilege('public', p.oid, 'EXECUTE') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname=%s AND p.proname=%s",
            (
                "dohalm_dataset_proposal_authority",
                "dohalm_dataset_governance_v1",
                "read_dataset_version_proposal",
            ),
        ).fetchone()
        assert read_function == (
            True,
            "s",
            ["search_path=pg_catalog, pg_temp"],
            True,
            False,
        )
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        settings = adapter._settings
        import psycopg

        connection = psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user=settings.user,
            password=settings.password,
            sslmode=settings.sslmode,
            autocommit=False,
        )
        try:
            with pytest.raises(Exception) as denied:
                with connection.transaction():
                    connection.execute(
                        "SELECT count(*) FROM "
                        "dohalm_dataset_governance_v1.dataset_version_proposal_authority"
                    )
            assert denied.value.sqlstate == "42501"
            with pytest.raises(Exception) as insert_denied:
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO dohalm_dataset_governance_v1."
                        "dataset_version_proposal_authority "
                        "(object_id,dataset_id,dataset_version,proposal_fingerprint,"
                        "canonical_payload,authority_reference) "
                        "VALUES ('denied','denied','1','sha256:' || repeat('0',64),"
                        "convert_to('{}', 'UTF8'),'dataset-proposal:denied')"
                    )
            assert insert_denied.value.sqlstate == "42501"
            for statement in (
                "UPDATE dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority SET dataset_version='denied'",
                "DELETE FROM dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority",
            ):
                with (
                    pytest.raises(Exception) as mutation_denied,
                    connection.transaction(),
                ):
                    connection.execute(statement)
                assert mutation_denied.value.sqlstate == "42501"
        finally:
            connection.close()


def _check_dataset_proposal_authority_create_replay_conflict_restart_and_round_trip(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.checksums import canonical_json_bytes
    from src.data.dataset_governance import propose_dataset_version
    from src.data.dataset_proposal_authority import (
        DatasetProposalAuthorityError,
        DatasetProposalOutcome,
        dataset_version_proposal_fingerprint,
    )
    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
    )

    suffix = uuid.uuid4().hex
    proposal = propose_dataset_version(_proposal_payload(suffix))
    fingerprint = dataset_version_proposal_fingerprint(proposal)
    conflicting = propose_dataset_version(
        _proposal_payload(
            suffix,
            producer={"name": "competing-governance", "version": "1.0.0"},
        )
    )
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        created = adapter.compare_and_create(proposal, proposal_fingerprint=fingerprint)
        replayed = PostgresDatasetProposalAuthority(
            adapter._settings
        ).compare_and_create(
            propose_dataset_version(dict(reversed(tuple(proposal.payload.items())))),
            proposal_fingerprint=fingerprint,
        )
        assert created.outcome is DatasetProposalOutcome.CREATED
        assert replayed.outcome is DatasetProposalOutcome.REPLAYED
        assert replayed.proposal == proposal
        assert replayed.proposal_fingerprint == fingerprint
        assert replayed.authority_reference == created.authority_reference
        with pytest.raises(DatasetProposalAuthorityError) as conflict:
            PostgresDatasetProposalAuthority(adapter._settings).compare_and_create(
                conflicting,
                proposal_fingerprint=dataset_version_proposal_fingerprint(conflicting),
            )
        assert conflict.value.code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
        assert conflict.value.existing_fingerprint == fingerprint
        different = propose_dataset_version(
            _proposal_payload(suffix + "b", dataset_version="2.0.0")
        )
        assert (
            adapter.compare_and_create(
                different,
                proposal_fingerprint=dataset_version_proposal_fingerprint(different),
            ).outcome
            is DatasetProposalOutcome.CREATED
        )
    with c1_postgres.factory.connection() as owner:
        rows = owner.execute(
            "SELECT object_id, proposal_fingerprint, canonical_payload "
            "FROM dohalm_dataset_governance_v1.dataset_version_proposal_authority "
            "WHERE object_id = ANY(%s) ORDER BY object_id",
            ([proposal.identity.object_id, different.identity.object_id],),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][1].rstrip() == fingerprint
    assert bytes(rows[0][2]) == canonical_json_bytes(proposal.payload)


def _check_dataset_proposal_authoritative_read_contract(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_governance import (
        DatasetVersionIdentity,
        propose_dataset_version,
    )
    from src.data.dataset_proposal_authority import (
        DatasetProposalAuthorityError,
        DatasetProposalAuthorityRecord,
        DatasetProposalOutcome,
        dataset_version_proposal_fingerprint,
    )
    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
    )

    suffix = uuid.uuid4().hex
    proposal = propose_dataset_version(_proposal_payload(suffix))
    fingerprint = dataset_version_proposal_fingerprint(proposal)
    missing = DatasetVersionIdentity(
        f"dataset_version_missing_{suffix}",
        f"dataset_missing_{suffix}",
        "1.0.0",
    )
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        with pytest.raises(DatasetProposalAuthorityError) as not_found:
            adapter.read_authoritative_proposal(missing)
        assert not_found.value.code == "DATASET_PROPOSAL_AUTHORITY_NOT_FOUND"

        created = adapter.compare_and_create(
            proposal,
            proposal_fingerprint=fingerprint,
        )
        replayed = adapter.compare_and_create(
            proposal,
            proposal_fingerprint=fingerprint,
        )
        assert replayed.outcome is DatasetProposalOutcome.REPLAYED
        with c1_postgres.factory.connection() as owner:
            before = owner.execute(
                "SELECT object_id, dataset_id, dataset_version, proposal_fingerprint, "
                "canonical_payload, authority_reference, authority_version, created_at "
                "FROM dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority WHERE object_id=%s",
                (proposal.identity.object_id,),
            ).fetchone()
        loaded = adapter.read_authoritative_proposal(proposal.identity)
        restarted = PostgresDatasetProposalAuthority(
            adapter._settings
        ).read_authoritative_proposal(proposal.identity)
        assert type(loaded) is DatasetProposalAuthorityRecord
        assert loaded == restarted
        assert loaded.proposal == created.proposal == proposal
        assert loaded.proposal == replayed.proposal
        assert loaded.identity == proposal.identity
        assert loaded.proposal_fingerprint == fingerprint
        assert loaded.authority_reference == created.authority_reference
        assert loaded.authority_version == created.authority_version == 1
        assert loaded.proposal.payload["extensions"] == proposal.payload["extensions"]
        assert loaded.proposal.payload["lineage"] == proposal.payload["lineage"]
        assert (
            loaded.proposal.payload["split_manifest"]
            == proposal.payload["split_manifest"]
        )

        conflicting = propose_dataset_version(
            _proposal_payload(
                suffix,
                producer={"name": "conflicting-governance", "version": "1.0.0"},
            )
        )
        with pytest.raises(DatasetProposalAuthorityError) as conflict:
            adapter.compare_and_create(
                conflicting,
                proposal_fingerprint=dataset_version_proposal_fingerprint(conflicting),
            )
        assert conflict.value.code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
        assert adapter.read_authoritative_proposal(proposal.identity) == loaded

        with c1_postgres.factory.connection() as owner:
            after = owner.execute(
                "SELECT object_id, dataset_id, dataset_version, proposal_fingerprint, "
                "canonical_payload, authority_reference, authority_version, created_at "
                "FROM dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority WHERE object_id=%s",
                (proposal.identity.object_id,),
            ).fetchone()
        assert after == before

        invalid = replace(adapter._settings, password="synthetic-wrong-password")
        with pytest.raises(DatasetProposalAuthorityError) as unavailable:
            PostgresDatasetProposalAuthority(invalid).read_authoritative_proposal(
                proposal.identity
            )
        assert unavailable.value.code == "DATASET_PROPOSAL_AUTHORITY_UNAVAILABLE"
        assert invalid.password not in str(unavailable.value)
        assert invalid.host not in str(unavailable.value)
        assert "SELECT" not in str(unavailable.value)

        for malformed_identity in (
            "invalid",
            DatasetVersionIdentity("", "dataset", "1.0.0"),
            DatasetVersionIdentity("object", "d" * 257, "1.0.0"),
        ):
            with pytest.raises(DatasetProposalAuthorityError) as malformed:
                adapter.read_authoritative_proposal(
                    malformed_identity  # type: ignore[arg-type]
                )
            assert malformed.value.code == "DATASET_PROPOSAL_AUTHORITY_IDENTITY_INVALID"

        with c1_postgres.factory.connection() as owner, owner.transaction():
            owner.execute(
                "ALTER TABLE dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority DISABLE TRIGGER USER"
            )
            owner.execute(
                "UPDATE dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority SET proposal_fingerprint=%s "
                "WHERE object_id=%s",
                ("sha256:" + "0" * 64, proposal.identity.object_id),
            )
            owner.execute(
                "ALTER TABLE dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority ENABLE TRIGGER USER"
            )
        with pytest.raises(DatasetProposalAuthorityError) as corrupt:
            adapter.read_authoritative_proposal(proposal.identity)
        assert corrupt.value.code == "DATASET_PROPOSAL_AUTHORITY_CORRUPT"
        with c1_postgres.factory.connection() as owner:
            assert owner.execute(
                "SELECT proposal_fingerprint FROM dohalm_dataset_governance_v1."
                "dataset_version_proposal_authority WHERE object_id=%s",
                (proposal.identity.object_id,),
            ).fetchone() == ("sha256:" + "0" * 64,)


def _check_product_dataset_governance_uses_durable_authority_without_lifecycle_side_effects(
    c1_postgres: C1Fixture,
) -> None:
    from test_product_dataset_governance import _compose, _CurrentEvidenceAuthority

    from src.data.dataset_proposal_authority import (
        DatasetProposalAuthorityError,
        DatasetProposalOutcome,
    )
    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
    )
    from src.data.product_dataset_governance import propose_product_dataset_version

    with c1_postgres.factory.connection() as owner:
        before = owner.execute(
            f"SELECT "
            f"(SELECT count(*) FROM {SCHEMA}.dataset_version_authority), "
            f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal), "
            f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event)"
        ).fetchone()
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        first = propose_product_dataset_version(
            _compose(),
            authority=adapter,
            current_evidence_authority=_CurrentEvidenceAuthority(),
            proposed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        )
        second = propose_product_dataset_version(
            _compose(),
            authority=PostgresDatasetProposalAuthority(adapter._settings),
            current_evidence_authority=_CurrentEvidenceAuthority(),
            proposed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        assert first.outcome is DatasetProposalOutcome.CREATED
        assert second.outcome is DatasetProposalOutcome.REPLAYED
        assert first.proposal == second.proposal

        invalid = replace(adapter._settings, password="synthetic-wrong-password")
        with pytest.raises(DatasetProposalAuthorityError) as unavailable:
            PostgresDatasetProposalAuthority(invalid).compare_and_create(
                first.proposal,
                proposal_fingerprint=first.proposal_fingerprint,
            )
        assert unavailable.value.code == "DATASET_PROPOSAL_AUTHORITY_UNAVAILABLE"
        assert invalid.password not in str(unavailable.value)
        assert invalid.host not in str(unavailable.value)
        assert "SELECT" not in str(unavailable.value)
    with c1_postgres.factory.connection() as owner:
        after = owner.execute(
            f"SELECT "
            f"(SELECT count(*) FROM {SCHEMA}.dataset_version_authority), "
            f"(SELECT count(*) FROM {SCHEMA}.training_execution_journal), "
            f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event)"
        ).fetchone()
    assert after == before


def _check_dataset_proposal_authority_multi_connection_concurrency_is_atomic(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_governance import propose_dataset_version
    from src.data.dataset_proposal_authority import (
        DatasetProposalAuthorityError,
        DatasetProposalOutcome,
        dataset_version_proposal_fingerprint,
    )
    from src.data.postgres_dataset_proposal_authority import (
        PostgresDatasetProposalAuthority,
    )

    suffix = uuid.uuid4().hex
    identical = propose_dataset_version(_proposal_payload(suffix))
    identical_fingerprint = dataset_version_proposal_fingerprint(identical)
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        barrier = threading.Barrier(4)

        def identical_call(_: int):
            barrier.wait()
            return PostgresDatasetProposalAuthority(
                adapter._settings
            ).compare_and_create(identical, proposal_fingerprint=identical_fingerprint)

        with ThreadPoolExecutor(max_workers=4) as workers:
            identical_results = list(workers.map(identical_call, range(4)))
        assert [item.outcome for item in identical_results].count(
            DatasetProposalOutcome.CREATED
        ) == 1
        assert [item.outcome for item in identical_results].count(
            DatasetProposalOutcome.REPLAYED
        ) == 3

        conflict_suffix = suffix + "c"
        proposals = (
            propose_dataset_version(_proposal_payload(conflict_suffix)),
            propose_dataset_version(
                _proposal_payload(
                    conflict_suffix,
                    content_fingerprint="sha256:" + "9" * 64,
                )
            ),
        )
        conflict_barrier = threading.Barrier(2)

        def conflicting_call(proposal: object):
            conflict_barrier.wait()
            try:
                return PostgresDatasetProposalAuthority(
                    adapter._settings
                ).compare_and_create(
                    proposal,
                    proposal_fingerprint=dataset_version_proposal_fingerprint(proposal),
                )
            except DatasetProposalAuthorityError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as workers:
            conflict_results = list(workers.map(conflicting_call, proposals))
        assert (
            sum(
                getattr(item, "outcome", None) is DatasetProposalOutcome.CREATED
                for item in conflict_results
            )
            == 1
        )
        errors = [
            item
            for item in conflict_results
            if isinstance(item, DatasetProposalAuthorityError)
        ]
        assert len(errors) == 1
        assert errors[0].code == "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT"
    with c1_postgres.factory.connection() as owner:
        count = owner.execute(
            "SELECT count(*) FROM "
            "dohalm_dataset_governance_v1.dataset_version_proposal_authority "
            "WHERE object_id = ANY(%s)",
            ([identical.identity.object_id, proposals[0].identity.object_id],),
        ).fetchone()
    assert count == (2,)


def _check_dataset_proposal_authority_rollback_corruption_and_no_overwrite(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.checksums import canonical_json_bytes
    from src.data.dataset_governance import propose_dataset_version
    from src.data.dataset_proposal_authority import (
        DatasetProposalAuthorityError,
        DatasetProposalOutcome,
        dataset_version_proposal_fingerprint,
    )

    suffix = uuid.uuid4().hex
    proposal = propose_dataset_version(_proposal_payload(suffix))
    fingerprint = dataset_version_proposal_fingerprint(proposal)
    payload = canonical_json_bytes(proposal.payload)
    with c1_postgres.factory.connection() as owner:
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            with owner.transaction():
                owner.execute(
                    "SELECT * FROM "
                    "dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal"
                    "(%s,%s,%s,%s,%s)",
                    (
                        proposal.identity.object_id,
                        proposal.identity.dataset_id,
                        proposal.identity.dataset_version,
                        fingerprint,
                        payload,
                    ),
                )
                raise RuntimeError("synthetic rollback")
        assert owner.execute(
            "SELECT count(*) FROM "
            "dohalm_dataset_governance_v1.dataset_version_proposal_authority "
            "WHERE object_id=%s",
            (proposal.identity.object_id,),
        ).fetchone() == (0,)

    with _dataset_proposal_adapter(c1_postgres) as adapter:
        assert (
            adapter.compare_and_create(
                proposal, proposal_fingerprint=fingerprint
            ).outcome
            is DatasetProposalOutcome.CREATED
        )
        with c1_postgres.factory.connection() as owner:
            with owner.transaction():
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority DISABLE TRIGGER USER"
                )
                owner.execute(
                    "UPDATE dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority "
                    "SET canonical_payload=%s WHERE object_id=%s",
                    (b"{}\n", proposal.identity.object_id),
                )
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority ENABLE TRIGGER USER"
                )
        with pytest.raises(DatasetProposalAuthorityError) as corrupt:
            adapter.compare_and_create(proposal, proposal_fingerprint=fingerprint)
        assert corrupt.value.code == "DATASET_PROPOSAL_AUTHORITY_CORRUPT"
        with c1_postgres.factory.connection() as owner:
            assert owner.execute(
                "SELECT canonical_payload FROM "
                "dohalm_dataset_governance_v1.dataset_version_proposal_authority "
                "WHERE object_id=%s",
                (proposal.identity.object_id,),
            ).fetchone() == (b"{}\n",)
            with owner.transaction():
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority DISABLE TRIGGER USER"
                )
                owner.execute(
                    "DELETE FROM dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority WHERE object_id=%s",
                    (proposal.identity.object_id,),
                )
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_proposal_authority ENABLE TRIGGER USER"
                )


@contextmanager
def _dataset_review_adapter(
    c1_postgres: C1Fixture,
) -> Iterator[PostgresDatasetReviewAuthority]:
    from psycopg import sql

    from src.data.postgres_dataset_review_authority import (
        PostgresDatasetReviewAuthority,
        PostgresDatasetReviewAuthoritySettings,
    )

    password = secrets.token_urlsafe(32)
    with c1_postgres.factory.connection() as owner:
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_dataset_review_authority PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        owner.commit()
    try:
        settings = PostgresDatasetReviewAuthoritySettings(
            environment="isolated_test",
            host=c1_postgres.settings.host,
            port=c1_postgres.settings.port,
            database=c1_postgres.settings.database,
            user="dohalm_dataset_review_authority",
            password=password,
            application_name="dohalm-dataset-review-contract",
            sslmode="disable",
        )
        yield PostgresDatasetReviewAuthority(settings)
    finally:
        with c1_postgres.factory.connection() as owner:
            owner.execute("ALTER ROLE dohalm_dataset_review_authority PASSWORD NULL")
            owner.commit()


def _create_authoritative_proposal(c1_postgres: C1Fixture, suffix: str):
    from src.data.dataset_governance import propose_dataset_version
    from src.data.dataset_proposal_authority import dataset_version_proposal_fingerprint

    proposal = propose_dataset_version(_proposal_payload(suffix))
    fingerprint = dataset_version_proposal_fingerprint(proposal)
    with _dataset_proposal_adapter(c1_postgres) as adapter:
        adapter.compare_and_create(proposal, proposal_fingerprint=fingerprint)
    return proposal, fingerprint


def _review_request(proposal: object, fingerprint: str, **updates: object):
    from src.data.dataset_review_authority import DatasetReviewStartRequest

    values = {
        "identity": proposal.identity,
        "proposal_fingerprint": fingerprint,
        "reviewer_reference": "reviewer:governance-primary",
        "review_started_at": datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc),
        "request_reference": "review-request:postgres-contract",
    }
    values.update(updates)
    return DatasetReviewStartRequest(**values)


def _check_dataset_review_authority_roles_functions_and_immutability(
    c1_postgres: C1Fixture,
) -> None:
    with c1_postgres.factory.connection() as owner:
        roles = dict(
            owner.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
                (["dohalm_dataset_review_owner", "dohalm_dataset_review_authority"],),
            ).fetchall()
        )
        assert roles == {
            "dohalm_dataset_review_owner": False,
            "dohalm_dataset_review_authority": True,
        }
        assert owner.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname=%s AND tablename=%s",
            ("dohalm_dataset_governance_v1", "dataset_version_review_authority"),
        ).fetchone() == ("dohalm_dataset_review_owner",)
        functions = owner.execute(
            "SELECT p.proname, p.prosecdef, p.proconfig, "
            "has_function_privilege(%s, p.oid, 'EXECUTE'), "
            "has_function_privilege('public', p.oid, 'EXECUTE') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname=%s AND p.proname = ANY(%s) ORDER BY p.proname",
            (
                "dohalm_dataset_review_authority",
                "dohalm_dataset_governance_v1",
                (["read_dataset_version_review", "start_dataset_version_review"]),
            ),
        ).fetchall()
        assert functions == [
            (
                "read_dataset_version_review",
                True,
                ["search_path=pg_catalog, pg_temp"],
                True,
                False,
            ),
            (
                "start_dataset_version_review",
                True,
                ["search_path=pg_catalog, pg_temp"],
                True,
                False,
            ),
        ]

    with _dataset_review_adapter(c1_postgres) as adapter:
        import psycopg

        settings = adapter._settings
        connection = psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user=settings.user,
            password=settings.password,
            sslmode=settings.sslmode,
            autocommit=False,
        )
        try:
            for statement in (
                (
                    "SELECT count(*) FROM dohalm_dataset_governance_v1."
                    "dataset_version_review_authority"
                ),
                (
                    "INSERT INTO dohalm_dataset_governance_v1."
                    "dataset_version_review_authority DEFAULT VALUES"
                ),
                (
                    "UPDATE dohalm_dataset_governance_v1."
                    "dataset_version_review_authority SET lifecycle_state='reviewing'"
                ),
                (
                    "DELETE FROM dohalm_dataset_governance_v1."
                    "dataset_version_review_authority"
                ),
            ):
                with pytest.raises(Exception) as denied, connection.transaction():
                    connection.execute(statement)
                assert denied.value.sqlstate == "42501"
        finally:
            connection.close()


def _check_dataset_review_authority_start_read_restart_and_no_proposal_mutation(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_governance import DatasetVersionIdentity
    from src.data.dataset_review_authority import (
        DatasetReviewAuthorityError,
        DatasetReviewOutcome,
        build_dataset_review_authority_record,
    )
    from src.data.postgres_dataset_review_authority import (
        PostgresDatasetReviewAuthority,
        _authority_reference,
    )

    suffix = uuid.uuid4().hex
    proposal, fingerprint = _create_authoritative_proposal(c1_postgres, suffix)
    request = _review_request(proposal, fingerprint)
    rollback_fingerprint = build_dataset_review_authority_record(
        request,
        authority_reference=_authority_reference(proposal.identity, fingerprint),
        authority_version=1,
    ).record_fingerprint
    with c1_postgres.factory.connection() as owner:
        proposal_before = owner.execute(
            "SELECT * FROM dohalm_dataset_governance_v1."
            "dataset_version_proposal_authority WHERE object_id=%s",
            (proposal.identity.object_id,),
        ).fetchone()
        with (
            pytest.raises(RuntimeError, match="synthetic review rollback"),
            owner.transaction(),
        ):
            owner.execute(
                "SELECT * FROM dohalm_dataset_governance_v1."
                "start_dataset_version_review(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    proposal.identity.object_id,
                    proposal.identity.dataset_id,
                    proposal.identity.dataset_version,
                    fingerprint,
                    request.reviewer_reference,
                    request.review_started_at,
                    request.request_reference,
                    rollback_fingerprint,
                ),
            )
            raise RuntimeError("synthetic review rollback")
        assert owner.execute(
            "SELECT count(*) FROM dohalm_dataset_governance_v1."
            "dataset_version_review_authority WHERE object_id=%s",
            (proposal.identity.object_id,),
        ).fetchone() == (0,)
    with _dataset_review_adapter(c1_postgres) as adapter:
        missing = DatasetVersionIdentity(
            "dataset_version_missing_review", "dataset_missing_review", "1.0.0"
        )
        with pytest.raises(DatasetReviewAuthorityError) as not_found:
            adapter.read_authoritative_review(
                missing, proposal_fingerprint="sha256:" + "0" * 64
            )
        assert not_found.value.code == "DATASET_REVIEW_AUTHORITY_NOT_FOUND"

        started = adapter.start_review(request)
        replay = PostgresDatasetReviewAuthority(adapter._settings).start_review(
            replace(
                request,
                review_started_at=datetime(2026, 8, 24, 3, 3, tzinfo=timezone.utc),
            )
        )
        assert started.outcome is DatasetReviewOutcome.STARTED
        assert replay.outcome is DatasetReviewOutcome.REPLAYED
        assert replay.record == started.record
        assert replay.record.review_started_at == request.review_started_at
        loaded = PostgresDatasetReviewAuthority(
            adapter._settings
        ).read_authoritative_review(proposal.identity, proposal_fingerprint=fingerprint)
        assert loaded == started.record
        with pytest.raises(DatasetReviewAuthorityError) as read_mismatch:
            adapter.read_authoritative_review(
                proposal.identity,
                proposal_fingerprint="sha256:" + "9" * 64,
            )
        assert (
            read_mismatch.value.code == "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH"
        )
        for conflict_request in (
            replace(request, reviewer_reference="reviewer:governance-secondary"),
            replace(request, request_reference="review-request:conflicting"),
        ):
            result = PostgresDatasetReviewAuthority(adapter._settings).start_review(
                conflict_request
            )
            assert result.outcome is DatasetReviewOutcome.CONFLICT
            assert result.record is None
        with pytest.raises(DatasetReviewAuthorityError) as mismatch:
            adapter.start_review(
                replace(request, proposal_fingerprint="sha256:" + "9" * 64)
            )
        assert mismatch.value.code == "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH"

        invalid = replace(adapter._settings, password="synthetic-wrong-password")
        with pytest.raises(DatasetReviewAuthorityError) as unavailable:
            PostgresDatasetReviewAuthority(invalid).read_authoritative_review(
                proposal.identity, proposal_fingerprint=fingerprint
            )
        assert unavailable.value.code == "DATASET_REVIEW_AUTHORITY_UNAVAILABLE"
        assert invalid.password not in str(unavailable.value)
        assert invalid.host not in str(unavailable.value)

    with c1_postgres.factory.connection() as owner:
        assert owner.execute(
            "SELECT count(*) FROM dohalm_dataset_governance_v1."
            "dataset_version_review_authority WHERE object_id=%s",
            (proposal.identity.object_id,),
        ).fetchone() == (1,)
        proposal_after = owner.execute(
            "SELECT * FROM dohalm_dataset_governance_v1."
            "dataset_version_proposal_authority WHERE object_id=%s",
            (proposal.identity.object_id,),
        ).fetchone()
        assert proposal_after == proposal_before
        for statement in (
            (
                "UPDATE dohalm_dataset_governance_v1."
                "dataset_version_review_authority "
                "SET reviewer_reference='reviewer:forbidden' WHERE object_id=%s"
            ),
            (
                "DELETE FROM dohalm_dataset_governance_v1."
                "dataset_version_review_authority WHERE object_id=%s"
            ),
        ):
            with pytest.raises(Exception) as immutable, owner.transaction():
                owner.execute(statement, (proposal.identity.object_id,))
            assert immutable.value.sqlstate == "55000"


def _check_dataset_review_authority_concurrency_and_corruption(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_review_authority import (
        DatasetReviewAuthorityError,
        DatasetReviewOutcome,
    )
    from src.data.postgres_dataset_review_authority import (
        PostgresDatasetReviewAuthority,
    )

    suffix = uuid.uuid4().hex
    proposal, fingerprint = _create_authoritative_proposal(c1_postgres, suffix)
    request = _review_request(proposal, fingerprint)
    with _dataset_review_adapter(c1_postgres) as adapter:
        barrier = threading.Barrier(4)

        def same_start(_: int):
            barrier.wait()
            return PostgresDatasetReviewAuthority(adapter._settings).start_review(
                request
            )

        with ThreadPoolExecutor(max_workers=4) as workers:
            same_results = list(workers.map(same_start, range(4)))
        assert (
            sum(
                result.outcome is DatasetReviewOutcome.STARTED
                for result in same_results
            )
            == 1
        )
        assert (
            sum(
                result.outcome is DatasetReviewOutcome.REPLAYED
                for result in same_results
            )
            == 3
        )

        proposal_two, fingerprint_two = _create_authoritative_proposal(
            c1_postgres, suffix + "b"
        )
        requests = (
            _review_request(proposal_two, fingerprint_two),
            _review_request(
                proposal_two,
                fingerprint_two,
                reviewer_reference="reviewer:governance-secondary",
            ),
        )
        conflict_barrier = threading.Barrier(2)

        def competing_start(item: object):
            conflict_barrier.wait()
            return PostgresDatasetReviewAuthority(adapter._settings).start_review(item)

        with ThreadPoolExecutor(max_workers=2) as workers:
            competing = list(workers.map(competing_start, requests))
        assert (
            sum(result.outcome is DatasetReviewOutcome.STARTED for result in competing)
            == 1
        )
        assert (
            sum(result.outcome is DatasetReviewOutcome.CONFLICT for result in competing)
            == 1
        )

        with c1_postgres.factory.connection() as owner, owner.transaction():
            owner.execute(
                "ALTER TABLE dohalm_dataset_governance_v1."
                "dataset_version_review_authority DISABLE TRIGGER USER"
            )
            owner.execute(
                "UPDATE dohalm_dataset_governance_v1."
                "dataset_version_review_authority SET record_fingerprint=%s "
                "WHERE object_id=%s",
                ("sha256:" + "0" * 64, proposal.identity.object_id),
            )
            owner.execute(
                "ALTER TABLE dohalm_dataset_governance_v1."
                "dataset_version_review_authority ENABLE TRIGGER USER"
            )
        with pytest.raises(DatasetReviewAuthorityError) as corrupt:
            adapter.read_authoritative_review(
                proposal.identity, proposal_fingerprint=fingerprint
            )
        assert corrupt.value.code == "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"

    with c1_postgres.factory.connection() as owner:
        assert owner.execute(
            "SELECT count(*) FROM dohalm_dataset_governance_v1."
            "dataset_version_review_authority WHERE object_id = ANY(%s)",
            ([proposal.identity.object_id, proposal_two.identity.object_id],),
        ).fetchone() == (2,)


def _check_dataset_review_authority_concurrency_repetition(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_review_authority import DatasetReviewOutcome
    from src.data.postgres_dataset_review_authority import (
        PostgresDatasetReviewAuthority,
    )

    with _dataset_review_adapter(c1_postgres) as adapter:
        for _ in range(4):
            suffix = uuid.uuid4().hex
            proposal, fingerprint = _create_authoritative_proposal(c1_postgres, suffix)
            request = _review_request(proposal, fingerprint)
            barrier = threading.Barrier(6)

            def same_start(
                _: int,
                current_barrier: threading.Barrier = barrier,
                current_request: object = request,
            ):
                current_barrier.wait()
                return PostgresDatasetReviewAuthority(adapter._settings).start_review(
                    current_request
                )

            with ThreadPoolExecutor(max_workers=6) as workers:
                results = list(workers.map(same_start, range(6)))
            assert (
                sum(
                    result.outcome is DatasetReviewOutcome.STARTED for result in results
                )
                == 1
            )
            assert (
                sum(
                    result.outcome is DatasetReviewOutcome.REPLAYED
                    for result in results
                )
                == 5
            )

            competing_proposal, competing_fingerprint = _create_authoritative_proposal(
                c1_postgres, suffix + "b"
            )
            requests = (
                _review_request(competing_proposal, competing_fingerprint),
                _review_request(
                    competing_proposal,
                    competing_fingerprint,
                    reviewer_reference="reviewer:governance-secondary",
                ),
            )
            competing_barrier = threading.Barrier(2)

            def competing_start(
                item: object,
                current_barrier: threading.Barrier = competing_barrier,
            ):
                current_barrier.wait()
                return PostgresDatasetReviewAuthority(adapter._settings).start_review(
                    item
                )

            with ThreadPoolExecutor(max_workers=2) as workers:
                competing = list(workers.map(competing_start, requests))
            assert (
                sum(
                    result.outcome is DatasetReviewOutcome.STARTED
                    for result in competing
                )
                == 1
            )
            assert (
                sum(
                    result.outcome is DatasetReviewOutcome.CONFLICT
                    for result in competing
                )
                == 1
            )


def _check_dataset_review_authority_fingerprint_and_corruption_matrix(
    c1_postgres: C1Fixture,
) -> None:
    from src.data.dataset_governance import DatasetVersionIdentity
    from src.data.dataset_review_authority import (
        DatasetReviewAuthorityError,
        DatasetReviewStartRequest,
        build_dataset_review_authority_record,
    )
    from src.data.postgres_dataset_review_authority import _authority_reference

    parity_requests = (
        DatasetReviewStartRequest(
            DatasetVersionIdentity("parity-object-a", "parity-dataset-a", "1.0.0"),
            "sha256:" + "1" * 64,
            "reviewer:parity-a",
            datetime(2026, 8, 24, 1, 2, 3, 456789, tzinfo=timezone.utc),
        ),
        DatasetReviewStartRequest(
            DatasetVersionIdentity("parity-object-b", "parity-dataset-b", "2.0.0"),
            "sha256:" + "2" * 64,
            "reviewer:parity-b",
            datetime(
                2026,
                8,
                24,
                9,
                8,
                7,
                654321,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
            "request:timezone-offset",
        ),
        DatasetReviewStartRequest(
            DatasetVersionIdentity("o" + "x" * 255, "d" + "y" * 255, "v" + "z" * 255),
            "sha256:" + "3" * 64,
            "r" + "a" * 255,
            datetime(2037, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
            "q" + "b" * 255,
        ),
    )
    with c1_postgres.factory.connection() as owner:
        for request in parity_requests:
            authority_reference = _authority_reference(
                request.identity, request.proposal_fingerprint
            )
            expected = build_dataset_review_authority_record(
                request,
                authority_reference=authority_reference,
                authority_version=1,
            ).record_fingerprint
            actual = owner.execute(
                "SELECT dohalm_dataset_governance_v1."
                "compute_dataset_review_record_fingerprint("
                "%s::varchar,%s::varchar,%s::varchar,%s::char(71),"
                "%s::varchar,%s::varchar,%s::timestamptz,%s::varchar,"
                "%s::varchar,%s::smallint)",
                (
                    request.identity.object_id,
                    request.identity.dataset_id,
                    request.identity.dataset_version,
                    request.proposal_fingerprint,
                    "reviewing",
                    request.reviewer_reference,
                    request.review_started_at,
                    request.request_reference,
                    authority_reference,
                    1,
                ),
            ).fetchone()
            assert actual is not None and actual[0].rstrip() == expected

    suffix = uuid.uuid4().hex
    corruption_cases = (
        ("fingerprint", {"record_fingerprint": "sha256:" + "0" * 64}),
        ("reviewer", {"reviewer_reference": "reviewer:synthetic-mismatch"}),
        (
            "authority",
            {"authority_reference": "dataset-review:" + "f" * 64},
        ),
    )
    with _dataset_review_adapter(c1_postgres) as adapter:
        for name, updates in corruption_cases:
            proposal, fingerprint = _create_authoritative_proposal(
                c1_postgres, suffix + name
            )
            adapter.start_review(_review_request(proposal, fingerprint))
            column, value = next(iter(updates.items()))
            with c1_postgres.factory.connection() as owner, owner.transaction():
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_review_authority DISABLE TRIGGER USER"
                )
                owner.execute(
                    f"UPDATE dohalm_dataset_governance_v1."
                    f"dataset_version_review_authority SET {column}=%s "
                    "WHERE object_id=%s",
                    (value, proposal.identity.object_id),
                )
                owner.execute(
                    "ALTER TABLE dohalm_dataset_governance_v1."
                    "dataset_version_review_authority ENABLE TRIGGER USER"
                )
            with pytest.raises(DatasetReviewAuthorityError) as corrupt:
                adapter.read_authoritative_review(
                    proposal.identity, proposal_fingerprint=fingerprint
                )
            assert corrupt.value.code == "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"

        proposal, fingerprint = _create_authoritative_proposal(
            c1_postgres, suffix + "invariants"
        )
        adapter.start_review(_review_request(proposal, fingerprint))
        invariant_cases = (
            ("dataset_id", "synthetic-mismatched-dataset", "23503"),
            ("proposal_fingerprint", "sha256:" + "9" * 64, "23503"),
            ("lifecycle_state", "approved", "23514"),
            ("authority_version", 2, "23514"),
            ("schema_revision", 2, "23514"),
        )
        with c1_postgres.factory.connection() as owner:
            for column, value, sqlstate in invariant_cases:
                with pytest.raises(Exception) as blocked, owner.transaction():
                    owner.execute(
                        "ALTER TABLE dohalm_dataset_governance_v1."
                        "dataset_version_review_authority DISABLE TRIGGER USER"
                    )
                    owner.execute(
                        f"UPDATE dohalm_dataset_governance_v1."
                        f"dataset_version_review_authority SET {column}=%s "
                        "WHERE object_id=%s",
                        (value, proposal.identity.object_id),
                    )
                assert blocked.value.sqlstate == sqlstate
