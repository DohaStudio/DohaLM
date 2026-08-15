"""Value and port contracts for the future production training host.

This module does not compose an issuer, issue an approval, or invoke a backend.
Resolver and journal implementations are bound by a future composition root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from .errors import TrainingError
from .execution_issuer import TrainingExecutionIssuerDecisionValue


_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_REASON_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _intent_invalid() -> TrainingError:
    return _error(
        "TRAINING_HOST_INTENT_INVALID",
        "A valid immutable production training intent is required.",
    )


def _decision_invalid() -> TrainingError:
    return _error(
        "TRAINING_EXECUTION_DECISION_INVALID",
        "A valid training execution decision is required.",
    )


def _journal_conflict() -> TrainingError:
    return _error(
        "TRAINING_HOST_JOURNAL_CONFLICT",
        "The training orchestration journal state conflicts with this operation.",
    )


def _is_reference(value: object) -> bool:
    return type(value) is str and _REFERENCE_PATTERN.fullmatch(value) is not None


def _is_fingerprint(value: object) -> bool:
    return type(value) is str and _FINGERPRINT_PATTERN.fullmatch(value) is not None


def _is_logical_root(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    if "\\" in value or ":" in value or any(ord(character) < 32 for character in value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _is_canonical_timestamp(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return (
        timestamp.tzinfo is not None
        and timestamp.utcoffset() is not None
        and timestamp.isoformat() == value
    )


def _is_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ProductionTrainingHostIntent:
    """Caller-owned references and intent; never execution authority."""

    action: str
    execution_mode: str
    dataset_version_reference: str
    dataset_manifest_reference: str
    expected_dataset_pair_fingerprint: str
    training_config_reference: str
    expected_config_fingerprint: str
    readiness_evidence_reference: str
    expected_readiness_fingerprint: str
    run_id: str
    output_logical_root: str
    decision_evidence_reference: str

    def __init__(
        self,
        *,
        action: str,
        execution_mode: str,
        dataset_version_reference: str,
        dataset_manifest_reference: str,
        expected_dataset_pair_fingerprint: str,
        training_config_reference: str,
        expected_config_fingerprint: str,
        readiness_evidence_reference: str,
        expected_readiness_fingerprint: str,
        run_id: str,
        output_logical_root: str,
        decision_evidence_reference: str,
    ) -> None:
        references = (
            dataset_version_reference,
            dataset_manifest_reference,
            training_config_reference,
            readiness_evidence_reference,
            run_id,
            decision_evidence_reference,
        )
        fingerprints = (
            expected_dataset_pair_fingerprint,
            expected_config_fingerprint,
            expected_readiness_fingerprint,
        )
        if (
            type(action) is not str
            or action != "full_pretraining"
            or type(execution_mode) is not str
            or execution_mode != "fresh"
            or not all(_is_reference(value) for value in references)
            or not all(_is_fingerprint(value) for value in fingerprints)
            or not _is_logical_root(output_logical_root)
        ):
            raise _intent_invalid()
        values = (
            action,
            execution_mode,
            dataset_version_reference,
            dataset_manifest_reference,
            expected_dataset_pair_fingerprint,
            training_config_reference,
            expected_config_fingerprint,
            readiness_evidence_reference,
            expected_readiness_fingerprint,
            run_id,
            output_logical_root,
            decision_evidence_reference,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "ProductionTrainingHostIntent(<redacted>)"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ResolvedTrainingExecutionDecision:
    """The exact seven immutable fields returned by a trusted resolver."""

    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    issued_at: str

    def __init__(
        self,
        *,
        decision: TrainingExecutionIssuerDecisionValue,
        authorization_id: str,
        issuer_id: str,
        approver_reference: str,
        evidence_reference: str,
        request_fingerprint: str,
        issued_at: str,
    ) -> None:
        references = (
            authorization_id,
            issuer_id,
            approver_reference,
            evidence_reference,
        )
        if (
            type(decision) is not TrainingExecutionIssuerDecisionValue
            or not all(_is_reference(value) for value in references)
            or not _is_fingerprint(request_fingerprint)
            or not _is_canonical_timestamp(issued_at)
        ):
            raise _decision_invalid()
        values = (
            decision,
            authorization_id,
            issuer_id,
            approver_reference,
            evidence_reference,
            request_fingerprint,
            issued_at,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "ResolvedTrainingExecutionDecision(<redacted>)"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TrustedDecisionProvenance:
    """Resolver-owned authenticity, binding, currentness, and policy evidence."""

    source_identity: str
    policy_reference: str
    decision_authority_id: str
    issuer_authority_id: str
    approver_authority_id: str
    bound_authorization_id: str
    bound_issuer_id: str
    bound_approver_reference: str
    bound_evidence_reference: str
    issuer_current: bool
    approver_current: bool
    current: bool

    def __init__(
        self,
        *,
        source_identity: str,
        policy_reference: str,
        decision_authority_id: str,
        issuer_authority_id: str,
        approver_authority_id: str,
        bound_authorization_id: str,
        bound_issuer_id: str,
        bound_approver_reference: str,
        bound_evidence_reference: str,
        issuer_current: bool,
        approver_current: bool,
        current: bool,
    ) -> None:
        references = (
            source_identity,
            policy_reference,
            bound_authorization_id,
            bound_issuer_id,
            bound_approver_reference,
            bound_evidence_reference,
        )
        if (
            not all(_is_reference(value) for value in references)
            or not all(
                _is_uuid(value)
                for value in (
                    decision_authority_id,
                    issuer_authority_id,
                    approver_authority_id,
                )
            )
            or not all(
                type(value) is bool
                for value in (issuer_current, approver_current, current)
            )
        ):
            raise _decision_invalid()
        values = (
            source_identity,
            policy_reference,
            decision_authority_id,
            issuer_authority_id,
            approver_authority_id,
            bound_authorization_id,
            bound_issuer_id,
            bound_approver_reference,
            bound_evidence_reference,
            issuer_current,
            approver_current,
            current,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "TrustedDecisionProvenance(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrustedDecisionResolution:
    decision: ResolvedTrainingExecutionDecision
    provenance: TrustedDecisionProvenance

    def __post_init__(self) -> None:
        if (
            type(self.decision) is not ResolvedTrainingExecutionDecision
            or type(self.provenance) is not TrustedDecisionProvenance
        ):
            raise _decision_invalid()

    def __repr__(self) -> str:
        return "TrustedDecisionResolution(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingDecisionResolutionRequest:
    """Host-owned binding passed to the trusted decision resolver."""

    intent: ProductionTrainingHostIntent
    decision_authority_id: str
    request_fingerprint: str
    dataset_version_id: str
    dataset_manifest_id: str
    dataset_pair_authority_id: str
    dataset_pair_fingerprint: str
    config_fingerprint: str
    readiness_fingerprint: str
    source_commit: str
    prerequisite_policy_reference: str

    def __post_init__(self) -> None:
        if (
            type(self.intent) is not ProductionTrainingHostIntent
            or not _is_uuid(self.decision_authority_id)
            or not _is_fingerprint(self.request_fingerprint)
            or not _is_uuid(self.dataset_pair_authority_id)
            or not all(
                _is_reference(value)
                for value in (
                    self.dataset_version_id,
                    self.dataset_manifest_id,
                    self.prerequisite_policy_reference,
                )
            )
            or not all(
                _is_fingerprint(value)
                for value in (
                    self.dataset_pair_fingerprint,
                    self.config_fingerprint,
                    self.readiness_fingerprint,
                )
            )
            or type(self.source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None
        ):
            raise _decision_invalid()

    def __repr__(self) -> str:
        return "TrainingDecisionResolutionRequest(<redacted>)"


class TrustedTrainingDecisionResolver(Protocol):
    """Construction-bound resolver; implementations are not caller input."""

    def resolve(
        self, request: TrainingDecisionResolutionRequest
    ) -> TrustedDecisionResolution:
        """Resolve the intent's authoritative immutable decision record."""
        ...


