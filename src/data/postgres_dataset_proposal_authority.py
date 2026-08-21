"""Durable PostgreSQL implementation of the Dataset proposal authority port."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checksums import canonical_json_bytes
from .dataset_governance import (
    DatasetVersionIdentity,
    DatasetVersionProposal,
    propose_dataset_version,
)
from .dataset_proposal_authority import (
    DatasetProposalAuthorityError,
    DatasetProposalAuthorityRecord,
    DatasetProposalAuthorityResult,
    DatasetProposalOutcome,
    dataset_version_proposal_fingerprint,
)

_ROLE = "dohalm_dataset_proposal_authority"
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_APPLICATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")


@dataclass(frozen=True, slots=True, repr=False)
class PostgresDatasetProposalAuthoritySettings:
    """Explicit role credential and transport policy for the durable adapter."""

    environment: str
    host: str
    port: int
    database: str
    user: str
    password: str
    application_name: str
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 15_000
    transaction_timeout_ms: int = 30_000
    sslmode: str = "verify-full"
    sslrootcert: Path | None = None

    def __post_init__(self) -> None:
        isolated = self.environment == "isolated_test"
        production = self.environment == "production"
        valid_transport = (
            isolated
            and self.host == "127.0.0.1"
            and self.sslmode == "disable"
            and self.sslrootcert is None
        ) or (
            production
            and self.sslmode == "verify-full"
            and isinstance(self.sslrootcert, Path)
            and self.sslrootcert.is_absolute()
        )
        if (
            not valid_transport
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
            or _REFERENCE.fullmatch(self.database) is None
            or self.user != _ROLE
            or type(self.password) is not str
            or not self.password
            or _APPLICATION_NAME.fullmatch(self.application_name) is None
            or type(self.connect_timeout_seconds) is not int
            or not 1 <= self.connect_timeout_seconds <= 60
            or type(self.statement_timeout_ms) is not int
            or not 1 <= self.statement_timeout_ms <= 300_000
            or type(self.transaction_timeout_ms) is not int
            or not self.statement_timeout_ms <= self.transaction_timeout_ms <= 600_000
        ):
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_CONFIGURATION_INVALID",
                "configuration",
            )

    def __repr__(self) -> str:
        return "PostgresDatasetProposalAuthoritySettings(<redacted>)"


class PostgresDatasetProposalAuthority:
    """Open a short-lived restricted transaction for each atomic adjudication."""

    def __init__(self, settings: PostgresDatasetProposalAuthoritySettings) -> None:
        if type(settings) is not PostgresDatasetProposalAuthoritySettings:
            raise TypeError("PostgreSQL Dataset proposal settings are required")
        self._settings = settings

    def __repr__(self) -> str:
        return "PostgresDatasetProposalAuthority(<redacted>)"

    def read_authoritative_proposal(
        self,
        identity: DatasetVersionIdentity,
    ) -> DatasetProposalAuthorityRecord:
        """Read one validated proposal through the restricted authority function."""

        requested = _read_identity(identity)
        connection = None
        try:
            import psycopg

            connection = psycopg.connect(**self._connection_kwargs())
            with connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY"
                )
                self._configure_transaction(connection)
                self._require_runtime_role(connection)
                cursor = connection.execute(
                    "SELECT * FROM "
                    "dohalm_dataset_governance_v1.read_dataset_version_proposal"
                    "(%s, %s, %s)",
                    requested,
                )
                row = _optional_named_row(cursor)
                if row is None:
                    raise DatasetProposalAuthorityError(
                        "DATASET_PROPOSAL_AUTHORITY_NOT_FOUND",
                        "read",
                        identity=identity,
                    )
                return _authority_record(row)
        except DatasetProposalAuthorityError:
            raise
        except Exception as error:
            sqlstate = getattr(error, "sqlstate", None)
            if isinstance(sqlstate, str) and sqlstate.startswith("XX"):
                raise _corrupt() from None
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_UNAVAILABLE",
                "persistence",
            ) from None
        finally:
            if connection is not None:
                connection.close()

    def compare_and_create(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
    ) -> DatasetProposalAuthorityResult:
        payload, fingerprint = _incoming(proposal, proposal_fingerprint)
        connection = None
        try:
            import psycopg

            connection = psycopg.connect(**self._connection_kwargs())
            with connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE"
                )
                self._configure_transaction(connection)
                self._require_runtime_role(connection)
                connection.execute(
                    "SELECT "
                    "dohalm_dataset_governance_v1.lock_dataset_version_proposal_identity"
                    "(%s, %s, %s)",
                    (
                        proposal.identity.object_id,
                        proposal.identity.dataset_id,
                        proposal.identity.dataset_version,
                    ),
                ).fetchone()
                cursor = connection.execute(
                    "SELECT * FROM "
                    "dohalm_dataset_governance_v1.compare_and_create_dataset_version_proposal"
                    "(%s, %s, %s, %s, %s)",
                    (
                        proposal.identity.object_id,
                        proposal.identity.dataset_id,
                        proposal.identity.dataset_version,
                        fingerprint,
                        payload,
                    ),
                )
                inserted_rows = _named_rows(cursor)
                if len(inserted_rows) > 1:
                    raise _corrupt()
                if inserted_rows:
                    row = inserted_rows[0]
                    outcome = _text(row["outcome"])
                else:
                    read_cursor = connection.execute(
                        "SELECT * FROM "
                        "dohalm_dataset_governance_v1.read_dataset_version_proposal"
                        "(%s, %s, %s)",
                        (
                            proposal.identity.object_id,
                            proposal.identity.dataset_id,
                            proposal.identity.dataset_version,
                        ),
                    )
                    row = {
                        "outcome": "REPLAYED",
                        **_one_named_row(read_cursor),
                    }
                    outcome = (
                        "REPLAYED"
                        if _text(row["proposal_fingerprint"]) == fingerprint
                        and _payload_bytes(row["canonical_payload"]) == payload
                        else "CONFLICT"
                    )
                    row["outcome"] = outcome
                stored = _stored_proposal(row)
                if outcome == "CONFLICT":
                    raise DatasetProposalAuthorityError(
                        "DATASET_VERSION_PROPOSAL_IDENTITY_CONFLICT",
                        "compare_and_create",
                        identity=proposal.identity,
                        existing_fingerprint=_text(row["proposal_fingerprint"]),
                        incoming_fingerprint=fingerprint,
                    )
                try:
                    resolved_outcome = DatasetProposalOutcome(outcome)
                except ValueError:
                    raise _corrupt() from None
                return DatasetProposalAuthorityResult(
                    outcome=resolved_outcome,
                    proposal=stored,
                    identity=stored.identity,
                    proposal_fingerprint=_text(row["proposal_fingerprint"]),
                    authority_reference=_text(row["authority_reference"]),
                    authority_version=_integer(row["authority_version"]),
                )
        except DatasetProposalAuthorityError:
            raise
        except Exception as error:
            sqlstate = getattr(error, "sqlstate", None)
            if isinstance(sqlstate, str) and sqlstate.startswith("XX"):
                raise _corrupt() from None
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_UNAVAILABLE",
                "persistence",
            ) from None
        finally:
            if connection is not None:
                connection.close()

    def _connection_kwargs(self) -> dict[str, Any]:
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
        return kwargs

    def _configure_transaction(self, connection: Any) -> None:
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true), "
            "set_config('idle_in_transaction_session_timeout', %s, true)",
            (
                str(self._settings.statement_timeout_ms),
                str(self._settings.transaction_timeout_ms),
            ),
        )

    @staticmethod
    def _require_runtime_role(connection: Any) -> None:
        if connection.execute("SELECT current_user").fetchone() != (_ROLE,):
            raise DatasetProposalAuthorityError(
                "DATASET_PROPOSAL_AUTHORITY_PERMISSION_DENIED",
                "transaction",
            )


def _incoming(
    proposal: DatasetVersionProposal, proposal_fingerprint: str
) -> tuple[bytes, str]:
    if type(proposal) is not DatasetVersionProposal or proposal.status != "draft":
        raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "persistence")
    expected = dataset_version_proposal_fingerprint(proposal)
    if proposal_fingerprint != expected:
        raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "fingerprint")
    return canonical_json_bytes(proposal.payload), expected


def _read_identity(identity: object) -> tuple[str, str, str]:
    if type(identity) is not DatasetVersionIdentity:
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_IDENTITY_INVALID",
            "read",
        )
    values = (identity.object_id, identity.dataset_id, identity.dataset_version)
    if any(type(value) is not str or not 1 <= len(value) <= 256 for value in values):
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_IDENTITY_INVALID",
            "read",
        )
    return values


def _named_rows(cursor: Any) -> list[dict[str, Any]]:
    description = getattr(cursor, "description", None)
    if description is None:
        raise _corrupt()
    names = tuple(column.name for column in description)
    rows = cursor.fetchall()
    if not names or len(names) != len(set(names)):
        raise _corrupt()
    return [dict(zip(names, row, strict=True)) for row in rows]


def _one_named_row(cursor: Any) -> dict[str, Any]:
    rows = _named_rows(cursor)
    if len(rows) != 1:
        raise _corrupt()
    return rows[0]


def _optional_named_row(cursor: Any) -> dict[str, Any] | None:
    rows = _named_rows(cursor)
    if len(rows) > 1:
        raise _corrupt()
    return rows[0] if rows else None


def _authority_record(row: dict[str, Any]) -> DatasetProposalAuthorityRecord:
    if set(row) != {
        "object_id",
        "dataset_id",
        "dataset_version",
        "proposal_fingerprint",
        "canonical_payload",
        "authority_reference",
        "authority_version",
        "created_at",
    }:
        raise _corrupt()
    stored = _stored_proposal({"outcome": "REPLAYED", **row})
    return DatasetProposalAuthorityRecord(
        proposal=stored,
        identity=stored.identity,
        proposal_fingerprint=_text(row["proposal_fingerprint"]),
        authority_reference=_text(row["authority_reference"]),
        authority_version=_integer(row["authority_version"]),
    )


def _stored_proposal(row: dict[str, Any]) -> DatasetVersionProposal:
    required = {
        "outcome",
        "object_id",
        "dataset_id",
        "dataset_version",
        "proposal_fingerprint",
        "canonical_payload",
        "authority_reference",
        "authority_version",
        "created_at",
    }
    if set(row) != required:
        raise _corrupt()
    payload = _payload_bytes(row["canonical_payload"])

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise _corrupt()
            value[key] = item
        return value

    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(decoded, dict) or canonical_json_bytes(decoded) != payload:
            raise _corrupt()
        proposal = propose_dataset_version(decoded)
    except DatasetProposalAuthorityError:
        raise
    except Exception:
        raise _corrupt() from None
    fingerprint = _text(row["proposal_fingerprint"])
    if (
        proposal.identity.object_id != row["object_id"]
        or proposal.identity.dataset_id != row["dataset_id"]
        or proposal.identity.dataset_version != row["dataset_version"]
        or dataset_version_proposal_fingerprint(proposal) != fingerprint
        or _REFERENCE.fullmatch(_text(row["authority_reference"])) is None
        or _integer(row["authority_version"]) != 1
    ):
        raise _corrupt()
    return proposal


def _payload_bytes(value: Any) -> bytes:
    payload = value
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    if type(payload) is not bytes or payload.startswith(b"\xef\xbb\xbf"):
        raise _corrupt()
    return payload


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise _corrupt()
    return value.rstrip()


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise _corrupt()
    return value


def _corrupt() -> DatasetProposalAuthorityError:
    return DatasetProposalAuthorityError(
        "DATASET_PROPOSAL_AUTHORITY_CORRUPT",
        "persistence",
    )


__all__ = [
    "PostgresDatasetProposalAuthority",
    "PostgresDatasetProposalAuthoritySettings",
]
