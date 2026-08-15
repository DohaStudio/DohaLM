"""Local single-user PostgreSQL activation and non-training readiness.

The module is an explicit local-only composition boundary. Importing it never
connects to PostgreSQL, starts Docker, reads Dataset content, initializes CUDA,
or invokes Training.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.postgres_c1 import apply_c1_migrations, load_c1_migrations

from .errors import TrainingError
from .production_composition import (
    _PostgresTrainingCompositionConfiguration,
    _ProductionTrainingActivationDecision,
    _compose_postgres_training_host,
)
from .production_full_pretraining_host import ProductionTrainingHostResult
from .production_host_foundation import (
    ProductionTrainingHostIntent,
    TrainingDecisionResolutionRequest,
    TrainingExecutionIssuerDecisionValue,
    TrainingOrchestrationPhase,
    _resolve_trusted_training_decision_resolution,
)
from .production_orchestration_seams import (
    _build_training_execution_request_from_prerequisites,
    _resolve_training_prerequisites,
)


POSTGRES_IMAGE = (
    "postgres:16.15-alpine@"
    "sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571"
)
_PROFILE = "local_single_user"
_PROVIDER = "postgresql"
_LABEL = "com.dohastudio.local-training.activation"
_SAFE_NAME = re.compile(r"dohalm-local-[a-z0-9-]{1,40}\Z")
_DB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,62}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}\Z")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ROLE_FILES = {
    "migration_owner": "migration_owner.password",
    "producer": "producer.password",
    "resolver": "resolver.password",
    "journal": "journal.password",
}


class LocalActivationStatus(str, Enum):
    READY = "READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_APPROVED = "NOT_APPROVED"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    CONTRACT_ERROR = "CONTRACT_ERROR"


def _failure(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _configuration_failure() -> TrainingError:
    return _failure(
        "LOCAL_TRAINING_CONFIGURATION_INVALID",
        "Valid redacted local single-user activation configuration is required.",
    )


def _mapping_failure() -> TrainingError:
    return _failure(
        "LOCAL_TRAINING_DATASET_MAPPING_INVALID",
        "The redacted local Dataset mapping is missing or is not current.",
    )


def _safe_relative(value: object) -> bool:
    if type(value) is not str or not value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
            raise ValueError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise _configuration_failure() from None
    if type(value) is not dict:
        raise _configuration_failure()
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, repr=False)
class LocalDatasetMappingConfiguration:
    root_environment_variable: str
    manifest_relative_path: str
    expected_manifest_sha256: str
    train_split_relative_path: str
    evaluation_split_relative_path: str
    tokenizer_reference_relative_path: str
    training_config_reference_relative_path: str

    def __post_init__(self) -> None:
        relatives = (
            self.manifest_relative_path,
            self.train_split_relative_path,
            self.evaluation_split_relative_path,
            self.tokenizer_reference_relative_path,
            self.training_config_reference_relative_path,
        )
        if (
            _REFERENCE.fullmatch(self.root_environment_variable) is None
            or _FINGERPRINT.fullmatch(self.expected_manifest_sha256) is None
            or not all(_safe_relative(value) for value in relatives)
        ):
            raise _configuration_failure()

    def __repr__(self) -> str:
        return "LocalDatasetMappingConfiguration(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class LocalDockerConfiguration:
    container_name: str
    network_name: str
    volume_name: str
    correlation_id: str

    def __post_init__(self) -> None:
        if (
            not all(
                type(value) is str and _SAFE_NAME.fullmatch(value) is not None
                for value in (self.container_name, self.network_name, self.volume_name)
            )
            or _REFERENCE.fullmatch(self.correlation_id) is None
            or len({self.container_name, self.network_name, self.volume_name}) != 3
        ):
            raise _configuration_failure()

    def __repr__(self) -> str:
        return "LocalDockerConfiguration(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class LocalSingleUserActivationConfiguration:
    profile: str
    provider: str
    host: str
    database: str
    credential_directory_environment_variable: str
    run_package_environment_variable: str
    output_root_environment_variable: str
    application_name: str
    process_boundary_id: str
    decision_authority_id: str
    prerequisite_policy_reference: str
    decision_policy_reference: str
    activation_authority_reference: str
    activation_evidence_reference: str
    connect_timeout_seconds: int
    statement_timeout_ms: int
    transaction_timeout_ms: int
    docker: LocalDockerConfiguration
    dataset: LocalDatasetMappingConfiguration

    def __post_init__(self) -> None:
        try:
            from uuid import UUID

            decision_id_valid = (
                str(UUID(self.decision_authority_id)) == self.decision_authority_id
            )
        except ValueError:
            decision_id_valid = False
        references = (
            self.credential_directory_environment_variable,
            self.run_package_environment_variable,
            self.output_root_environment_variable,
            self.application_name,
            self.process_boundary_id,
            self.prerequisite_policy_reference,
            self.decision_policy_reference,
            self.activation_authority_reference,
            self.activation_evidence_reference,
        )
        if (
            self.profile != _PROFILE
            or self.provider != _PROVIDER
            or self.host != "127.0.0.1"
            or _DB_NAME.fullmatch(self.database) is None
            or not all(_REFERENCE.fullmatch(value) is not None for value in references)
            or not decision_id_valid
            or type(self.connect_timeout_seconds) is not int
            or not 1 <= self.connect_timeout_seconds <= 60
            or type(self.statement_timeout_ms) is not int
            or not 1 <= self.statement_timeout_ms <= 300_000
            or type(self.transaction_timeout_ms) is not int
            or not self.statement_timeout_ms <= self.transaction_timeout_ms <= 600_000
            or type(self.docker) is not LocalDockerConfiguration
            or type(self.dataset) is not LocalDatasetMappingConfiguration
        ):
            raise _configuration_failure()

    def __repr__(self) -> str:
        return "LocalSingleUserActivationConfiguration(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class LocalRoleCredentials:
    migration_owner: str
    producer: str
    resolver: str
    journal: str

    def __post_init__(self) -> None:
        values = (self.migration_owner, self.producer, self.resolver, self.journal)
        if not all(
            type(value) is str and 16 <= len(value) <= 128 for value in values
        ) or len(set(values)) != len(values):
            raise _configuration_failure()

    def __repr__(self) -> str:
        return "LocalRoleCredentials(<redacted>)"


@dataclass(frozen=True, slots=True)
class LocalPostgresBootstrapResult:
    image: str
    host: str
    port: int
    database: str
    migration_versions: tuple[int, ...]
    migration_current: bool
    binding_verified: bool
    durable_volume_preserved: bool


def load_local_activation_configuration(
    path: Path,
) -> LocalSingleUserActivationConfiguration:
    value = _json_object(path)
    try:
        docker = LocalDockerConfiguration(**value.pop("docker"))
        dataset = LocalDatasetMappingConfiguration(**value.pop("dataset"))
        return LocalSingleUserActivationConfiguration(
            **value, docker=docker, dataset=dataset
        )
    except (KeyError, TypeError, AttributeError, TrainingError):
        raise _configuration_failure() from None


def load_local_role_credentials(
    configuration: LocalSingleUserActivationConfiguration,
    environment: Mapping[str, str] | None = None,
) -> tuple[LocalRoleCredentials, Path]:
    env = os.environ if environment is None else environment
    raw_directory = env.get(configuration.credential_directory_environment_variable)
    if not raw_directory:
        raise _configuration_failure()
    directory = Path(raw_directory).expanduser().resolve()
    repository = Path(__file__).resolve().parents[2]
    try:
        directory.relative_to(repository)
    except ValueError:
        pass
    else:
        raise _configuration_failure()
    if not directory.is_dir() or directory.is_symlink():
        raise _configuration_failure()
    values: dict[str, str] = {}
    for role, filename in _ROLE_FILES.items():
        path = directory / filename
        if not path.is_file() or path.is_symlink():
            raise _configuration_failure()
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise _configuration_failure() from None
        values[role] = value
    return LocalRoleCredentials(**values), directory


def _run_command(
    command: Sequence[str], *, environment: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=None if environment is None else dict(environment),
    )


class LocalDurablePostgresBootstrapper:
    """Own only explicitly labelled local Docker resources and preserve data."""

    def __init__(
        self,
        configuration: LocalSingleUserActivationConfiguration,
        credentials: LocalRoleCredentials,
        credential_directory: Path,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
    ) -> None:
        self._configuration = configuration
        self._credentials = credentials
        self._credential_directory = credential_directory
        self._run = command_runner

    def bootstrap(self) -> LocalPostgresBootstrapResult:
        self._ensure_resource("network", self._configuration.docker.network_name)
        self._ensure_resource("volume", self._configuration.docker.volume_name)
        if not self._container_exists():
            self._create_container()
        else:
            self._assert_owned("container", self._configuration.docker.container_name)
            self._run(("docker", "start", self._configuration.docker.container_name))
        port = self._published_port()
        self._verify_loopback_binding(port)
        self._wait_for_database(port)
        versions = self._migrate_and_configure_roles(port)
        return LocalPostgresBootstrapResult(
            image=POSTGRES_IMAGE,
            host="127.0.0.1",
            port=port,
            database=self._configuration.database,
            migration_versions=versions,
            migration_current=True,
            binding_verified=True,
            durable_volume_preserved=True,
        )

    def stop(self) -> None:
        if self._container_exists():
            self._assert_owned("container", self._configuration.docker.container_name)
            self._run(("docker", "stop", self._configuration.docker.container_name))

    def destroy(self, *, confirm_correlation_id: str) -> None:
        if confirm_correlation_id != self._configuration.docker.correlation_id:
            raise _configuration_failure()
        container = self._configuration.docker.container_name
        if self._container_exists():
            self._assert_owned("container", container)
            self._run(("docker", "rm", "-f", container))
        for kind, name in (
            ("volume", self._configuration.docker.volume_name),
            ("network", self._configuration.docker.network_name),
        ):
            if self._resource_exists(kind, name):
                self._assert_owned(kind, name)
                self._run(("docker", kind, "rm", name))

    def _label_value(self) -> str:
        return self._configuration.docker.correlation_id

    def _resource_exists(self, kind: str, name: str) -> bool:
        try:
            self._run(("docker", kind, "inspect", name))
        except subprocess.CalledProcessError:
            return False
        return True

    def _container_exists(self) -> bool:
        return self._resource_exists(
            "container", self._configuration.docker.container_name
        )

    def _assert_owned(self, kind: str, name: str) -> None:
        result = self._run(
            (
                "docker",
                kind,
                "inspect",
                "--format",
                f'{{{{ index .Config.Labels "{_LABEL}" }}}}'
                if kind == "container"
                else f'{{{{ index .Labels "{_LABEL}" }}}}',
                name,
            )
        )
        if result.stdout.strip() != self._label_value():
            raise _failure(
                "LOCAL_TRAINING_DOCKER_OWNERSHIP_CONFLICT",
                "A local Docker resource is not owned by this activation configuration.",
            )

    def _ensure_resource(self, kind: str, name: str) -> None:
        if self._resource_exists(kind, name):
            self._assert_owned(kind, name)
            return
        command = [
            "docker",
            kind,
            "create",
            "--label",
            f"{_LABEL}={self._label_value()}",
        ]
        if kind == "network":
            command.extend(("--driver", "bridge"))
        command.append(name)
        self._run(tuple(command))

    def _create_container(self) -> None:
        owner_file = (
            self._credential_directory / _ROLE_FILES["migration_owner"]
        ).resolve()
        command = (
            "docker",
            "create",
            "--name",
            self._configuration.docker.container_name,
            "--label",
            f"{_LABEL}={self._label_value()}",
            "--network",
            self._configuration.docker.network_name,
            "--mount",
            f"type=volume,src={self._configuration.docker.volume_name},dst=/var/lib/postgresql/data",
            "--mount",
            f"type=bind,src={owner_file},dst=/run/secrets/dohalm-bootstrap-password,readonly",
            "-e",
            "POSTGRES_PASSWORD_FILE=/run/secrets/dohalm-bootstrap-password",
            "-e",
            f"POSTGRES_DB={self._configuration.database}",
            "-p",
            "127.0.0.1::5432",
            POSTGRES_IMAGE,
        )
        self._run(command)
        self._run(("docker", "start", self._configuration.docker.container_name))

    def _published_port(self) -> int:
        result = self._run(
            ("docker", "port", self._configuration.docker.container_name, "5432/tcp")
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) != 1 or not lines[0].startswith("127.0.0.1:"):
            raise _failure(
                "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                "PostgreSQL must be published on IPv4 loopback only.",
            )
        try:
            return int(lines[0].rsplit(":", 1)[1])
        except ValueError:
            raise _failure(
                "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                "PostgreSQL must use a valid dynamic loopback port.",
            ) from None

    def _verify_loopback_binding(self, port: int) -> None:
        inspected = self._run(
            (
                "docker",
                "inspect",
                "--format",
                "{{json .NetworkSettings.Ports}}",
                self._configuration.docker.container_name,
            )
        )
        try:
            bindings = json.loads(inspected.stdout)["5432/tcp"]
        except (KeyError, TypeError, json.JSONDecodeError):
            raise _failure(
                "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                "The PostgreSQL publish binding could not be verified.",
            ) from None
        if bindings != [{"HostIp": "127.0.0.1", "HostPort": str(port)}]:
            raise _failure(
                "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                "PostgreSQL must not bind to a wildcard or external interface.",
            )
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        if platform.system() == "Windows":
            listener = self._run(
                (
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$listeners = Get-NetTCPConnection -State Listen -LocalPort "
                    f"{port} -ErrorAction Stop; "
                    "$listeners | Select-Object -ExpandProperty LocalAddress",
                )
            )
            addresses = {
                line.strip() for line in listener.stdout.splitlines() if line.strip()
            }
            if addresses != {"127.0.0.1"}:
                raise _failure(
                    "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                    "The host listener must be IPv4 loopback only.",
                )
        else:
            listener = self._run(("ss", "-H", "-ltn", "sport", "=", f":{port}"))
            addresses = [
                line.split()[3] for line in listener.stdout.splitlines() if line.strip()
            ]
            if addresses != [f"127.0.0.1:{port}"]:
                raise _failure(
                    "LOCAL_TRAINING_PUBLIC_BINDING_DENIED",
                    "The host listener must be IPv4 loopback only.",
                )

    def _wait_for_database(self, port: int) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                import psycopg

                with psycopg.connect(
                    host="127.0.0.1",
                    port=port,
                    dbname=self._configuration.database,
                    user="postgres",
                    password=self._credentials.migration_owner,
                    connect_timeout=2,
                    sslmode="disable",
                ):
                    return
            except Exception:
                time.sleep(0.25)
        raise _failure(
            "LOCAL_TRAINING_POSTGRES_UNAVAILABLE",
            "The local PostgreSQL database did not become ready.",
        )

    def _migrate_and_configure_roles(self, port: int) -> tuple[int, ...]:
        try:
            import psycopg
            from psycopg import sql

            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                dbname=self._configuration.database,
                user="postgres",
                password=self._credentials.migration_owner,
                connect_timeout=self._configuration.connect_timeout_seconds,
                sslmode="disable",
                autocommit=False,
            ) as connection:
                apply_c1_migrations(connection)
                with connection.transaction():
                    for role, password in (
                        (
                            "dohalm_training_authority_producer",
                            self._credentials.producer,
                        ),
                        ("dohalm_training_resolver", self._credentials.resolver),
                        ("dohalm_training_journal", self._credentials.journal),
                    ):
                        connection.execute(
                            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                                sql.Identifier(role), sql.Literal(password)
                            )
                        )
                rows = connection.execute(
                    "SELECT version, name, sha256 FROM dohalm_training_v1.schema_migration ORDER BY version"
                ).fetchall()
        except TrainingError:
            raise
        except Exception:
            raise _failure(
                "LOCAL_TRAINING_POSTGRES_BOOTSTRAP_FAILED",
                "The redacted local PostgreSQL bootstrap failed.",
            ) from None
        migrations = load_c1_migrations()
        expected = [(item.version, item.name, item.sha256) for item in migrations]
        actual = [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
        if actual != expected:
            raise _failure(
                "LOCAL_TRAINING_MIGRATION_DRIFT",
                "The local PostgreSQL migration inventory is not current.",
            )
        return tuple(item.version for item in migrations)


def _resolve_container_port(
    configuration: LocalSingleUserActivationConfiguration,
) -> int:
    try:
        result = _run_command(
            ("docker", "port", configuration.docker.container_name, "5432/tcp")
        )
        line = result.stdout.strip()
        if "\n" in line or not line.startswith("127.0.0.1:"):
            raise ValueError
        return int(line.rsplit(":", 1)[1])
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise _failure(
            "LOCAL_TRAINING_POSTGRES_UNAVAILABLE",
            "The local PostgreSQL dynamic loopback port is unavailable.",
        ) from None


def _composition_configuration(
    configuration: LocalSingleUserActivationConfiguration,
    credentials: LocalRoleCredentials,
    port: int,
) -> _PostgresTrainingCompositionConfiguration:
    return _PostgresTrainingCompositionConfiguration(
        provider=_PROVIDER,
        environment=_PROFILE,
        host="127.0.0.1",
        port=port,
        database=configuration.database,
        resolver_password=credentials.resolver,
        journal_password=credentials.journal,
        application_name=configuration.application_name,
        process_boundary_id=configuration.process_boundary_id,
        decision_authority_id=configuration.decision_authority_id,
        prerequisite_policy_reference=configuration.prerequisite_policy_reference,
        decision_policy_reference=configuration.decision_policy_reference,
        activation_authority_reference=configuration.activation_authority_reference,
        activation_evidence_reference=configuration.activation_evidence_reference,
        connect_timeout_seconds=configuration.connect_timeout_seconds,
        statement_timeout_ms=configuration.statement_timeout_ms,
        transaction_timeout_ms=configuration.transaction_timeout_ms,
        sslmode="disable",
        sslrootcert=None,
    )


def _activation_decision(
    configuration: LocalSingleUserActivationConfiguration,
) -> _ProductionTrainingActivationDecision:
    return _ProductionTrainingActivationDecision(
        authorized=True,
        provider=_PROVIDER,
        authority_reference=configuration.activation_authority_reference,
        evidence_reference=configuration.activation_evidence_reference,
        process_boundary_id=configuration.process_boundary_id,
    )


def _dataset_mapping_status(
    configuration: LocalSingleUserActivationConfiguration,
    environment: Mapping[str, str],
) -> tuple[bool, str]:
    raw_root = environment.get(configuration.dataset.root_environment_variable)
    if not raw_root:
        return False, LocalActivationStatus.NOT_CONFIGURED.value
    root = Path(raw_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise _mapping_failure()
    paths = [
        root / configuration.dataset.manifest_relative_path,
        root / configuration.dataset.train_split_relative_path,
        root / configuration.dataset.evaluation_split_relative_path,
        root / configuration.dataset.tokenizer_reference_relative_path,
        root / configuration.dataset.training_config_reference_relative_path,
    ]
    if not all(path.exists() for path in paths):
        raise _mapping_failure()
    manifest = paths[0]
    if not manifest.is_file():
        raise _mapping_failure()
    actual = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    if actual != configuration.dataset.expected_manifest_sha256:
        raise _mapping_failure()
    return True, "CURRENT"


def _output_probe(
    configuration: LocalSingleUserActivationConfiguration,
    environment: Mapping[str, str],
) -> bool:
    raw = environment.get(configuration.output_root_environment_variable)
    if not raw:
        return False
    root = Path(raw).expanduser().resolve()
    repository = Path(__file__).resolve().parents[2]
    try:
        root.relative_to(repository)
    except ValueError:
        pass
    else:
        raise _configuration_failure()
    root.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".dohalm-readiness-", dir=root)
    os.close(descriptor)
    Path(name).unlink()
    return True


def _gpu_probe(torch_module: Any | None = None) -> dict[str, Any]:
    try:
        torch = torch_module or importlib.import_module("torch")
        available = bool(torch.cuda.is_available())
        if not available:
            return {
                "available": False,
                "name": None,
                "total_vram_bytes": None,
                "free_vram_bytes": None,
                "fp16_supported": False,
            }
        properties = torch.cuda.get_device_properties(0)
        free, total = torch.cuda.mem_get_info(0)
        major = int(getattr(properties, "major", 0))
        return {
            "available": True,
            "name": str(properties.name),
            "total_vram_bytes": int(total),
            "free_vram_bytes": int(free),
            "fp16_supported": major >= 7,
        }
    except Exception:
        return {
            "available": False,
            "name": None,
            "total_vram_bytes": None,
            "free_vram_bytes": None,
            "fp16_supported": False,
        }


def _load_run_intent(
    configuration: LocalSingleUserActivationConfiguration,
    environment: Mapping[str, str],
) -> ProductionTrainingHostIntent | None:
    raw = environment.get(configuration.run_package_environment_variable)
    if not raw:
        return None
    package_path = Path(raw).expanduser().resolve()
    value = _json_object(package_path)
    try:
        if set(value) != {"schema_version", "intent"} or value["schema_version"] != 1:
            raise ValueError
        intent = ProductionTrainingHostIntent(**value["intent"])
    except (KeyError, TypeError, ValueError, TrainingError):
        raise _failure(
            "LOCAL_TRAINING_RUN_PACKAGE_INVALID",
            "A valid redacted immutable run package is required.",
        ) from None
    return intent


def inspect_local_training_readiness(
    configuration: LocalSingleUserActivationConfiguration,
    *,
    environment: Mapping[str, str] | None = None,
    torch_module: Any | None = None,
    port_resolver: Callable[
        [LocalSingleUserActivationConfiguration], int
    ] = _resolve_container_port,
) -> dict[str, Any]:
    """Inspect local activation without journal mutation or backend invocation."""

    env = os.environ if environment is None else environment
    result: dict[str, Any] = {
        "status": LocalActivationStatus.NOT_CONFIGURED.value,
        "profile": _PROFILE,
        "configuration_valid": True,
        "database": {
            "configured": False,
            "migration_current": False,
            "roles_reachable": False,
        },
        "dataset_mapping": {"configured": False, "current": False},
        "run_package": {"configured": False, "approval_current": False},
        "gpu": _gpu_probe(torch_module),
        "output_root_writable": False,
        "training_backend_invocation_count": 0,
        "journal_mutation_count": 0,
        "local_composition_activation_active": False,
        "production_activation_authorized": False,
        "training_execution_authorized": False,
    }
    root = None
    resolved = None
    try:
        credentials, _ = load_local_role_credentials(configuration, env)
        dataset_configured, dataset_status = _dataset_mapping_status(configuration, env)
        result["dataset_mapping"] = {
            "configured": dataset_configured,
            "current": dataset_status == "CURRENT",
        }
        result["output_root_writable"] = _output_probe(configuration, env)
        if not dataset_configured or not result["output_root_writable"]:
            return result
        port = port_resolver(configuration)
        root = _compose_postgres_training_host(
            _composition_configuration(configuration, credentials, port)
        )
        preflight = root.preflight()
        root.startup(_activation_decision(configuration))
        result["local_composition_activation_active"] = True
        result["database"] = {
            "configured": True,
            "migration_current": True,
            "roles_reachable": preflight.role_separation,
            "host": "127.0.0.1",
            "port": port,
        }
        intent = _load_run_intent(configuration, env)
        if intent is None:
            result["status"] = LocalActivationStatus.NOT_APPROVED.value
            return result
        result["run_package"]["configured"] = True
        resolved = _resolve_training_prerequisites(
            root._required_prerequisite(), intent
        )
        request = _build_training_execution_request_from_prerequisites(intent, resolved)
        decision_request = TrainingDecisionResolutionRequest(
            intent=intent,
            decision_authority_id=configuration.decision_authority_id,
            request_fingerprint=request.request_fingerprint,
            dataset_version_id=resolved.dataset_version_id,
            dataset_manifest_id=resolved.dataset_manifest_id,
            dataset_pair_authority_id=resolved.dataset_pair_authority_id,
            dataset_pair_fingerprint=resolved.dataset_pair_fingerprint,
            config_fingerprint=resolved.config_fingerprint,
            readiness_fingerprint=resolved.readiness_fingerprint,
            source_commit=resolved.source_commit,
            prerequisite_policy_reference=resolved.provenance.resolution_policy_reference,
        )
        decision = _resolve_trusted_training_decision_resolution(
            root._required_decision(), decision_request
        )
        record = root._required_journal().read(intent.run_id)
        if record is not None and record.phase not in {
            TrainingOrchestrationPhase.SUCCEEDED,
            TrainingOrchestrationPhase.FAILED,
        }:
            raise _failure(
                "LOCAL_TRAINING_NON_TERMINAL_RUN_REQUIRES_RECONCILIATION",
                "A non-terminal local run must be reconciled manually.",
            )
        approved = (
            decision.decision.decision is TrainingExecutionIssuerDecisionValue.APPROVED
        )
        result["run_package"]["approval_current"] = approved
        result["training_execution_authorized"] = approved
        result["status"] = (
            LocalActivationStatus.READY.value
            if approved
            else LocalActivationStatus.NOT_APPROVED.value
        )
        return result
    except TrainingError as error:
        if error.code in {
            "LOCAL_TRAINING_CONFIGURATION_INVALID",
            "LOCAL_TRAINING_DATASET_MAPPING_INVALID",
            "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
        }:
            result["status"] = LocalActivationStatus.NOT_CONFIGURED.value
        elif error.code in {
            "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
            "TRAINING_EXECUTION_APPROVAL_DENIED",
        }:
            result["status"] = LocalActivationStatus.NOT_APPROVED.value
        elif error.code.startswith("TRAINING_DATABASE") or error.code.startswith(
            "LOCAL_TRAINING_POSTGRES"
        ):
            result["status"] = LocalActivationStatus.ENVIRONMENT_ERROR.value
        else:
            result["status"] = LocalActivationStatus.CONTRACT_ERROR.value
        result["error_code"] = error.code
        return result
    except (OSError, RuntimeError):
        result["status"] = LocalActivationStatus.ENVIRONMENT_ERROR.value
        result["error_code"] = "LOCAL_TRAINING_ENVIRONMENT_ERROR"
        return result
    finally:
        if resolved is not None and root is not None:
            root._required_prerequisite().release(resolved)
        if root is not None:
            root.shutdown()


def execute_local_training(
    configuration: LocalSingleUserActivationConfiguration,
    *,
    environment: Mapping[str, str] | None = None,
) -> ProductionTrainingHostResult:
    """Execute only through the existing Host and an exact approved run package."""

    env = os.environ if environment is None else environment
    credentials, _ = load_local_role_credentials(configuration, env)
    intent = _load_run_intent(configuration, env)
    if intent is None:
        raise _failure(
            "TRAINING_EXECUTION_APPROVAL_REQUIRED",
            "An exact immutable run package and approval are required.",
        )
    dataset_configured, _ = _dataset_mapping_status(configuration, env)
    if not dataset_configured or not _output_probe(configuration, env):
        raise _mapping_failure()
    port = _resolve_container_port(configuration)
    root = _compose_postgres_training_host(
        _composition_configuration(configuration, credentials, port)
    )
    try:
        root.preflight()
        host = root.startup(_activation_decision(configuration))
        return host.run(intent)
    finally:
        root.shutdown()


def bootstrap_local_postgres(
    configuration: LocalSingleUserActivationConfiguration,
    *,
    environment: Mapping[str, str] | None = None,
) -> LocalPostgresBootstrapResult:
    credentials, directory = load_local_role_credentials(configuration, environment)
    return LocalDurablePostgresBootstrapper(
        configuration, credentials, directory
    ).bootstrap()


def result_json(value: object) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=lambda item: item.value if isinstance(item, Enum) else str(item),
    )


__all__ = [
    "LocalActivationStatus",
    "LocalDurablePostgresBootstrapper",
    "LocalPostgresBootstrapResult",
    "LocalSingleUserActivationConfiguration",
    "bootstrap_local_postgres",
    "execute_local_training",
    "inspect_local_training_readiness",
    "load_local_activation_configuration",
    "load_local_role_credentials",
    "result_json",
]
