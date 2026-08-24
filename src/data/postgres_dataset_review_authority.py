"""Durable PostgreSQL implementation of the Dataset review authority port."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataset_governance import DatasetVersionIdentity
from .dataset_review_authority import (
    DatasetReviewAuthorityError,
    DatasetReviewAuthorityRecord,
    DatasetReviewOutcome,
    DatasetReviewStartRequest,
    DatasetReviewStartResult,
    build_dataset_review_authority_record,
    validate_dataset_review_authority_record,
    validate_dataset_review_start_request,
    validate_dataset_review_start_result,
)

_ROLE = "dohalm_dataset_review_authority"
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_APPLICATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
_AUTHORITY_VERSION = 1


@dataclass(frozen=True, slots=True, repr=False)
class PostgresDatasetReviewAuthoritySettings:
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
            raise DatasetReviewAuthorityError(
                "DATASET_REVIEW_AUTHORITY_CONFIGURATION_INVALID",
                "configuration",
            )

    def __repr__(self) -> str:
        return "PostgresDatasetReviewAuthoritySettings(<redacted>)"


class PostgresDatasetReviewAuthority:
    """Use one short-lived restricted transaction per review operation."""

    def __init__(self, settings: PostgresDatasetReviewAuthoritySettings) -> None:
        if type(settings) is not PostgresDatasetReviewAuthoritySettings:
            raise TypeError("PostgreSQL Dataset review settings are required")
        self._settings = settings

    def __repr__(self) -> str:
        return "PostgresDatasetReviewAuthority(<redacted>)"

    def start_review(
        self,
        request: DatasetReviewStartRequest,
    ) -> DatasetReviewStartResult:
        requested = validate_dataset_review_start_request(request)
        authority_reference = _authority_reference(
            requested.identity,
            requested.proposal_fingerprint,
        )
        expected_record = build_dataset_review_authority_record(
            requested,
            authority_reference=authority_reference,
            authority_version=_AUTHORITY_VERSION,
        )
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
                cursor = connection.execute(
                    "SELECT * FROM "
                    "dohalm_dataset_governance_v1.start_dataset_version_review"
                    "(%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        requested.identity.object_id,
                        requested.identity.dataset_id,
                        requested.identity.dataset_version,
                        requested.proposal_fingerprint,
                        requested.reviewer_reference,
                        requested.review_started_at,
                        requested.request_reference,
                        expected_record.record_fingerprint,
                    ),
                )
                row = _one_named_row(cursor)
                outcome = _outcome(row.pop("outcome"))
                if outcome is DatasetReviewOutcome.CONFLICT:
                    _require_conflict_row(
                        row,
                        request=requested,
                        authority_reference=authority_reference,
                    )
                    result = DatasetReviewStartResult(
                        outcome=outcome,
                        identity=requested.identity,
                        proposal_fingerprint=requested.proposal_fingerprint,
                        authority_reference=_text(row["authority_reference"]),
                        authority_version=_integer(row["authority_version"]),
                    )
                else:
                    record = _record(row)
                    result = DatasetReviewStartResult(
                        outcome=outcome,
                        identity=record.identity,
                        proposal_fingerprint=record.proposal_fingerprint,
                        authority_reference=record.authority_reference,
                        authority_version=record.authority_version,
                        record=record,
                    )
                return validate_dataset_review_start_result(result, requested)
        except DatasetReviewAuthorityError:
            raise
        except Exception as error:  # noqa: BLE001 - sanitize the psycopg boundary
            raise _map_error(error, identity=requested.identity) from None
        finally:
            if connection is not None:
                connection.close()

    def read_authoritative_review(
        self,
        identity: DatasetVersionIdentity,
        *,
        proposal_fingerprint: str,
    ) -> DatasetReviewAuthorityRecord:
        requested = _read_binding(identity, proposal_fingerprint)
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
                    "dohalm_dataset_governance_v1.read_dataset_version_review"
                    "(%s, %s, %s, %s)",
                    (*requested, proposal_fingerprint),
                )
                row = _optional_named_row(cursor)
                if row is None:
                    raise DatasetReviewAuthorityError(
                        "DATASET_REVIEW_AUTHORITY_NOT_FOUND",
                        "read",
                        identity=identity,
                    )
                return validate_dataset_review_authority_record(
                    _record(row),
                    expected_identity=identity,
                    expected_proposal_fingerprint=proposal_fingerprint,
                )
        except DatasetReviewAuthorityError:
            raise
        except Exception as error:  # noqa: BLE001 - sanitize the psycopg boundary
            raise _map_error(error, identity=identity) from None
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
            raise DatasetReviewAuthorityError(
                "DATASET_REVIEW_AUTHORITY_PERMISSION_DENIED",
                "transaction",
            )


def _authority_reference(
    identity: DatasetVersionIdentity,
    proposal_fingerprint: str,
) -> str:
    semantic = (
        f"{identity.object_id}\x1f{identity.dataset_id}\x1f"
        f"{identity.dataset_version}\x1f{proposal_fingerprint}"
    ).encode()
    return "dataset-review:" + hashlib.sha256(semantic).hexdigest()


def _read_binding(
    identity: object, proposal_fingerprint: object
) -> tuple[str, str, str]:
    try:
        request = DatasetReviewStartRequest(
            identity=identity,  # type: ignore[arg-type]
            proposal_fingerprint=proposal_fingerprint,  # type: ignore[arg-type]
            reviewer_reference="validation:read",
            review_started_at=datetime.min.replace(tzinfo=timezone.utc),
        )
    except Exception as error:
        if isinstance(error, DatasetReviewAuthorityError):
            raise DatasetReviewAuthorityError(error.code, "read") from None
        raise
    return (
        request.identity.object_id,
        request.identity.dataset_id,
        request.identity.dataset_version,
    )


def _record(row: dict[str, Any]) -> DatasetReviewAuthorityRecord:
    required = {
        "object_id",
        "dataset_id",
        "dataset_version",
        "proposal_fingerprint",
        "lifecycle_state",
        "reviewer_reference",
        "review_started_at",
        "request_reference",
        "authority_reference",
        "authority_version",
        "record_fingerprint",
        "created_at",
    }
    if set(row) != required:
        raise _corrupt()
    started_at = row["review_started_at"]
    created_at = row["created_at"]
    if (
        not isinstance(started_at, datetime)
        or started_at.tzinfo is None
        or started_at.utcoffset() is None
        or not isinstance(created_at, datetime)
        or created_at.tzinfo is None
        or created_at.utcoffset() is None
    ):
        raise _corrupt()
    request_reference = row["request_reference"]
    if request_reference is not None and not isinstance(request_reference, str):
        raise _corrupt()
    try:
        return DatasetReviewAuthorityRecord(
            identity=DatasetVersionIdentity(
                _text(row["object_id"]),
                _text(row["dataset_id"]),
                _text(row["dataset_version"]),
            ),
            proposal_fingerprint=_text(row["proposal_fingerprint"]),
            reviewer_reference=_text(row["reviewer_reference"]),
            review_started_at=started_at,
            request_reference=request_reference,
            authority_reference=_text(row["authority_reference"]),
            authority_version=_integer(row["authority_version"]),
            record_fingerprint=_text(row["record_fingerprint"]),
            lifecycle_state=_text(row["lifecycle_state"]),
        )
    except DatasetReviewAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - normalize malformed driver values
        raise _corrupt() from None


def _require_conflict_row(
    row: dict[str, Any],
    *,
    request: DatasetReviewStartRequest,
    authority_reference: str,
) -> None:
    if set(row) != {
        "object_id",
        "dataset_id",
        "dataset_version",
        "proposal_fingerprint",
        "lifecycle_state",
        "reviewer_reference",
        "review_started_at",
        "request_reference",
        "authority_reference",
        "authority_version",
        "record_fingerprint",
        "created_at",
    }:
        raise _corrupt()
    if any(
        row[name] is not None
        for name in (
            "lifecycle_state",
            "reviewer_reference",
            "review_started_at",
            "request_reference",
            "record_fingerprint",
            "created_at",
        )
    ):
        raise _corrupt()
    if (
        _text(row["object_id"]) != request.identity.object_id
        or _text(row["dataset_id"]) != request.identity.dataset_id
        or _text(row["dataset_version"]) != request.identity.dataset_version
        or _text(row["proposal_fingerprint"]) != request.proposal_fingerprint
        or _text(row["authority_reference"]) != authority_reference
        or _integer(row["authority_version"]) != _AUTHORITY_VERSION
    ):
        raise _corrupt()


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


def _outcome(value: Any) -> DatasetReviewOutcome:
    try:
        return DatasetReviewOutcome(_text(value))
    except ValueError:
        raise _corrupt() from None


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise _corrupt()
    return value.rstrip()


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise _corrupt()
    return value


def _map_error(
    error: BaseException,
    *,
    identity: DatasetVersionIdentity,
) -> DatasetReviewAuthorityError:
    sqlstate = getattr(error, "sqlstate", None)
    code = {
        "P5001": "DATASET_REVIEW_PROPOSAL_NOT_FOUND",
        "P5002": "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH",
        "P5003": "DATASET_REVIEW_PROPOSAL_AUTHORITY_CORRUPT",
        "P5004": "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH",
        "22023": "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
    }.get(sqlstate)
    if code is not None:
        return DatasetReviewAuthorityError(code, "persistence", identity=identity)
    if isinstance(sqlstate, str) and sqlstate.startswith("XX"):
        return _corrupt()
    return DatasetReviewAuthorityError(
        "DATASET_REVIEW_AUTHORITY_UNAVAILABLE",
        "persistence",
        identity=identity,
    )


def _corrupt() -> DatasetReviewAuthorityError:
    return DatasetReviewAuthorityError(
        "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
        "persistence",
    )


__all__ = [
    "PostgresDatasetReviewAuthority",
    "PostgresDatasetReviewAuthoritySettings",
]
