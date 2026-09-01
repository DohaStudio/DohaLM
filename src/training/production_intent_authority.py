"""Production Training intent authority foundation.

This module owns immutable intake and validate-only contracts.  It never
composes a production Host, claims the execution journal, or invokes a backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from src.data.checksums import checksum_value

from .errors import TrainingError
from .execution_approval import TrainingExecutionRequest
from .current_evidence_gate import TrainingCurrentEvidencePort
from .execution_issuer import TrainingExecutionIssuerDecisionValue


_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_LOGICAL_ROOT = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _valid_reference(value: object) -> bool:
    return type(value) is str and _REFERENCE.fullmatch(value) is not None


def _valid_fingerprint(value: object) -> bool:
    return type(value) is str and _FINGERPRINT.fullmatch(value) is not None


def _valid_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _valid_logical_root(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    if "\\" in value or ":" in value or any(ord(char) < 32 for char in value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and value == path.as_posix()
        and _LOGICAL_ROOT.fullmatch(value) is not None
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _error(
            "TRAINING_INTENT_RECORD_INVALID",
            "A timezone-aware authority timestamp is required.",
        )
    return value.astimezone(timezone.utc)


class TrainingIntentMode(str, Enum):
    FRESH = "fresh"
    R3_ONE_EPOCH_CONTINUATION = "r3_one_epoch_continuation"


class TrainingIntentLifecycle(str, Enum):
    SUBMITTED = "SUBMITTED"
    DECISION_BOUND_APPROVED = "DECISION_BOUND_APPROVED"
    DECISION_BOUND_DENIED = "DECISION_BOUND_DENIED"


class TrainingIntentSubmitOutcome(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentContinuation:
    predecessor_run_id: str
    checkpoint_reference: str
    source_step: int
    target_cumulative_steps: int

    def __post_init__(self) -> None:
        if (
            not _valid_reference(self.predecessor_run_id)
            or not _valid_reference(self.checkpoint_reference)
            or type(self.source_step) is not int
            or type(self.target_cumulative_steps) is not int
            or self.source_step < 1
            or self.target_cumulative_steps <= self.source_step
        ):
            raise _error(
                "TRAINING_INTENT_CONTINUATION_INVALID",
                "The exact approved continuation binding is required.",
            )

    def __repr__(self) -> str:
        return "TrainingIntentContinuation(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentSubmission:
    client_request_id: str
    requested_run_id: str
    execution_mode: TrainingIntentMode
    dataset_version_authority_id: str
    dataset_manifest_authority_id: str
    dataset_pair_authority_id: str
    dataset_version_id: str
    dataset_manifest_id: str
    dataset_pair_fingerprint: str
    config_authority_id: str
    config_fingerprint: str
    readiness_authority_id: str
    readiness_fingerprint: str
    source_commit: str
    output_logical_root: str
    continuation: TrainingIntentContinuation | None = None
    schema_version: int = 1
    action: str = "full_pretraining"

    def __post_init__(self) -> None:
        references = (
            self.client_request_id,
            self.requested_run_id,
            self.dataset_version_id,
            self.dataset_manifest_id,
        )
        authority_ids = (
            self.dataset_version_authority_id,
            self.dataset_manifest_authority_id,
            self.dataset_pair_authority_id,
            self.config_authority_id,
            self.readiness_authority_id,
        )
        fingerprints = (
            self.dataset_pair_fingerprint,
            self.config_fingerprint,
            self.readiness_fingerprint,
        )
        if (
            self.schema_version != 1
            or self.action != "full_pretraining"
            or type(self.execution_mode) is not TrainingIntentMode
            or not all(_valid_reference(value) for value in references)
            or not all(_valid_uuid(value) for value in authority_ids)
            or not all(_valid_fingerprint(value) for value in fingerprints)
            or _SOURCE_COMMIT.fullmatch(self.source_commit) is None
            or not _valid_logical_root(self.output_logical_root)
            or (
                self.execution_mode is TrainingIntentMode.FRESH
                and self.continuation is not None
            )
            or (
                self.execution_mode is TrainingIntentMode.R3_ONE_EPOCH_CONTINUATION
                and type(self.continuation) is not TrainingIntentContinuation
            )
        ):
            raise _error(
                "TRAINING_INTENT_SUBMISSION_INVALID",
                "A valid immutable production Training intent is required.",
            )

    def __repr__(self) -> str:
        return "TrainingIntentSubmission(<redacted>)"


def training_intent_fingerprint(
    submitter_authority_id: str, submission: TrainingIntentSubmission
) -> str:
    """Return the ADR-032 canonical immutable intent fingerprint."""
    if (
        not _valid_uuid(submitter_authority_id)
        or type(submission) is not TrainingIntentSubmission
    ):
        raise _error(
            "TRAINING_INTENT_SUBMISSION_INVALID",
            "A resolved current submitter and immutable intent are required.",
        )
    continuation = submission.continuation
    payload = {
        "action": submission.action,
        "config_authority_id": submission.config_authority_id,
        "config_fingerprint": submission.config_fingerprint,
        "continuation": (
            None
            if continuation is None
            else {
                "checkpoint_reference": continuation.checkpoint_reference,
                "predecessor_run_id": continuation.predecessor_run_id,
                "source_step": continuation.source_step,
                "target_cumulative_steps": continuation.target_cumulative_steps,
            }
        ),
        "dataset_manifest_authority_id": submission.dataset_manifest_authority_id,
        "dataset_manifest_id": submission.dataset_manifest_id,
        "dataset_pair_authority_id": submission.dataset_pair_authority_id,
        "dataset_pair_fingerprint": submission.dataset_pair_fingerprint,
        "dataset_version_authority_id": submission.dataset_version_authority_id,
        "dataset_version_id": submission.dataset_version_id,
        "execution_mode": submission.execution_mode.value,
        "output_logical_root": submission.output_logical_root,
        "readiness_authority_id": submission.readiness_authority_id,
        "readiness_fingerprint": submission.readiness_fingerprint,
        "requested_run_id": submission.requested_run_id,
        "schema_version": submission.schema_version,
        "source_commit": submission.source_commit,
        "submitter_authority_id": submitter_authority_id,
    }
    return checksum_value(payload)


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentSubmitterAuthorityRecord:
    authority_id: str
    domain_key: str
    state: str
    state_effective_at: datetime
    created_at: datetime
    valid_from: datetime
    valid_until: datetime | None
    projection_version: int

    def __post_init__(self) -> None:
        if (
            not _valid_uuid(self.authority_id)
            or not _valid_reference(self.domain_key)
            or self.state
            not in {"scheduled", "current", "expired", "revoked", "superseded"}
            or type(self.projection_version) is not int
            or self.projection_version < 1
        ):
            raise _error(
                "TRAINING_INTENT_SUBMITTER_INVALID",
                "A valid dedicated submitter authority record is required.",
            )
        object.__setattr__(self, "state_effective_at", _utc(self.state_effective_at))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "valid_from", _utc(self.valid_from))
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _utc(self.valid_until))

    @property
    def current(self) -> bool:
        return self.state == "current"

    def __repr__(self) -> str:
        return "TrainingIntentSubmitterAuthorityRecord(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentRecord:
    intent_id: str
    submitter_authority_id: str
    submission: TrainingIntentSubmission
    intent_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not _valid_uuid(self.intent_id)
            or not _valid_uuid(self.submitter_authority_id)
            or type(self.submission) is not TrainingIntentSubmission
            or not _valid_fingerprint(self.intent_fingerprint)
            or self.intent_id == self.submission.requested_run_id
            or self.intent_fingerprint
            != training_intent_fingerprint(self.submitter_authority_id, self.submission)
        ):
            raise _error(
                "TRAINING_INTENT_RECORD_INVALID",
                "The durable Training intent record is invalid.",
            )
        object.__setattr__(self, "created_at", _utc(self.created_at))

    def __repr__(self) -> str:
        return "TrainingIntentRecord(<redacted>)"

    def lifecycle(
        self, binding: TrainingIntentDecisionBinding | None
    ) -> TrainingIntentLifecycle:
        if binding is None:
            return TrainingIntentLifecycle.SUBMITTED
        if binding.intent_id != self.intent_id:
            raise _error(
                "TRAINING_INTENT_DECISION_BINDING_INVALID",
                "The decision binding does not belong to this Training intent.",
            )
        if binding.decision is TrainingExecutionIssuerDecisionValue.APPROVED:
            return TrainingIntentLifecycle.DECISION_BOUND_APPROVED
        return TrainingIntentLifecycle.DECISION_BOUND_DENIED


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentDecisionBinding:
    intent_id: str
    decision_authority_id: str
    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_authority_id: str
    issuer_id: str
    approver_authority_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    bound_at: datetime

    def __post_init__(self) -> None:
        if (
            not all(
                _valid_uuid(value)
                for value in (
                    self.intent_id,
                    self.decision_authority_id,
                    self.issuer_authority_id,
                    self.approver_authority_id,
                )
            )
            or type(self.decision) is not TrainingExecutionIssuerDecisionValue
            or not all(
                _valid_reference(value)
                for value in (
                    self.authorization_id,
                    self.issuer_id,
                    self.approver_reference,
                    self.evidence_reference,
                )
            )
            or not _valid_fingerprint(self.request_fingerprint)
            or self.issuer_authority_id == self.approver_authority_id
        ):
            raise _error(
                "TRAINING_INTENT_DECISION_BINDING_INVALID",
                "A valid immutable decision binding is required.",
            )
        object.__setattr__(self, "bound_at", _utc(self.bound_at))

    def __repr__(self) -> str:
        return "TrainingIntentDecisionBinding(<redacted>)"


def project_training_execution_request(
    intent: TrainingIntentRecord,
) -> TrainingExecutionRequest:
    """Project the existing 11-field TrainingExecutionRequest v1 contract."""
    if type(intent) is not TrainingIntentRecord:
        raise _error(
            "TRAINING_INTENT_RECORD_INVALID",
            "A durable Training intent record is required.",
        )
    submission = intent.submission
    values = {
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
    return TrainingExecutionRequest(
        **values, request_fingerprint=checksum_value(values)
    )


class TrainingIntentSubmitterAuthorityPort(Protocol):
    def resolve_current(
        self, authority_id: str
    ) -> TrainingIntentSubmitterAuthorityRecord: ...


class TrainingIntentAuthorityPort(Protocol):
    def submit(
        self,
        submitter: TrainingIntentSubmitterAuthorityRecord,
        submission: TrainingIntentSubmission,
    ) -> tuple[TrainingIntentSubmitOutcome, TrainingIntentRecord]: ...

    def get(self, intent_id: str) -> TrainingIntentRecord | None: ...

    def get_by_idempotency(
        self, submitter_authority_id: str, client_request_id: str
    ) -> TrainingIntentRecord | None: ...

    def bind_decision(
        self, intent_id: str, decision_authority_id: str
    ) -> TrainingIntentDecisionBinding: ...

    def get_decision_binding(
        self, intent_id: str
    ) -> TrainingIntentDecisionBinding | None: ...


@dataclass(frozen=True, slots=True, repr=False)
class TrainingIntentValidationSnapshot:
    intent: TrainingIntentRecord
    binding: TrainingIntentDecisionBinding | None
    submitter_current: bool
    dataset_version_current: bool
    dataset_manifest_current: bool
    dataset_pair_current: bool
    config_current: bool
    readiness_current: bool
    decision_current: bool
    issuer_current: bool
    approver_current: bool
    current_evidence_current: bool

    def __repr__(self) -> str:
        return "TrainingIntentValidationSnapshot(<redacted>)"


class TrainingIntentValidationPort(Protocol):
    def read_validation_snapshot(
        self, intent_id: str
    ) -> TrainingIntentValidationSnapshot: ...

    def verify_current_evidence(self, intent: TrainingIntentRecord) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedTrainingIntent:
    intent: TrainingIntentRecord
    binding: TrainingIntentDecisionBinding
    execution_request: TrainingExecutionRequest

    def __repr__(self) -> str:
        return "ValidatedTrainingIntent(<redacted>)"


class ProductionTrainingIntentSubmissionService:
    """Construction-bound local selector; callers cannot choose a submitter."""

    def __init__(
        self,
        selected_submitter_authority_id: str,
        submitters: TrainingIntentSubmitterAuthorityPort,
        intents: TrainingIntentAuthorityPort,
        current_evidence: TrainingCurrentEvidencePort,
    ) -> None:
        if not _valid_uuid(selected_submitter_authority_id):
            raise _error(
                "TRAINING_INTENT_SUBMITTER_INVALID",
                "A trusted local submitter selector is required.",
            )
        self._selected_submitter_authority_id = selected_submitter_authority_id
        self._submitters = submitters
        self._intents = intents
        self._current_evidence = current_evidence

    def submit(
        self, submission: TrainingIntentSubmission
    ) -> tuple[TrainingIntentSubmitOutcome, TrainingIntentRecord]:
        self._current_evidence.verify_currentness(
            submission.readiness_authority_id,
            submission.readiness_fingerprint,
        )
        submitter = self._submitters.resolve_current(
            self._selected_submitter_authority_id
        )
        if not submitter.current:
            raise _error(
                "TRAINING_INTENT_SUBMITTER_NOT_CURRENT",
                "The configured Training intent submitter is not current.",
            )
        return self._intents.submit(submitter, submission)


def validate_intent_for_execution(
    intent_id: str,
    expected_source_commit: str,
    authority: TrainingIntentValidationPort,
) -> ValidatedTrainingIntent:
    """Validate durable authority only and stop before C3/Host/backend."""
    if (
        not _valid_uuid(intent_id)
        or _SOURCE_COMMIT.fullmatch(expected_source_commit) is None
    ):
        raise _error(
            "TRAINING_INTENT_VALIDATION_INVALID",
            "A valid intent identity and source commit are required.",
        )
    snapshot = authority.read_validation_snapshot(intent_id)
    if type(snapshot) is not TrainingIntentValidationSnapshot:
        raise _error(
            "TRAINING_INTENT_VALIDATION_INVALID",
            "An authoritative validation snapshot is required.",
        )
    if snapshot.binding is None:
        raise _error(
            "TRAINING_INTENT_DECISION_MISSING",
            "The Training intent has no durable execution decision binding.",
        )
    if snapshot.binding.decision is not TrainingExecutionIssuerDecisionValue.APPROVED:
        raise _error(
            "TRAINING_INTENT_DECISION_DENIED",
            "The Training intent decision does not permit execution.",
        )
    if (
        len(
            {
                snapshot.intent.submitter_authority_id,
                snapshot.binding.issuer_authority_id,
                snapshot.binding.approver_authority_id,
            }
        )
        != 3
    ):
        raise _error(
            "TRAINING_INTENT_AUTHORITY_ROLE_COLLISION",
            "Submitter, issuer, and approver authority identities must be distinct.",
        )
    current = (
        snapshot.submitter_current,
        snapshot.dataset_version_current,
        snapshot.dataset_manifest_current,
        snapshot.dataset_pair_current,
        snapshot.config_current,
        snapshot.readiness_current,
        snapshot.decision_current,
        snapshot.issuer_current,
        snapshot.approver_current,
        snapshot.current_evidence_current,
    )
    if not all(value is True for value in current):
        raise _error(
            "TRAINING_INTENT_AUTHORITY_STALE",
            "A bound Training intent authority is no longer current.",
        )
    request = project_training_execution_request(snapshot.intent)
    if (
        snapshot.intent.submission.source_commit != expected_source_commit
        or request.request_fingerprint != snapshot.binding.request_fingerprint
    ):
        raise _error(
            "TRAINING_INTENT_BINDING_MISMATCH",
            "The Training intent does not match its current validation target.",
        )
    return ValidatedTrainingIntent(snapshot.intent, snapshot.binding, request)


__all__ = [
    "ProductionTrainingIntentSubmissionService",
    "TrainingIntentAuthorityPort",
    "TrainingIntentContinuation",
    "TrainingIntentDecisionBinding",
    "TrainingIntentLifecycle",
    "TrainingIntentMode",
    "TrainingIntentRecord",
    "TrainingIntentSubmission",
    "TrainingIntentSubmitOutcome",
    "TrainingIntentSubmitterAuthorityPort",
    "TrainingIntentSubmitterAuthorityRecord",
    "TrainingIntentValidationPort",
    "TrainingIntentValidationSnapshot",
    "ValidatedTrainingIntent",
    "project_training_execution_request",
    "training_intent_fingerprint",
    "validate_intent_for_execution",
]
