"""Restricted-function PostgreSQL adapter for production authority provisioning."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Protocol

from .errors import TrainingError
from .production_authority_provisioning import (
    AuthorityProvisioningIdentity,
    ConfigAuthorityProvisionCommand,
    DatasetAuthorityRegistrationCommand,
    DatasetAuthorityRegistrationResult,
    DatasetPairReplacementCommand,
    DatasetPairReplacementResult,
    DecisionAuthorityProvisionCommand,
    PrincipalProvisionCommand,
    ProductionAuthorityProvisioningPort,
    ReadinessAuthorityProvisionCommand,
)

_PRODUCER_ROLE = "dohalm_training_authority_producer"


class _ConnectionFactory(Protocol):
    role: str

    @contextmanager
    def transaction(self, *, isolation: str, read_only: bool) -> Iterator[Any]: ...


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _trim(value: Any) -> Any:
    return value.rstrip() if isinstance(value, str) else value


def _row(cursor: Any) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None or cursor.description is None:
        raise _error(
            "PRODUCTION_AUTHORITY_PROVISIONING_CORRUPT",
            "The committed production authority result is unavailable.",
        )
    return {
        column.name: value
        for column, value in zip(cursor.description, row, strict=True)
    }


def _identity(
    row: Mapping[str, Any], prefix: str = ""
) -> AuthorityProvisioningIdentity:
    return AuthorityProvisioningIdentity(
        authority_id=str(row[f"{prefix}authority_id"]),
        domain_key=_trim(row[f"{prefix}domain_key"]),
        payload_fingerprint=_trim(row[f"{prefix}payload_sha256"]),
        state=row[f"{prefix}authority_state"],
        projection_version=row[f"{prefix}projection_version"],
    )


def _map_error(error: BaseException) -> TrainingError:
    if isinstance(error, TrainingError):
        return error
    state = getattr(error, "sqlstate", None)
    if state in {"23505", "40001"}:
        return _error(
            "PRODUCTION_AUTHORITY_PROVISIONING_CONFLICT",
            "An immutable production authority conflicts with existing state.",
        )
    if state in {"22023", "23503", "23514"}:
        return _error(
            "PRODUCTION_AUTHORITY_PROVISIONING_INVALID",
            "The production authority input or binding is invalid.",
        )
    if state in {"25006", "42501"}:
        return _error(
            "PRODUCTION_AUTHORITY_PROVISIONING_PERMISSION_DENIED",
            "The production authority operation is not permitted.",
        )
    return _error(
        "PRODUCTION_AUTHORITY_PROVISIONING_UNAVAILABLE",
        "The production authority store is unavailable "
        f"(SQLSTATE {state if isinstance(state, str) else 'unknown'}).",
    )


class PostgresProductionAuthorityProvisioning(ProductionAuthorityProvisioningPort):
    """One restricted producer transaction per authority family operation."""

    def __init__(self, producer: _ConnectionFactory) -> None:
        if producer.role != _PRODUCER_ROLE:
            raise _error(
                "PRODUCTION_AUTHORITY_PROVISIONING_CONFIGURATION_INVALID",
                "The exact authority-producer role is required.",
            )
        self._producer = producer

    def __repr__(self) -> str:
        return "PostgresProductionAuthorityProvisioning(<redacted>)"

    def provision_issuer(
        self, command: PrincipalProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        return self._principal("issuer", command)

    def provision_approver(
        self, command: PrincipalProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        return self._principal("approver", command)

    def _principal(
        self, family: str, command: PrincipalProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        if type(command) is not PrincipalProvisionCommand or family not in {
            "issuer",
            "approver",
        }:
            raise _map_error(ValueError("invalid principal command"))
        function = (
            "provision_training_issuer"
            if family == "issuer"
            else "provision_training_approver"
        )
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    f"SELECT * FROM dohalm_training_v1.{function}("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        command.authority_id,
                        command.domain_key,
                        command.payload,
                        command.payload_fingerprint,
                        command.source_commit,
                        command.valid_from,
                        command.valid_until,
                        command.principal_reference,
                        command.event_id,
                        command.correlation_reference,
                        command.evidence_reference,
                    ),
                )
                return _identity(_row(cursor))
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None

    def provision_config(
        self, command: ConfigAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        if type(command) is not ConfigAuthorityProvisionCommand:
            raise _map_error(ValueError("invalid config command"))
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    "SELECT * FROM dohalm_training_v1.provision_training_config("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        command.authority_id,
                        command.domain_key,
                        command.canonical_payload,
                        command.payload_fingerprint,
                        command.source_commit,
                        command.valid_from,
                        command.valid_until,
                        command.event_id,
                        command.correlation_reference,
                        command.evidence_reference,
                    ),
                )
                return _identity(_row(cursor))
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None

    def provision_readiness(
        self, command: ReadinessAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        if type(command) is not ReadinessAuthorityProvisionCommand:
            raise _map_error(ValueError("invalid readiness command"))
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    "SELECT * FROM dohalm_training_v1.provision_training_readiness("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        command.authority_id,
                        command.domain_key,
                        command.canonical_payload,
                        command.payload_fingerprint,
                        command.source_commit,
                        command.dataset_pair_fingerprint,
                        command.config_fingerprint,
                        command.evaluated_at,
                        command.valid_from,
                        command.valid_until,
                        command.event_id,
                        command.correlation_reference,
                        command.evidence_reference,
                    ),
                )
                return _identity(_row(cursor))
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None

    def register_dataset_publication(
        self, command: DatasetAuthorityRegistrationCommand
    ) -> DatasetAuthorityRegistrationResult:
        if type(command) is not DatasetAuthorityRegistrationCommand:
            raise _map_error(ValueError("invalid Dataset command"))
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    "SELECT * FROM dohalm_training_v1.register_training_dataset_publication("
                    + ",".join(["%s"] * 25)
                    + ")",
                    (
                        command.version_authority_id,
                        command.manifest_authority_id,
                        command.pair_authority_id,
                        command.version_domain_key,
                        command.manifest_domain_key,
                        command.pair_domain_key,
                        command.version_payload,
                        command.manifest_payload,
                        command.pair_payload,
                        command.dataset_version_id,
                        command.dataset_manifest_id,
                        command.pair_fingerprint,
                        command.source_commit,
                        command.publication_scenario,
                        command.eligibility_reference,
                        command.source_lineage_reference,
                        command.valid_from,
                        command.valid_until,
                        command.version_event_id,
                        command.manifest_event_id,
                        command.pair_event_id,
                        command.correlation_reference,
                        True,
                        False,
                        False,
                    ),
                )
                row = _row(cursor)
                return DatasetAuthorityRegistrationResult(
                    version=_identity(row, "version_"),
                    manifest=_identity(row, "manifest_"),
                    pair=_identity(row, "pair_"),
                    dataset_version_id=_trim(row["dataset_version_id"]),
                    dataset_manifest_id=_trim(row["dataset_manifest_id"]),
                    pair_fingerprint=_trim(row["pair_fingerprint"]),
                )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None

    def replace_dataset_pair(
        self, command: DatasetPairReplacementCommand
    ) -> DatasetPairReplacementResult:
        if type(command) is not DatasetPairReplacementCommand:
            raise _map_error(ValueError("invalid Dataset pair replacement command"))
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    "SELECT * FROM dohalm_training_v1.replace_training_dataset_pair("
                    + ",".join(["%s"] * 20)
                    + ")",
                    (
                        command.previous_pair_authority_id,
                        command.expected_previous_projection_version,
                        command.version_authority_id,
                        command.manifest_authority_id,
                        command.pair_authority_id,
                        command.pair_domain_key,
                        command.version_payload,
                        command.manifest_payload,
                        command.pair_payload,
                        command.dataset_version_id,
                        command.dataset_manifest_id,
                        command.pair_fingerprint,
                        command.source_commit,
                        command.publication_scenario,
                        command.valid_until,
                        command.pair_event_id,
                        command.supersede_event_id,
                        command.correlation_reference,
                        command.evidence_reference,
                        command.pair_payload_fingerprint,
                    ),
                )
                row = _row(cursor)
                return DatasetPairReplacementResult(
                    version=_identity(row, "version_"),
                    manifest=_identity(row, "manifest_"),
                    pair=_identity(row, "pair_"),
                    previous_pair_authority_id=str(row["previous_pair_authority_id"]),
                    previous_pair_state=row["previous_pair_state"],
                    previous_pair_projection_version=int(
                        row["previous_pair_projection_version"]
                    ),
                    pair_fingerprint=_trim(row["pair_fingerprint"]),
                    pair_schema_version=int(row["pair_schema_version"]),
                )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None

    def create_decision(
        self, command: DecisionAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity:
        if type(command) is not DecisionAuthorityProvisionCommand:
            raise _map_error(ValueError("invalid decision command"))
        try:
            with self._producer.transaction(
                isolation="READ COMMITTED", read_only=False
            ) as connection:
                cursor = connection.execute(
                    "SELECT * FROM dohalm_training_v1.create_training_execution_decision("
                    + ",".join(["%s"] * 19)
                    + ")",
                    (
                        command.authority_id,
                        command.domain_key,
                        command.canonical_payload,
                        command.payload_fingerprint,
                        command.source_commit,
                        command.decision.value,
                        command.authorization_id,
                        command.issuer_authority_id,
                        command.issuer_id,
                        command.approver_authority_id,
                        command.approver_reference,
                        command.evidence_reference,
                        command.request.request_fingerprint,
                        command.issued_at,
                        command.valid_from,
                        command.valid_until,
                        command.event_id,
                        command.correlation_reference,
                        command.evidence_reference,
                    ),
                )
                return _identity(_row(cursor))
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _map_error(error) from None


__all__ = ["PostgresProductionAuthorityProvisioning"]
