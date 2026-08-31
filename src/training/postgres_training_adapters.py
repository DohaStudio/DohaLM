"""Package-private PostgreSQL adapters for the non-activating C2 boundary."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import yaml

from src.data.checksums import canonical_json_bytes

from .dataset_training_entry import evaluate_dataset_training_entry
from .errors import TrainingError
from .execution_issuer import TrainingExecutionIssuerDecisionValue
from .full_pretraining import FullPretrainingConfig, inspect_full_pretraining_readiness
from .production_host_foundation import (
    ResolvedTrainingExecutionDecision,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationClaimResult,
    TrainingOrchestrationClaimStatus,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrainingOrchestrationTransition,
    TrustedDecisionProvenance,
    TrustedDecisionResolution,
)
from .production_orchestration_seams import (
    ResolvedTrainingPrerequisites,
    TrainingPrerequisiteResolutionRequest,
    TrustedPrerequisiteProvenance,
)

if TYPE_CHECKING:
    from psycopg import Connection


_SCHEMA = "dohalm_training_v1"
_AUTHORITY_PRODUCER_ROLE = "dohalm_training_authority_producer"
_INTENT_WRITER_ROLE = "dohalm_training_intent_writer"
_RESOLVER_ROLE = "dohalm_training_resolver"
_JOURNAL_ROLE = "dohalm_training_journal"
_ROLES = frozenset(
    {_AUTHORITY_PRODUCER_ROLE, _INTENT_WRITER_ROLE, _RESOLVER_ROLE, _JOURNAL_ROLE}
)
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_APPLICATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_EXPECTED_JOURNAL_COLUMNS = frozenset(
    {
        "run_id",
        "request_fingerprint",
        "intent_fingerprint",
        "host_schema_version",
        "host_lifecycle_version",
        "orchestration_correlation_id",
        "dataset_version_id",
        "dataset_manifest_id",
        "dataset_pair_fingerprint",
        "config_fingerprint",
        "readiness_fingerprint",
        "source_commit",
        "prerequisite_resolution_policy_reference",
        "authorization_id",
        "issuer_id",
        "approver_reference",
        "evidence_reference",
        "authorization_fingerprint",
        "decision_evidence_fingerprint",
        "decision_policy_reference",
        "phase",
        "journal_version",
        "backend_entered",
        "reconciliation_required",
        "reconciliation_reason_code",
        "process_boundary_id",
        "created_at",
        "updated_at",
        "reservation_group_id",
    }
)
_CLAIM_JOURNAL_COLUMN_MAP = {
    "run_id": "journal_run_id",
    "request_fingerprint": "journal_request_fingerprint",
    "intent_fingerprint": "journal_intent_fingerprint",
    "host_schema_version": "journal_host_schema_version",
    "host_lifecycle_version": "journal_host_lifecycle_version",
    "orchestration_correlation_id": "journal_orchestration_correlation_id",
    "dataset_version_id": "journal_dataset_version_id",
    "dataset_manifest_id": "journal_dataset_manifest_id",
    "dataset_pair_fingerprint": "journal_dataset_pair_fingerprint",
    "config_fingerprint": "journal_config_fingerprint",
    "readiness_fingerprint": "journal_readiness_fingerprint",
    "source_commit": "journal_source_commit",
    "prerequisite_resolution_policy_reference": "journal_prerequisite_policy_reference",
    "authorization_id": "journal_authorization_id",
    "issuer_id": "journal_issuer_id",
    "approver_reference": "journal_approver_reference",
    "evidence_reference": "journal_evidence_reference",
    "authorization_fingerprint": "journal_authorization_fingerprint",
    "decision_evidence_fingerprint": "journal_decision_evidence_fingerprint",
    "decision_policy_reference": "journal_decision_policy_reference",
    "phase": "journal_phase",
    "journal_version": "journal_version",
    "backend_entered": "journal_backend_entered",
    "reconciliation_required": "journal_reconciliation_required",
    "reconciliation_reason_code": "journal_reconciliation_reason_code",
    "process_boundary_id": "journal_process_boundary_id",
    "created_at": "journal_created_at",
    "updated_at": "journal_updated_at",
    "reservation_group_id": "journal_reservation_group_id",
}
if frozenset(_CLAIM_JOURNAL_COLUMN_MAP) != _EXPECTED_JOURNAL_COLUMNS:
    raise RuntimeError("C2 claim result map is incomplete")


def _adapter_error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


class _PostgresCommitOutcomeUnknown(RuntimeError):
    pass


class _ConnectionFactory(Protocol):
    role: str

    @contextmanager
    def transaction(
        self, *, isolation: str, read_only: bool
    ) -> Iterator[Connection[Any]]: ...


@dataclass(frozen=True, slots=True, repr=False)
class _PostgresTrainingConnectionSettings:
    """Explicit role credential and transport policy; never a raw DSN."""

    environment: str
    host: str
    port: int
    database: str
    user: str
    password: str
    role: str
    application_name: str
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 15_000
    transaction_timeout_ms: int = 30_000
    sslmode: str = "verify-full"
    sslrootcert: Path | None = None

    def __post_init__(self) -> None:
        isolated = self.environment == "isolated_test"
        local_single_user = self.environment == "local_single_user"
        production = self.environment == "production"
        loopback = self.host == "127.0.0.1"
        valid_tls = (
            production
            and self.sslmode == "verify-full"
            and isinstance(self.sslrootcert, Path)
            and self.sslrootcert.is_absolute()
        ) or (
            (isolated or local_single_user)
            and loopback
            and self.sslmode == "disable"
            and self.sslrootcert is None
        )
        if (
            not (isolated or local_single_user or production)
            or not isinstance(self.host, str)
            or not self.host
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
            or _REFERENCE.fullmatch(self.database) is None
            or self.role not in _ROLES
            or self.user != self.role
            or type(self.password) is not str
            or not self.password
            or _APPLICATION_NAME.fullmatch(self.application_name) is None
            or type(self.connect_timeout_seconds) is not int
            or not 1 <= self.connect_timeout_seconds <= 60
            or type(self.statement_timeout_ms) is not int
            or not 1 <= self.statement_timeout_ms <= 300_000
            or type(self.transaction_timeout_ms) is not int
            or not self.statement_timeout_ms <= self.transaction_timeout_ms <= 600_000
            or not valid_tls
        ):
            raise _adapter_error(
                "TRAINING_DATABASE_CONFIGURATION_INVALID",
                "Valid role-scoped PostgreSQL configuration is required.",
            )

    def __repr__(self) -> str:
        return "_PostgresTrainingConnectionSettings(<redacted>)"


class _PostgresTrainingConnectionFactory:
    """Open one Psycopg connection for one explicit transaction and role."""

    def __init__(self, settings: _PostgresTrainingConnectionSettings) -> None:
        if type(settings) is not _PostgresTrainingConnectionSettings:
            raise TypeError("PostgreSQL settings are required")
        self._settings = settings
        self.role = settings.role

    def __repr__(self) -> str:
        return "_PostgresTrainingConnectionFactory(<redacted>)"

    @contextmanager
    def transaction(
        self, *, isolation: str, read_only: bool
    ) -> Iterator[Connection[Any]]:
        if isolation not in {"REPEATABLE READ", "READ COMMITTED"}:
            raise ValueError("unsupported isolation")
        connection = None
        try:
            import psycopg

            kwargs: dict[str, Any] = {
                "host": self._settings.host,
                "port": self._settings.port,
                "dbname": self._settings.database,
                "user": self._settings.user,
                "password": self._settings.password,
                "connect_timeout": self._settings.connect_timeout_seconds,
                "application_name": self._settings.application_name,
                "sslmode": self._settings.sslmode,
                "options": "-c timezone=UTC -c client_encoding=UTF8",
                "autocommit": False,
            }
            if self._settings.sslrootcert is not None:
                kwargs["sslrootcert"] = str(self._settings.sslrootcert)
            connection = psycopg.connect(**kwargs)
            operation_completed = False
            try:
                with connection.transaction():
                    access = "READ ONLY" if read_only else "READ WRITE"
                    connection.execute(
                        f"SET TRANSACTION ISOLATION LEVEL {isolation} {access}"
                    )
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true), "
                        "set_config('idle_in_transaction_session_timeout', %s, true)",
                        (
                            str(self._settings.statement_timeout_ms),
                            str(self._settings.transaction_timeout_ms),
                        ),
                    )
                    current_user = connection.execute("SELECT current_user").fetchone()
                    if current_user != (self.role,):
                        raise _adapter_error(
                            "TRAINING_DATABASE_PERMISSION_DENIED",
                            "The PostgreSQL connection role is not authorized.",
                        )
                    yield connection
                    operation_completed = True
            except Exception as error:
                if operation_completed and _is_connection_interruption(error):
                    raise _PostgresCommitOutcomeUnknown from None
                raise
        finally:
            if connection is not None:
                connection.close()


def _is_connection_interruption(error: BaseException) -> bool:
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate.startswith("08"):
        return True
    try:
        from psycopg import OperationalError
    except ImportError:
        return False
    return isinstance(error, OperationalError)


def _sqlstate(error: BaseException) -> str | None:
    value = getattr(error, "sqlstate", None)
    return value if isinstance(value, str) else None


def _named_rows(cursor: Any) -> list[dict[str, Any]]:
    description = getattr(cursor, "description", None)
    if description is None:
        raise ValueError("missing result metadata")
    names = tuple(column.name for column in description)
    if not names or len(names) != len(set(names)):
        raise ValueError("invalid result metadata")
    rows = cursor.fetchall()
    return [dict(zip(names, row, strict=True)) for row in rows]


def _one_or_none(cursor: Any) -> dict[str, Any] | None:
    rows = _named_rows(cursor)
    if len(rows) > 1:
        raise _adapter_error(
            "TRAINING_DATABASE_INTEGRITY_FAILURE",
            "The PostgreSQL result cardinality is invalid.",
        )
    return rows[0] if rows else None


def _trim(value: Any) -> Any:
    return value.rstrip() if isinstance(value, str) else value


def _aware(value: Any) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("aware database timestamp required")
    return value


def _timestamp(value: Any) -> str:
    return _aware(value).isoformat()


def _uuid(value: Any) -> str:
    result = str(value)
    if str(UUID(result)) != result:
        raise ValueError("canonical UUID required")
    return result


def _bytes(value: Any) -> bytes:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if type(value) is not bytes or not value:
        raise ValueError("non-empty bytes required")
    return value


def _checked_payload(row: Mapping[str, Any], prefix: str) -> bytes:
    payload = _bytes(row[f"{prefix}_payload"])
    expected = _trim(row[f"{prefix}_payload_sha256"])
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected != actual:
        raise ValueError("payload checksum mismatch")
    return payload


def _json_object(payload: bytes, *, canonical: bool = True) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("BOM is forbidden")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict) or (
        canonical and canonical_json_bytes(value) != payload
    ):
        raise ValueError("canonical JSON object required")
    return value


class _UniqueYamlLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False) -> Any:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping
)


def _validate_yaml_source(payload: bytes) -> None:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("BOM is forbidden")
    text = payload.decode("utf-8")
    for token in yaml.scan(text):
        if isinstance(
            token,
            (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken),
        ):
            raise ValueError("YAML aliases and tags are forbidden")
    value = yaml.load(text, Loader=_UniqueYamlLoader)
    if not isinstance(value, dict):
        raise ValueError("YAML mapping required")


class _PostgresTrainingPrerequisiteResolver:
    """Resolve one immutable prerequisite snapshot through the resolver function."""

    def __init__(self, factory: _ConnectionFactory, *, policy_reference: str) -> None:
        if (
            factory.role != _RESOLVER_ROLE
            or _REFERENCE.fullmatch(policy_reference) is None
        ):
            raise _adapter_error(
                "TRAINING_DATABASE_CONFIGURATION_INVALID",
                "A resolver role and policy reference are required.",
            )
        self._factory = factory
        self._policy_reference = policy_reference
        self._materialization_root = Path(tempfile.mkdtemp(prefix="dohalm-c2-"))
        self._closed = False

    def __repr__(self) -> str:
        return "_PostgresTrainingPrerequisiteResolver(<redacted>)"

    def __enter__(self) -> _PostgresTrainingPrerequisiteResolver:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._remove_tree(self._materialization_root)
            self._closed = True

    def release(self, resolved: ResolvedTrainingPrerequisites) -> None:
        """Delete only the materialization owned by one completed request."""

        if type(resolved) is not ResolvedTrainingPrerequisites or self._closed:
            raise _adapter_error(
                "TRAINING_HOST_PREREQUISITE_INVALID",
                "Validated immutable training prerequisites are required.",
            )
        request_root = resolved.config_path.parent
        if (
            resolved.manifest_path.parent != request_root
            or request_root.parent != self._materialization_root
            or not request_root.exists()
        ):
            raise _adapter_error(
                "TRAINING_HOST_PREREQUISITE_INVALID",
                "Validated immutable training prerequisites are required.",
            )
        self._remove_tree(request_root)

    @staticmethod
    def _remove_tree(root: Path) -> None:
        for path in root.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(root, ignore_errors=False)

    def resolve(
        self, request: TrainingPrerequisiteResolutionRequest
    ) -> ResolvedTrainingPrerequisites:
        if type(request) is not TrainingPrerequisiteResolutionRequest or self._closed:
            raise _adapter_error(
                "TRAINING_HOST_PREREQUISITE_INVALID",
                "Validated immutable training prerequisites are required.",
            )
        try:
            with self._factory.transaction(
                isolation="REPEATABLE READ", read_only=True
            ) as connection:
                row = _one_or_none(
                    connection.execute(
                        f"SELECT * FROM {_SCHEMA}.read_c2_training_prerequisite_snapshot("
                        "%s,%s,%s,%s,%s,%s,%s)",
                        (
                            request.dataset_version_authority_id,
                            request.dataset_manifest_authority_id,
                            request.config_authority_id,
                            request.readiness_authority_id,
                            request.intent.expected_dataset_pair_fingerprint,
                            request.intent.expected_config_fingerprint,
                            request.intent.expected_readiness_fingerprint,
                        ),
                    )
                )
            if row is None:
                raise _adapter_error(
                    "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
                    "Authoritative training prerequisites are unavailable.",
                )
            return self._map(request, row)
        except TrainingError:
            raise
        except _PostgresCommitOutcomeUnknown:
            raise _adapter_error(
                "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
                "Authoritative training prerequisites are unavailable.",
            ) from None
        except Exception as error:
            raise _map_prerequisite_error(error) from None

    def _map(
        self, request: TrainingPrerequisiteResolutionRequest, row: Mapping[str, Any]
    ) -> ResolvedTrainingPrerequisites:
        intent = request.intent
        snapshot_at = _aware(row["snapshot_at"])
        ids = {
            "dataset_version": _uuid(row["dataset_version_authority_id"]),
            "dataset_manifest": _uuid(row["dataset_manifest_authority_id"]),
            "dataset_pair": _uuid(row["dataset_pair_authority_id"]),
            "config": _uuid(row["config_authority_id"]),
            "readiness": _uuid(row["readiness_authority_id"]),
        }
        if ids != {
            "dataset_version": request.dataset_version_authority_id,
            "dataset_manifest": request.dataset_manifest_authority_id,
            "dataset_pair": ids["dataset_pair"],
            "config": request.config_authority_id,
            "readiness": request.readiness_authority_id,
        }:
            raise ValueError("authority identity mismatch")
        references = {
            "dataset_version": row["dataset_version_reference"],
            "dataset_manifest": row["dataset_manifest_reference"],
            "config": row["config_reference"],
            "readiness": row["readiness_reference"],
        }
        if references != {
            "dataset_version": intent.dataset_version_reference,
            "dataset_manifest": intent.dataset_manifest_reference,
            "config": intent.training_config_reference,
            "readiness": intent.readiness_evidence_reference,
        }:
            raise ValueError("authority reference mismatch")
        if any(
            row[f"{name}_state"] != "current" for name in (*references, "dataset_pair")
        ):
            raise _adapter_error(
                "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
                "Authoritative training prerequisites are stale.",
            )
        if any(
            _aware(row[f"{name}_state_effective_at"]) > snapshot_at
            for name in (*references, "dataset_pair")
        ):
            raise ValueError("future current projection")
        pair_fingerprint = _trim(row["dataset_pair_fingerprint"])
        config_fingerprint = _trim(row["config_payload_sha256"])
        readiness_fingerprint = _trim(row["readiness_payload_sha256"])
        if (
            pair_fingerprint != intent.expected_dataset_pair_fingerprint
            or config_fingerprint != intent.expected_config_fingerprint
            or readiness_fingerprint != intent.expected_readiness_fingerprint
            or _trim(row["readiness_pair_fingerprint"]) != pair_fingerprint
            or _trim(row["readiness_config_fingerprint"]) != config_fingerprint
            or row["config_kind"] != "full_pretraining"
            or row["config_schema_version"] != 1
            or row["readiness_result"] != "READY"
            or _aware(row["readiness_evaluated_at"]) > snapshot_at
            or _aware(row["readiness_valid_until"]) <= snapshot_at
        ):
            raise ValueError("typed prerequisite binding invalid")
        version_payload = _json_object(_checked_payload(row, "dataset_version"))
        manifest_payload = _json_object(_checked_payload(row, "dataset_manifest"))
        pair_payload = _json_object(_checked_payload(row, "dataset_pair"))
        config_payload = _checked_payload(row, "config")
        readiness_payload = _checked_payload(row, "readiness")
        _validate_yaml_source(config_payload)
        _validate_yaml_source(readiness_payload)
        material_root = Path(
            tempfile.mkdtemp(prefix="request-", dir=self._materialization_root)
        )
        config_path = self._materialize(material_root, "config.yaml", config_payload)
        manifest_path = self._materialize(
            material_root, "manifest.yaml", readiness_payload
        )
        config = FullPretrainingConfig.from_yaml(config_path)
        readiness_report = inspect_full_pretraining_readiness(
            config_path, manifest_path
        )
        upstream = pair_payload.get("upstream_objects")
        artifacts = pair_payload.get("artifact_references")
        evaluated_at = pair_payload.get("evaluated_at")
        expected_split_id = pair_payload.get("expected_split_id")
        if (
            not isinstance(upstream, Sequence)
            or isinstance(upstream, (str, bytes))
            or not isinstance(artifacts, Sequence)
            or isinstance(artifacts, (str, bytes))
            or type(evaluated_at) is not str
            or type(expected_split_id) is not str
        ):
            raise ValueError("dataset pair permission inputs missing")
        permission = evaluate_dataset_training_entry(
            version_payload,
            manifest_payload,
            upstream_objects=upstream,
            evaluated_at=evaluated_at,
            readiness_report=readiness_report,
            expected_split_id=expected_split_id,
            artifact_references=artifacts,
        )
        if (
            permission.allowed is not True
            or permission.pair_fingerprint != pair_fingerprint
            or config.output_dir != intent.output_logical_root
        ):
            raise ValueError("prerequisite domain validation failed")
        return ResolvedTrainingPrerequisites(
            schema_version=1,
            intent_fingerprint=request.intent_fingerprint,
            dataset_version_reference=references["dataset_version"],
            dataset_manifest_reference=references["dataset_manifest"],
            training_config_reference=references["config"],
            readiness_evidence_reference=references["readiness"],
            dataset_version_authority_id=ids["dataset_version"],
            dataset_manifest_authority_id=ids["dataset_manifest"],
            dataset_pair_authority_id=ids["dataset_pair"],
            config_authority_id=ids["config"],
            readiness_authority_id=ids["readiness"],
            config_path=config_path,
            config_snapshot=config.to_dict(),
            manifest_path=manifest_path,
            readiness_report=readiness_report,
            dataset_permission=permission,
            dataset_version_id=permission.dataset_version_id,
            dataset_manifest_id=permission.dataset_manifest_id,
            dataset_pair_fingerprint=pair_fingerprint,
            config_fingerprint=config_fingerprint,
            readiness_fingerprint=readiness_fingerprint,
            source_commit=_trim(row["readiness_source_commit"]),
            run_id=intent.run_id,
            output_logical_root=intent.output_logical_root,
            provenance=TrustedPrerequisiteProvenance(
                dataset_source_identity=row["dataset_pair_reference"],
                config_source_identity=references["config"],
                readiness_source_identity=references["readiness"],
                resolution_policy_reference=self._policy_reference,
                evaluated_at=_timestamp(snapshot_at),
                current=True,
            ),
        )

    @staticmethod
    def _materialize(root: Path, name: str, payload: bytes) -> Path:
        path = root / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o400)
            if path.is_symlink() or path.resolve().parent != root.resolve():
                raise ValueError("materialization containment failure")
            return path.resolve()
        except Exception:
            if path.exists():
                path.unlink()
            raise


class _PostgresTrainingDecisionResolver:
    def __init__(self, factory: _ConnectionFactory, *, policy_reference: str) -> None:
        if (
            factory.role != _RESOLVER_ROLE
            or _REFERENCE.fullmatch(policy_reference) is None
        ):
            raise _adapter_error(
                "TRAINING_DATABASE_CONFIGURATION_INVALID",
                "A resolver role and policy reference are required.",
            )
        self._factory = factory
        self._policy_reference = policy_reference

    def __repr__(self) -> str:
        return "_PostgresTrainingDecisionResolver(<redacted>)"

    def resolve(
        self, request: TrainingDecisionResolutionRequest
    ) -> TrustedDecisionResolution:
        if type(request) is not TrainingDecisionResolutionRequest:
            raise _adapter_error(
                "TRAINING_EXECUTION_DECISION_INVALID",
                "A valid training execution decision is required.",
            )
        try:
            with self._factory.transaction(
                isolation="REPEATABLE READ", read_only=True
            ) as connection:
                row = _one_or_none(
                    connection.execute(
                        f"SELECT * FROM {_SCHEMA}.read_c2_training_decision_snapshot(%s,%s,%s)",
                        (
                            request.decision_authority_id,
                            request.request_fingerprint,
                            self._policy_reference,
                        ),
                    )
                )
            if row is None:
                raise _adapter_error(
                    "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
                    "A training execution decision is unavailable.",
                )
            return self._map(request, row)
        except TrainingError:
            raise
        except Exception as error:
            raise _map_decision_error(error) from None

    def _map(
        self, request: TrainingDecisionResolutionRequest, row: Mapping[str, Any]
    ) -> TrustedDecisionResolution:
        snapshot_at = _aware(row["snapshot_at"])
        decision_id = _uuid(row["decision_authority_id"])
        issuer_id = _uuid(row["issuer_authority_id"])
        approver_id = _uuid(row["approver_authority_id"])
        _checked_payload(row, "decision")
        _checked_payload(row, "issuer")
        _checked_payload(row, "approver")
        if (
            decision_id != request.decision_authority_id
            or row["decision_reference"] != f"decision:{decision_id}"
            or _trim(row["request_fingerprint"]) != request.request_fingerprint
            or row["decision_policy_reference"] != self._policy_reference
            or row["decision_state"] != "current"
            or row["issuer_state"] != "current"
            or row["approver_state"] != "current"
            or any(
                _aware(row[f"{name}_state_effective_at"]) > snapshot_at
                for name in ("decision", "issuer", "approver")
            )
            or _aware(row["decision_valid_until"]) <= snapshot_at
            or _aware(row["issuer_active_from"]) > snapshot_at
            or (
                row["issuer_active_until"] is not None
                and _aware(row["issuer_active_until"]) <= snapshot_at
            )
            or _aware(row["approver_active_from"]) > snapshot_at
            or (
                row["approver_active_until"] is not None
                and _aware(row["approver_active_until"]) <= snapshot_at
            )
            or row["issuer_adapter_kind"] != "same_process_training_execution_issuer"
            or row["evidence_reference"] != f"decision:{decision_id}"
        ):
            raise ValueError("decision binding or currentness invalid")
        try:
            decision_value = TrainingExecutionIssuerDecisionValue(row["decision_value"])
        except ValueError:
            raise ValueError("unknown decision state") from None
        decision = ResolvedTrainingExecutionDecision(
            decision=decision_value,
            authorization_id=row["authorization_id"],
            issuer_id=row["issuer_id"],
            approver_reference=row["approver_reference"],
            evidence_reference=row["evidence_reference"],
            request_fingerprint=_trim(row["request_fingerprint"]),
            issued_at=_timestamp(row["issued_at"]),
        )
        return TrustedDecisionResolution(
            decision=decision,
            provenance=TrustedDecisionProvenance(
                source_identity=row["decision_reference"],
                policy_reference=self._policy_reference,
                decision_authority_id=decision_id,
                issuer_authority_id=issuer_id,
                approver_authority_id=approver_id,
                bound_authorization_id=decision.authorization_id,
                bound_issuer_id=decision.issuer_id,
                bound_approver_reference=decision.approver_reference,
                bound_evidence_reference=decision.evidence_reference,
                issuer_current=True,
                approver_current=True,
                current=True,
            ),
        )


class _PostgresTrainingExecutionJournal:
    def __init__(self, factory: _ConnectionFactory) -> None:
        if factory.role != _JOURNAL_ROLE:
            raise _adapter_error(
                "TRAINING_DATABASE_CONFIGURATION_INVALID",
                "A journal role is required.",
            )
        self._factory = factory

    def __repr__(self) -> str:
        return "_PostgresTrainingExecutionJournal(<redacted>)"

    def claim(
        self, request: TrainingOrchestrationClaimRequest
    ) -> TrainingOrchestrationClaimResult:
        if type(request) is not TrainingOrchestrationClaimRequest:
            raise _journal_invalid()
        try:
            with self._factory.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                row = _one_or_none(
                    connection.execute(
                        f"SELECT * FROM {_SCHEMA}.claim_c2_training_execution_journal("
                        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            request.identity.run_id,
                            request.identity.request_fingerprint,
                            request.intent_fingerprint,
                            request.orchestration_correlation_id,
                            request.dataset_version_id,
                            request.dataset_manifest_id,
                            request.dataset_pair_fingerprint,
                            request.config_fingerprint,
                            request.readiness_fingerprint,
                            request.source_commit,
                            request.prerequisite_policy_reference,
                            request.process_boundary_id,
                        ),
                    )
                )
            if row is None:
                raise _journal_integrity()
            status = TrainingOrchestrationClaimStatus(row.pop("claim_status"))
            return TrainingOrchestrationClaimResult(
                status=status, record=_journal_record(row, prefix="journal_")
            )
        except TrainingError:
            raise
        except _PostgresCommitOutcomeUnknown:
            raise _adapter_error(
                "TRAINING_HOST_JOURNAL_OUTCOME_UNKNOWN",
                "The journal outcome requires manual reconciliation.",
            ) from None
        except (KeyError, TypeError, ValueError):
            raise _journal_integrity() from None
        except Exception as error:
            raise _map_journal_error(error) from None

    def read(self, run_id: str) -> TrainingOrchestrationRecord | None:
        if type(run_id) is not str or _REFERENCE.fullmatch(run_id) is None:
            raise _journal_invalid()
        try:
            with self._factory.transaction(
                isolation="READ COMMITTED", read_only=True
            ) as connection:
                row = _one_or_none(
                    connection.execute(
                        f"SELECT * FROM {_SCHEMA}.read_c2_training_execution_journal(%s)",
                        (run_id,),
                    )
                )
            return None if row is None else _journal_record(row)
        except TrainingError:
            raise
        except (KeyError, TypeError, ValueError):
            raise _journal_integrity() from None
        except Exception as error:
            raise _map_journal_error(error) from None

    def transition(
        self, transition: TrainingOrchestrationTransition
    ) -> TrainingOrchestrationRecord:
        if type(transition) is not TrainingOrchestrationTransition:
            raise _journal_invalid()
        try:
            with self._factory.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                row = _one_or_none(
                    connection.execute(
                        f"SELECT * FROM {_SCHEMA}.transition_c2_training_execution_journal("
                        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            transition.identity.run_id,
                            transition.identity.request_fingerprint,
                            transition.expected_phase.value,
                            transition.expected_version,
                            transition.next_phase.value,
                            transition.process_boundary_id,
                            transition.reason_code,
                            transition.authorization_id,
                            transition.issuer_id,
                            transition.approver_reference,
                            transition.evidence_reference,
                            transition.authorization_fingerprint,
                            transition.decision_evidence_fingerprint,
                            transition.decision_policy_reference,
                        ),
                    )
                )
            if row is None:
                raise _journal_integrity()
            return _journal_record(row)
        except TrainingError:
            raise
        except _PostgresCommitOutcomeUnknown:
            raise _adapter_error(
                "TRAINING_HOST_JOURNAL_OUTCOME_UNKNOWN",
                "The journal outcome requires manual reconciliation.",
            ) from None
        except (KeyError, TypeError, ValueError):
            raise _journal_integrity() from None
        except Exception as error:
            raise _map_journal_error(error) from None


def _journal_record(
    row: Mapping[str, Any], *, prefix: str = ""
) -> TrainingOrchestrationRecord:
    column_map = (
        _CLAIM_JOURNAL_COLUMN_MAP
        if prefix
        else {name: name for name in _EXPECTED_JOURNAL_COLUMNS}
    )
    if frozenset(row) != frozenset(column_map.values()):
        raise ValueError("journal result metadata mismatch")
    normalized = {
        name: _trim(row[source_name]) for name, source_name in column_map.items()
    }
    if (
        normalized["host_schema_version"] != 1
        or normalized["host_lifecycle_version"] != 1
    ):
        raise ValueError("journal schema version invalid")
    claim = TrainingOrchestrationClaimRequest(
        identity=TrainingOrchestrationIdentity(
            run_id=normalized["run_id"],
            request_fingerprint=normalized["request_fingerprint"],
        ),
        intent_fingerprint=normalized["intent_fingerprint"],
        orchestration_correlation_id=normalized["orchestration_correlation_id"],
        dataset_version_id=normalized["dataset_version_id"],
        dataset_manifest_id=normalized["dataset_manifest_id"],
        dataset_pair_fingerprint=normalized["dataset_pair_fingerprint"],
        config_fingerprint=normalized["config_fingerprint"],
        readiness_fingerprint=normalized["readiness_fingerprint"],
        source_commit=normalized["source_commit"],
        prerequisite_policy_reference=normalized[
            "prerequisite_resolution_policy_reference"
        ],
        process_boundary_id=normalized["process_boundary_id"],
    )
    return TrainingOrchestrationRecord(
        claim=claim,
        phase=TrainingOrchestrationPhase(normalized["phase"]),
        journal_version=normalized["journal_version"],
        reservation_group_id=_uuid(normalized["reservation_group_id"]),
        authorization_id=normalized["authorization_id"],
        issuer_id=normalized["issuer_id"],
        approver_reference=normalized["approver_reference"],
        evidence_reference=normalized["evidence_reference"],
        decision_policy_reference=normalized["decision_policy_reference"],
        authorization_fingerprint=normalized["authorization_fingerprint"],
        decision_evidence_fingerprint=normalized["decision_evidence_fingerprint"],
        backend_entered=normalized["backend_entered"],
        reconciliation_required=normalized["reconciliation_required"],
        reason_code=normalized["reconciliation_reason_code"],
    )


def _map_prerequisite_error(error: BaseException) -> TrainingError:
    state = _sqlstate(error)
    if state == "21000":
        return _adapter_error(
            "TRAINING_HOST_PREREQUISITE_INVALID",
            "The prerequisite authority relationship is conflicting.",
        )
    if state == "42501":
        return _adapter_error(
            "TRAINING_DATABASE_PERMISSION_DENIED",
            "The PostgreSQL operation is not authorized.",
        )
    if state in {"57014", "55P03"} or _is_connection_interruption(error):
        return _adapter_error(
            "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
            "Authoritative training prerequisites are unavailable.",
        )
    return _adapter_error(
        "TRAINING_HOST_PREREQUISITE_INVALID",
        "Validated immutable training prerequisites are required.",
    )


def _map_decision_error(error: BaseException) -> TrainingError:
    state = _sqlstate(error)
    if state == "42501":
        return _adapter_error(
            "TRAINING_DATABASE_PERMISSION_DENIED",
            "The PostgreSQL operation is not authorized.",
        )
    if state in {"57014", "55P03"} or _is_connection_interruption(error):
        return _adapter_error(
            "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
            "A training execution decision is unavailable.",
        )
    return _adapter_error(
        "TRAINING_EXECUTION_DECISION_INVALID",
        "A valid training execution decision is required.",
    )


def _journal_invalid() -> TrainingError:
    return _adapter_error(
        "TRAINING_HOST_JOURNAL_CONFLICT",
        "The training orchestration journal state conflicts with this operation.",
    )


def _journal_integrity() -> TrainingError:
    return _adapter_error(
        "TRAINING_HOST_JOURNAL_INTEGRITY_FAILURE",
        "The training orchestration journal failed an integrity contract.",
    )


def _map_journal_error(error: BaseException) -> TrainingError:
    state = _sqlstate(error)
    if state is not None and state.startswith("XX"):
        return _journal_integrity()
    if state in {"23505", "23514", "40001", "P0002"}:
        return _journal_invalid()
    if state == "42501":
        return _adapter_error(
            "TRAINING_DATABASE_PERMISSION_DENIED",
            "The PostgreSQL operation is not authorized.",
        )
    if state in {"57014", "55P03"}:
        return _adapter_error(
            "TRAINING_DATABASE_TIMEOUT",
            "The PostgreSQL operation timed out.",
        )
    if _is_connection_interruption(error):
        return _adapter_error(
            "TRAINING_HOST_JOURNAL_UNAVAILABLE",
            "The training orchestration journal is unavailable.",
        )
    return _journal_invalid()


__all__: list[str] = []
