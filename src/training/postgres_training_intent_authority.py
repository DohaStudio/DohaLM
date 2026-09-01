"""PostgreSQL adapter for the ADR-032 Training intent foundation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from src.data.checksums import checksum_value, sha256_bytes

from .errors import TrainingError
from .execution_issuer import TrainingExecutionIssuerDecisionValue
from .postgres_training_adapters import _ConnectionFactory
from .production_intent_authority import (
    TrainingIntentContinuation,
    TrainingIntentDecisionBinding,
    TrainingIntentMode,
    TrainingIntentRecord,
    TrainingIntentSubmission,
    TrainingIntentSubmitOutcome,
    TrainingIntentSubmitterAuthorityRecord,
    TrainingIntentValidationSnapshot,
    project_training_execution_request,
    training_intent_fingerprint,
)
from .current_evidence_gate import TrainingCurrentEvidencePort


_PRODUCER_ROLE = "dohalm_training_authority_producer"
_WRITER_ROLE = "dohalm_training_intent_writer"
_RESOLVER_ROLE = "dohalm_training_resolver"


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _trim(value: Any) -> Any:
    return value.rstrip() if isinstance(value, str) else value


def _rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _one(cursor: Any, *, missing: bool = False) -> Mapping[str, Any] | None:
    rows = _rows(cursor)
    if not rows and missing:
        return None
    if len(rows) != 1:
        raise _error(
            "TRAINING_INTENT_AUTHORITY_CORRUPT",
            "The Training intent authority returned an invalid result.",
        )
    return rows[0]


def _map_error(error: BaseException) -> TrainingError:
    state = getattr(error, "sqlstate", None)
    if state in {"23505", "40001"}:
        return _error(
            "TRAINING_INTENT_CONFLICT",
            "The Training intent authority rejected a conflicting operation.",
        )
    if state in {"23503", "P0002"}:
        return _error(
            "TRAINING_INTENT_AUTHORITY_UNAVAILABLE",
            "A required Training intent authority is unavailable.",
        )
    if state in {"22023", "23514"}:
        return _error(
            "TRAINING_INTENT_INVALID",
            "The Training intent authority rejected invalid immutable input.",
        )
    if state in {"25006", "42501"}:
        return _error(
            "TRAINING_INTENT_AUTHORITY_PERMISSION_DENIED",
            "The Training intent operation is not permitted.",
        )
    return _error(
        "TRAINING_INTENT_AUTHORITY_UNAVAILABLE",
        "The Training intent authority is unavailable "
        f"(SQLSTATE {state if isinstance(state, str) else 'unknown'}).",
    )


def _map_submitter(row: Mapping[str, Any]) -> TrainingIntentSubmitterAuthorityRecord:
    return TrainingIntentSubmitterAuthorityRecord(
        authority_id=str(row["authority_id"]),
        domain_key=_trim(row["domain_key"]),
        state=row["authority_state"],
        state_effective_at=row["state_effective_at"],
        created_at=row["created_at"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        projection_version=row["projection_version"],
    )


def _map_intent(row: Mapping[str, Any]) -> TrainingIntentRecord:
    mode = TrainingIntentMode(row["execution_mode"])
    continuation = None
    if mode is TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION:
        continuation = TrainingIntentContinuation(
            predecessor_run_id=row["predecessor_run_id"],
            checkpoint_reference=row["checkpoint_reference"],
            source_step=row["source_step"],
            target_cumulative_steps=row["target_cumulative_steps"],
        )
    submission = TrainingIntentSubmission(
        schema_version=row["schema_version"],
        action=row["action"],
        client_request_id=row["client_request_id"],
        requested_run_id=row["requested_run_id"],
        execution_mode=mode,
        dataset_version_authority_id=str(row["dataset_version_authority_id"]),
        dataset_manifest_authority_id=str(row["dataset_manifest_authority_id"]),
        dataset_pair_authority_id=str(row["dataset_pair_authority_id"]),
        dataset_version_id=row["dataset_version_id"],
        dataset_manifest_id=row["dataset_manifest_id"],
        dataset_pair_fingerprint=_trim(row["dataset_pair_fingerprint"]),
        config_authority_id=str(row["config_authority_id"]),
        config_fingerprint=_trim(row["config_fingerprint"]),
        readiness_authority_id=str(row["readiness_authority_id"]),
        readiness_fingerprint=_trim(row["readiness_fingerprint"]),
        source_commit=row["source_commit"],
        output_logical_root=row["output_logical_root"],
        continuation=continuation,
    )
    record = TrainingIntentRecord(
        intent_id=str(row["intent_id"]),
        submitter_authority_id=str(row["submitter_authority_id"]),
        submission=submission,
        intent_fingerprint=_trim(row["intent_fingerprint"]),
        created_at=row["created_at"],
    )
    if project_training_execution_request(record).request_fingerprint != _trim(
        row["request_fingerprint"]
    ):
        raise _error(
            "TRAINING_INTENT_AUTHORITY_CORRUPT",
            "The durable Training intent request projection is corrupt.",
        )
    return record


def _map_binding(row: Mapping[str, Any]) -> TrainingIntentDecisionBinding:
    return TrainingIntentDecisionBinding(
        intent_id=str(row["intent_id"]),
        decision_authority_id=str(row["decision_authority_id"]),
        decision=TrainingExecutionIssuerDecisionValue(row["decision"]),
        authorization_id=row["authorization_id"],
        issuer_authority_id=str(row["issuer_authority_id"]),
        issuer_id=row["issuer_id"],
        approver_authority_id=str(row["approver_authority_id"]),
        approver_reference=row["approver_reference"],
        evidence_reference=row["evidence_reference"],
        request_fingerprint=_trim(row["request_fingerprint"]),
        bound_at=row["bound_at"],
    )


class PostgresTrainingIntentAuthority:
    """Role-separated restricted-function adapter; no execution surface."""

    def __init__(
        self,
        *,
        producer: _ConnectionFactory,
        writer: _ConnectionFactory,
        resolver: _ConnectionFactory,
        current_evidence: TrainingCurrentEvidencePort,
    ) -> None:
        if (
            producer.role != _PRODUCER_ROLE
            or writer.role != _WRITER_ROLE
            or resolver.role != _RESOLVER_ROLE
        ):
            raise _error(
                "TRAINING_INTENT_AUTHORITY_CONFIGURATION_INVALID",
                "Exact producer, intent-writer, and resolver roles are required.",
            )
        self._producer = producer
        self._writer = writer
        self._resolver = resolver
        self._current_evidence = current_evidence

    def __repr__(self) -> str:
        return "PostgresTrainingIntentAuthority(<redacted>)"

    def provision_submitter(
        self,
        *,
        authority_id: str,
        domain_key: str,
        payload: bytes,
        source_commit: str,
        valid_from: datetime,
        valid_until: datetime | None,
        event_id: str,
        correlation_reference: str,
        evidence_reference: str,
    ) -> TrainingIntentSubmitterAuthorityRecord:
        try:
            UUID(authority_id)
            UUID(event_id)
            with self._producer.transaction(
                isolation="read committed", read_only=False
            ) as connection:
                connection.execute(
                    "SELECT * FROM dohalm_training_v1.provision_training_intent_submitter("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        authority_id,
                        domain_key,
                        payload,
                        sha256_bytes(payload),
                        source_commit,
                        valid_from,
                        valid_until,
                        event_id,
                        correlation_reference,
                        evidence_reference,
                    ),
                ).fetchone()
            record = self._read_submitter(authority_id)
            if record is None:
                raise _error(
                    "TRAINING_INTENT_AUTHORITY_CORRUPT",
                    "The committed Training intent submitter cannot be read back.",
                )
            return record
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def append_submitter_event(
        self,
        *,
        event_id: str,
        authority_id: str,
        expected_stream_version: int,
        event_kind: str,
        superseded_by_authority_id: str | None,
        effective_at: datetime,
        correlation_reference: str,
        evidence_reference: str,
    ) -> None:
        try:
            with self._producer.transaction(
                isolation="read committed", read_only=False
            ) as connection:
                connection.execute(
                    "SELECT * FROM dohalm_training_v1.write_training_intent_submitter_event("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        event_id,
                        authority_id,
                        expected_stream_version,
                        event_kind,
                        superseded_by_authority_id,
                        effective_at,
                        correlation_reference,
                        evidence_reference,
                    ),
                ).fetchone()
        except Exception as exc:
            raise _map_error(exc) from None

    def resolve_current(
        self, authority_id: str
    ) -> TrainingIntentSubmitterAuthorityRecord:
        record = self._read_submitter(authority_id)
        if record is None:
            raise _error(
                "TRAINING_INTENT_SUBMITTER_NOT_CURRENT",
                "The selected Training intent submitter is not current.",
            )
        if not record.current:
            raise _error(
                "TRAINING_INTENT_SUBMITTER_NOT_CURRENT",
                "The selected Training intent submitter is not current.",
            )
        return record

    def _read_submitter(
        self, authority_id: str
    ) -> TrainingIntentSubmitterAuthorityRecord | None:
        try:
            with self._resolver.transaction(
                isolation="repeatable read", read_only=True
            ) as connection:
                row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.read_training_intent_submitter(%s)",
                        (authority_id,),
                    ),
                    missing=True,
                )
            return None if row is None else _map_submitter(row)
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def submit(
        self,
        submitter: TrainingIntentSubmitterAuthorityRecord,
        submission: TrainingIntentSubmission,
    ) -> tuple[TrainingIntentSubmitOutcome, TrainingIntentRecord]:
        if not submitter.current:
            raise _error(
                "TRAINING_INTENT_SUBMITTER_NOT_CURRENT",
                "The selected Training intent submitter is not current.",
            )
        continuation = submission.continuation
        intent_fingerprint = training_intent_fingerprint(
            submitter.authority_id, submission
        )
        projection_values = {
            "schema_version": submission.schema_version,
            "action": submission.action,
            "dataset_version_id": submission.dataset_version_id,
            "dataset_manifest_id": submission.dataset_manifest_id,
            "dataset_pair_fingerprint": submission.dataset_pair_fingerprint,
            "config_fingerprint": submission.config_fingerprint,
            "readiness_fingerprint": submission.readiness_fingerprint,
            "run_id": submission.requested_run_id,
            "output_logical_root": submission.output_logical_root,
            "source_commit": submission.source_commit,
            "execution_mode": submission.execution_mode.value,
        }
        request_fingerprint = checksum_value(projection_values)
        try:
            with self._writer.transaction(
                isolation="read committed", read_only=False
            ) as connection:
                row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.submit_training_intent("
                        + ",".join(["%s"] * 22)
                        + ")",
                        (
                            submitter.authority_id,
                            submission.client_request_id,
                            submission.requested_run_id,
                            submission.execution_mode.value,
                            submission.dataset_version_authority_id,
                            submission.dataset_manifest_authority_id,
                            submission.dataset_pair_authority_id,
                            submission.dataset_version_id,
                            submission.dataset_manifest_id,
                            submission.dataset_pair_fingerprint,
                            submission.config_authority_id,
                            submission.config_fingerprint,
                            submission.readiness_authority_id,
                            submission.readiness_fingerprint,
                            submission.source_commit,
                            submission.output_logical_root,
                            None
                            if continuation is None
                            else continuation.predecessor_run_id,
                            None
                            if continuation is None
                            else continuation.checkpoint_reference,
                            None if continuation is None else continuation.source_step,
                            None
                            if continuation is None
                            else continuation.target_cumulative_steps,
                            intent_fingerprint,
                            request_fingerprint,
                        ),
                    )
                )
            assert row is not None
            record = self.get(str(row["submitted_intent_id"]))
            if record is None:
                raise _error(
                    "TRAINING_INTENT_AUTHORITY_CORRUPT",
                    "The committed Training intent cannot be read back.",
                )
            return TrainingIntentSubmitOutcome(row["submit_status"]), record
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def get(self, intent_id: str) -> TrainingIntentRecord | None:
        return self._read_intent(
            "SELECT * FROM dohalm_training_v1.read_training_intent(%s)",
            (intent_id,),
        )

    def get_by_idempotency(
        self, submitter_authority_id: str, client_request_id: str
    ) -> TrainingIntentRecord | None:
        return self._read_intent(
            "SELECT * FROM dohalm_training_v1.read_training_intent_by_idempotency(%s,%s)",
            (submitter_authority_id, client_request_id),
        )

    def _read_intent(
        self, statement: str, parameters: tuple[object, ...]
    ) -> TrainingIntentRecord | None:
        try:
            with self._resolver.transaction(
                isolation="repeatable read", read_only=True
            ) as connection:
                row = _one(connection.execute(statement, parameters), missing=True)
            return None if row is None else _map_intent(row)
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def bind_decision(
        self, intent_id: str, decision_authority_id: str
    ) -> TrainingIntentDecisionBinding:
        try:
            with self._writer.transaction(
                isolation="read committed", read_only=False
            ) as connection:
                connection.execute(
                    "SELECT * FROM dohalm_training_v1.bind_training_intent_decision(%s,%s)",
                    (intent_id, decision_authority_id),
                ).fetchone()
            binding = self.get_decision_binding(intent_id)
            if binding is None:
                raise _error(
                    "TRAINING_INTENT_AUTHORITY_CORRUPT",
                    "The committed decision binding cannot be read back.",
                )
            return binding
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def get_decision_binding(
        self, intent_id: str
    ) -> TrainingIntentDecisionBinding | None:
        try:
            with self._resolver.transaction(
                isolation="repeatable read", read_only=True
            ) as connection:
                row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.read_training_intent_decision_binding(%s)",
                        (intent_id,),
                    ),
                    missing=True,
                )
            return None if row is None else _map_binding(row)
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def read_validation_snapshot(
        self, intent_id: str
    ) -> TrainingIntentValidationSnapshot:
        try:
            with self._resolver.transaction(
                isolation="repeatable read", read_only=True
            ) as connection:
                intent_row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.read_training_intent(%s)",
                        (intent_id,),
                    )
                )
                binding_row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.read_training_intent_decision_binding(%s)",
                        (intent_id,),
                    ),
                    missing=True,
                )
                state_row = _one(
                    connection.execute(
                        "SELECT * FROM dohalm_training_v1.read_training_intent_validation_state(%s)",
                        (intent_id,),
                    )
                )
            assert intent_row is not None and state_row is not None
            intent = _map_intent(intent_row)
            current_evidence_current = True
            try:
                self._current_evidence.verify_currentness(
                    intent.submission.readiness_authority_id,
                    intent.submission.readiness_fingerprint,
                )
            except TrainingError:
                current_evidence_current = False
            return TrainingIntentValidationSnapshot(
                intent=intent,
                binding=None if binding_row is None else _map_binding(binding_row),
                submitter_current=state_row["submitter_current"],
                dataset_version_current=state_row["dataset_version_current"],
                dataset_manifest_current=state_row["dataset_manifest_current"],
                dataset_pair_current=state_row["dataset_pair_current"],
                config_current=state_row["config_current"],
                readiness_current=state_row["readiness_current"],
                decision_current=state_row["decision_current"],
                issuer_current=state_row["issuer_current"],
                approver_current=state_row["approver_current"],
                current_evidence_current=current_evidence_current,
            )
        except TrainingError:
            raise
        except Exception as exc:
            raise _map_error(exc) from None

    def verify_current_evidence(self, intent: TrainingIntentRecord) -> None:
        self._current_evidence.verify_currentness(
            intent.submission.readiness_authority_id,
            intent.submission.readiness_fingerprint,
        )


__all__ = ["PostgresTrainingIntentAuthority"]