def _resolve_trusted_training_decision(
    resolver: TrustedTrainingDecisionResolver,
    request: TrainingDecisionResolutionRequest,
) -> ResolvedTrainingExecutionDecision:
    return _resolve_trusted_training_decision_resolution(resolver, request).decision


def _resolve_trusted_training_decision_resolution(
    resolver: TrustedTrainingDecisionResolver,
    request: TrainingDecisionResolutionRequest,
) -> TrustedDecisionResolution:
    if type(request) is not TrainingDecisionResolutionRequest:
        raise _decision_invalid()
    try:
        resolution = resolver.resolve(request)
        if type(resolution) is not TrustedDecisionResolution:
            raise _decision_invalid()
        decision = resolution.decision
        provenance = resolution.provenance
        if (
            type(decision) is not ResolvedTrainingExecutionDecision
            or type(provenance) is not TrustedDecisionProvenance
            or provenance.current is not True
            or provenance.issuer_current is not True
            or provenance.approver_current is not True
            or provenance.decision_authority_id != request.decision_authority_id
            or decision.authorization_id != provenance.bound_authorization_id
            or decision.issuer_id != provenance.bound_issuer_id
            or decision.approver_reference != provenance.bound_approver_reference
            or decision.evidence_reference != provenance.bound_evidence_reference
            or decision.evidence_reference != request.intent.decision_evidence_reference
        ):
            raise _decision_invalid()
        if decision.request_fingerprint != request.request_fingerprint:
            raise _error(
                "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
                "The approval target does not match the execution request.",
            )
        return resolution
    except TrainingError as exc:
        if type(exc) is TrainingError and exc.code in {
            "TRAINING_EXECUTION_DECISION_INVALID",
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
        }:
            raise
        raise _decision_invalid() from None
    except Exception:
        raise _error(
            "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
            "A training execution decision is unavailable.",
        ) from None


class TrainingOrchestrationPhase(str, Enum):
    CLAIMED = "claimed"
    RESOLVED = "resolved"
    VALIDATED = "validated"
    DECISION_SUBMITTED = "decision_submitted"
    BACKEND_ENTERED = "backend_entered"
    APPROVAL_CONSUMED = "approval_consumed"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_RECONCILIATION_REQUIRED = "manual_reconciliation_required"


_TERMINAL_PHASES = frozenset(
    {
        TrainingOrchestrationPhase.COMPLETED,
        TrainingOrchestrationPhase.FAILED,
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
    }
)
_TRANSITIONS = {
    TrainingOrchestrationPhase.CLAIMED: frozenset(
        {
            TrainingOrchestrationPhase.RESOLVED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
    TrainingOrchestrationPhase.RESOLVED: frozenset(
        {
            TrainingOrchestrationPhase.VALIDATED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
    TrainingOrchestrationPhase.VALIDATED: frozenset(
        {
            TrainingOrchestrationPhase.DECISION_SUBMITTED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
    TrainingOrchestrationPhase.DECISION_SUBMITTED: frozenset(
        {
            TrainingOrchestrationPhase.APPROVAL_CONSUMED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
    TrainingOrchestrationPhase.APPROVAL_CONSUMED: frozenset(
        {
            TrainingOrchestrationPhase.BACKEND_ENTERED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
    TrainingOrchestrationPhase.BACKEND_ENTERED: frozenset(
        {
            TrainingOrchestrationPhase.COMPLETED,
            TrainingOrchestrationPhase.FAILED,
            TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        }
    ),
}


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TrainingOrchestrationIdentity:
    run_id: str
    request_fingerprint: str

    def __init__(self, *, run_id: str, request_fingerprint: str) -> None:
        if not _is_reference(run_id) or not _is_fingerprint(request_fingerprint):
            raise _journal_conflict()
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "request_fingerprint", request_fingerprint)

    def __repr__(self) -> str:
        return "TrainingOrchestrationIdentity(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingOrchestrationClaimRequest:
    """Complete immutable binding required by the restricted claim function."""

    identity: TrainingOrchestrationIdentity
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

    def __post_init__(self) -> None:
        if (
            type(self.identity) is not TrainingOrchestrationIdentity
            or not _is_fingerprint(self.intent_fingerprint)
            or not all(
                _is_reference(value)
                for value in (
                    self.orchestration_correlation_id,
                    self.dataset_version_id,
                    self.dataset_manifest_id,
                    self.prerequisite_policy_reference,
                    self.process_boundary_id,
                )
            )
            or not all(
                _is_fingerprint(value)
                for value in (
                    self.dataset_pair_fingerprint,
                    self.config_fingerprint,
                    self.readiness_fingerprint,
                )
            )
            or type(self.source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None
        ):
            raise _journal_conflict()

    def __repr__(self) -> str:
        return "TrainingOrchestrationClaimRequest(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingOrchestrationRecord:
    claim: TrainingOrchestrationClaimRequest
    phase: TrainingOrchestrationPhase
    journal_version: int
    reservation_group_id: str
    authorization_id: str | None = None
    issuer_id: str | None = None
    approver_reference: str | None = None
    evidence_reference: str | None = None
    decision_policy_reference: str | None = None
    authorization_fingerprint: str | None = None
    decision_evidence_fingerprint: str | None = None
    backend_entered: bool = False
    reconciliation_required: bool = False
    reason_code: str | None = None

    def __post_init__(self) -> None:
        optional_fingerprints = (
            self.authorization_fingerprint,
            self.decision_evidence_fingerprint,
        )
        decision_binding = (
            self.authorization_id,
            self.issuer_id,
            self.approver_reference,
            self.evidence_reference,
            self.decision_policy_reference,
            self.authorization_fingerprint,
            self.decision_evidence_fingerprint,
        )
        if (
            type(self.claim) is not TrainingOrchestrationClaimRequest
            or type(self.phase) is not TrainingOrchestrationPhase
            or type(self.journal_version) is not int
            or self.journal_version < 1
            or not _is_uuid(self.reservation_group_id)
            or any(
                value is not None and not _is_fingerprint(value)
                for value in optional_fingerprints
            )
            or any(
                value is not None and not _is_reference(value)
                for value in decision_binding[:5]
            )
            or any(value is not None for value in decision_binding)
            is not all(value is not None for value in decision_binding)
            or type(self.backend_entered) is not bool
            or type(self.reconciliation_required) is not bool
            or (
                self.reason_code is not None
                and (
                    type(self.reason_code) is not str
                    or _REASON_CODE_PATTERN.fullmatch(self.reason_code) is None
                )
            )
            or (self.phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED)
            is not self.reconciliation_required
            or (
                self.phase
                in {
                    TrainingOrchestrationPhase.BACKEND_ENTERED,
                    TrainingOrchestrationPhase.COMPLETED,
                }
                and not self.backend_entered
            )
            or (
                self.phase is TrainingOrchestrationPhase.APPROVAL_CONSUMED
                and self.backend_entered
            )
        ):
            raise _journal_conflict()

    @property
    def identity(self) -> TrainingOrchestrationIdentity:
        return self.claim.identity

    @property
    def process_boundary_id(self) -> str:
        return self.claim.process_boundary_id

    def __repr__(self) -> str:
        return "TrainingOrchestrationRecord(<redacted>)"


class TrainingOrchestrationClaimStatus(str, Enum):
    ACQUIRED = "acquired"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingOrchestrationClaimResult:
    status: TrainingOrchestrationClaimStatus
    record: TrainingOrchestrationRecord

    def __post_init__(self) -> None:
        if (
            type(self.status) is not TrainingOrchestrationClaimStatus
            or type(self.record) is not TrainingOrchestrationRecord
        ):
            raise _journal_conflict()

    def __repr__(self) -> str:
        return "TrainingOrchestrationClaimResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class TrainingOrchestrationTransition:
    identity: TrainingOrchestrationIdentity
    process_boundary_id: str
    expected_phase: TrainingOrchestrationPhase
    expected_version: int
    next_phase: TrainingOrchestrationPhase
    authorization_id: str | None = None
    issuer_id: str | None = None
    approver_reference: str | None = None
    evidence_reference: str | None = None
    decision_policy_reference: str | None = None
    authorization_fingerprint: str | None = None
    decision_evidence_fingerprint: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.identity) is not TrainingOrchestrationIdentity
            or not _is_reference(self.process_boundary_id)
            or type(self.expected_phase) is not TrainingOrchestrationPhase
            or type(self.expected_version) is not int
            or self.expected_version < 1
            or type(self.next_phase) is not TrainingOrchestrationPhase
            or self.expected_phase in _TERMINAL_PHASES
            or self.next_phase not in _TRANSITIONS.get(self.expected_phase, frozenset())
            or any(
                value is not None and not _is_fingerprint(value)
                for value in (
                    self.authorization_fingerprint,
                    self.decision_evidence_fingerprint,
                )
            )
            or any(
                value is not None and not _is_reference(value)
                for value in (
                    self.authorization_id,
                    self.issuer_id,
                    self.approver_reference,
                    self.evidence_reference,
                    self.decision_policy_reference,
                )
            )
            or (self.next_phase is TrainingOrchestrationPhase.DECISION_SUBMITTED)
            is not all(
                value is not None
                for value in (
                    self.authorization_id,
                    self.issuer_id,
                    self.approver_reference,
                    self.evidence_reference,
                    self.decision_policy_reference,
                    self.authorization_fingerprint,
                    self.decision_evidence_fingerprint,
                )
            )
            or (
                self.reason_code is not None
                and (
                    type(self.reason_code) is not str
                    or _REASON_CODE_PATTERN.fullmatch(self.reason_code) is None
                )
            )
        ):
            raise _journal_conflict()

    def __repr__(self) -> str:
        return "TrainingOrchestrationTransition(<redacted>)"


class DurableTrainingOrchestrationJournal(Protocol):
    """Durable CAS journal port; records never restore approval authority."""

    def claim(
        self, request: TrainingOrchestrationClaimRequest
    ) -> TrainingOrchestrationClaimResult:
        """Atomically acquire a new run or return its deterministic replay."""
        ...

    def read(self, run_id: str) -> TrainingOrchestrationRecord | None:
        """Read audit-safe state without reconstructing a capability."""
        ...

    def transition(
        self, transition: TrainingOrchestrationTransition
    ) -> TrainingOrchestrationRecord:
        """Atomically compare expected phase and commit the next phase."""
        ...


def _next_journal_record(
    current: TrainingOrchestrationRecord,
    transition: TrainingOrchestrationTransition,
) -> TrainingOrchestrationRecord:
    if (
        type(current) is not TrainingOrchestrationRecord
        or type(transition) is not TrainingOrchestrationTransition
        or current.identity != transition.identity
        or current.phase is not transition.expected_phase
        or current.journal_version != transition.expected_version
        or current.phase in _TERMINAL_PHASES
    ):
        raise _journal_conflict()
    authorization_fingerprint = (
        transition.authorization_fingerprint or current.authorization_fingerprint
    )
    evidence_fingerprint = (
        transition.decision_evidence_fingerprint
        or current.decision_evidence_fingerprint
    )
    if transition.next_phase is TrainingOrchestrationPhase.DECISION_SUBMITTED and (
        authorization_fingerprint is None or evidence_fingerprint is None
    ):
        raise _journal_conflict()
    backend_entered = current.backend_entered or transition.next_phase in {
        TrainingOrchestrationPhase.BACKEND_ENTERED,
        TrainingOrchestrationPhase.COMPLETED,
    }
    return TrainingOrchestrationRecord(
        claim=current.claim,
        phase=transition.next_phase,
        journal_version=current.journal_version + 1,
        reservation_group_id=current.reservation_group_id,
        authorization_id=(
            transition.authorization_id
            if transition.authorization_id is not None
            else current.authorization_id
        ),
        issuer_id=(
            transition.issuer_id
            if transition.issuer_id is not None
            else current.issuer_id
        ),
        approver_reference=(
            transition.approver_reference
            if transition.approver_reference is not None
            else current.approver_reference
        ),
        evidence_reference=(
            transition.evidence_reference
            if transition.evidence_reference is not None
            else current.evidence_reference
        ),
        decision_policy_reference=(
            transition.decision_policy_reference
            if transition.decision_policy_reference is not None
            else current.decision_policy_reference
        ),
        authorization_fingerprint=authorization_fingerprint,
        decision_evidence_fingerprint=evidence_fingerprint,
        backend_entered=backend_entered,
        reconciliation_required=transition.next_phase
        is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
        reason_code=transition.reason_code,
    )


__all__ = [
    "DurableTrainingOrchestrationJournal",
    "ProductionTrainingHostIntent",
    "ResolvedTrainingExecutionDecision",
    "TrainingOrchestrationClaimResult",
    "TrainingOrchestrationClaimRequest",
    "TrainingOrchestrationClaimStatus",
    "TrainingOrchestrationIdentity",
    "TrainingOrchestrationPhase",
    "TrainingOrchestrationRecord",
    "TrainingOrchestrationTransition",
    "TrainingDecisionResolutionRequest",
    "TrustedDecisionProvenance",
    "TrustedDecisionResolution",
    "TrustedTrainingDecisionResolver",
]
