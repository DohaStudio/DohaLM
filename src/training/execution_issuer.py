"""Same-process production Training Execution decision and issuer boundary."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Any

from .dataset_training_entry import DatasetTrainingPermission
from .errors import TrainingError
from .execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    _dataset_permission_for_training_execution_request,
    _issue_training_execution_approval_from_trusted_adapter,
)


_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class TrainingExecutionIssuerDecisionValue(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


@dataclass(frozen=True)
class TrainingExecutionIssuerDecision:
    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    issued_at: str


@dataclass(frozen=True)
class _TrainingExecutionDecisionSubmission:
    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    issued_at: str


class _TrainingExecutionSubmissionCapability:
    """Identity-only authority created with one decision source."""

    __slots__ = ()


class _TrainingExecutionDecisionUnavailable(RuntimeError):
    """Internal control signal for an absent business decision."""


class _TrainingExecutionDecisionReplay(RuntimeError):
    """Internal control signal for an already-claimed business decision."""


@dataclass(frozen=True)
class _DecisionMaterial:
    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_id: str
    approver_reference: str
    evidence_reference: str
    request_fingerprint: str
    issued_at: str


@dataclass
class _DecisionRecord:
    material: _DecisionMaterial
    claimed: bool = False


def _values(value: object) -> tuple[Any, ...]:
    return tuple(getattr(value, item.name) for item in fields(value))


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _decision_invalid() -> TrainingError:
    return _error(
        "TRAINING_EXECUTION_DECISION_INVALID",
        "A valid training execution decision is required.",
    )


def _valid_timestamp(value: str) -> bool:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def _validated_material(
    submission: _TrainingExecutionDecisionSubmission,
) -> _DecisionMaterial:
    if type(submission) is not _TrainingExecutionDecisionSubmission:
        raise _decision_invalid()
    if type(submission.decision) is not TrainingExecutionIssuerDecisionValue:
        raise _decision_invalid()
    evidence = (
        submission.authorization_id,
        submission.issuer_id,
        submission.approver_reference,
        submission.evidence_reference,
        submission.request_fingerprint,
        submission.issued_at,
    )
    if not all(isinstance(value, str) and value.strip() for value in evidence):
        raise _decision_invalid()
    if _FINGERPRINT_PATTERN.fullmatch(submission.request_fingerprint) is None:
        raise _decision_invalid()
    if not _valid_timestamp(submission.issued_at):
        raise _decision_invalid()
    return _DecisionMaterial(*_values(submission))


class TrainingExecutionDecisionSource:
    """Process-local, request-bound, single-use business decision source."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capability = _TrainingExecutionSubmissionCapability()
        self._by_authorization: dict[str, _DecisionRecord] = {}
        self._by_request: dict[str, _DecisionRecord] = {}

    def _submit(
        self,
        capability: _TrainingExecutionSubmissionCapability,
        submission: _TrainingExecutionDecisionSubmission,
    ) -> None:
        if capability is not self._capability:
            raise _error(
                "TRAINING_EXECUTION_DECISION_SUBMITTER_UNAUTHORIZED",
                "The training execution decision submitter is unauthorized.",
            )
        material = _validated_material(submission)
        with self._lock:
            by_authorization = self._by_authorization.get(material.authorization_id)
            by_request = self._by_request.get(material.request_fingerprint)
            if by_authorization is None and by_request is None:
                record = _DecisionRecord(material)
                self._by_authorization[material.authorization_id] = record
                self._by_request[material.request_fingerprint] = record
                return
            if (
                by_authorization is not None
                and by_authorization is by_request
                and by_authorization.material == material
            ):
                raise _error(
                    "TRAINING_EXECUTION_DECISION_SUBMISSION_REPLAYED",
                    "The training execution decision submission was replayed.",
                )
            raise _error(
                "TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT",
                "The training execution decision submission conflicts with existing state.",
            )

    def claim(self, request_fingerprint: str) -> _DecisionMaterial:
        if (
            not isinstance(request_fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(request_fingerprint) is None
        ):
            raise _decision_invalid()
        with self._lock:
            record = self._by_request.get(request_fingerprint)
            if record is None:
                raise _TrainingExecutionDecisionUnavailable()
            if record.claimed:
                raise _TrainingExecutionDecisionReplay()
            record.claimed = True
            return record.material


@dataclass(frozen=True)
class ProductionTrainingExecutionIssuerAdapter:
    _decision_source: TrainingExecutionDecisionSource

    def __post_init__(self) -> None:
        if type(self._decision_source) is not TrainingExecutionDecisionSource:
            raise _decision_invalid()

    def decide(
        self, request: TrainingExecutionRequest
    ) -> TrainingExecutionIssuerDecision:
        material = self._decision_source.claim(request.request_fingerprint)
        return TrainingExecutionIssuerDecision(*_values(material))


@dataclass(frozen=True)
class _AdapterRegistration:
    adapter: ProductionTrainingExecutionIssuerAdapter
    decision_source: TrainingExecutionDecisionSource


@dataclass(frozen=True)
class _SubmissionBinding:
    capability: _TrainingExecutionSubmissionCapability
    decision_source: TrainingExecutionDecisionSource


@dataclass(frozen=True)
class _DecisionProvenance:
    decision: TrainingExecutionIssuerDecision
    adapter: ProductionTrainingExecutionIssuerAdapter
    request: TrainingExecutionRequest
    values: tuple[Any, ...]


_ISSUER_LOCK = threading.RLock()
_ADAPTER_REGISTRATION: _AdapterRegistration | None = None
_SUBMISSION_BINDINGS: dict[int, _SubmissionBinding] = {}
_DECISION_PROVENANCE: dict[int, _DecisionProvenance] = {}
_DECISION_REPLAY_KEYS: set[tuple[str, str]] = set()


def _register_training_execution_issuer_adapter(
    adapter: ProductionTrainingExecutionIssuerAdapter,
) -> None:
    global _ADAPTER_REGISTRATION
    if type(adapter) is not ProductionTrainingExecutionIssuerAdapter:
        raise _error(
            "TRAINING_EXECUTION_ISSUER_UNAUTHENTICATED",
            "A trusted training execution issuer adapter is required.",
        )
    source = adapter._decision_source
    if type(source) is not TrainingExecutionDecisionSource:
        raise _error(
            "TRAINING_EXECUTION_ISSUER_UNAUTHENTICATED",
            "A trusted training execution issuer adapter is required.",
        )
    capability = source._capability
    with _ISSUER_LOCK:
        if _ADAPTER_REGISTRATION is not None:
            raise _error(
                "TRAINING_EXECUTION_ISSUER_UNAUTHORIZED",
                "The training execution issuer is already registered.",
            )
        _ADAPTER_REGISTRATION = _AdapterRegistration(adapter, source)
        _SUBMISSION_BINDINGS[id(capability)] = _SubmissionBinding(capability, source)


def _compose_production_training_execution_issuer() -> (
    _TrainingExecutionSubmissionCapability
):
    source = TrainingExecutionDecisionSource()
    adapter = ProductionTrainingExecutionIssuerAdapter(source)
    _register_training_execution_issuer_adapter(adapter)
    return source._capability


def _submit_training_execution_decision_from_trusted_orchestrator(
    capability: _TrainingExecutionSubmissionCapability,
    submission: _TrainingExecutionDecisionSubmission,
) -> None:
    with _ISSUER_LOCK:
        binding = _SUBMISSION_BINDINGS.get(id(capability))
        if binding is None or binding.capability is not capability:
            raise _error(
                "TRAINING_EXECUTION_DECISION_SUBMITTER_UNAUTHORIZED",
                "The training execution decision submitter is unauthorized.",
            )
        source = binding.decision_source
    source._submit(capability, submission)


def _registered_adapter() -> _AdapterRegistration:
    with _ISSUER_LOCK:
        registration = _ADAPTER_REGISTRATION
        if registration is None:
            raise _error(
                "TRAINING_EXECUTION_ISSUER_UNAVAILABLE",
                "The training execution issuer is unavailable.",
            )
        if registration.adapter._decision_source is not registration.decision_source:
            raise _error(
                "TRAINING_EXECUTION_ISSUER_UNAUTHORIZED",
                "The training execution issuer is unauthorized.",
            )
        return registration


def _claim_returned_decision(
    decision: TrainingExecutionIssuerDecision,
    adapter: ProductionTrainingExecutionIssuerAdapter,
    request: TrainingExecutionRequest,
) -> tuple[Any, ...]:
    if type(decision) is not TrainingExecutionIssuerDecision:
        raise _decision_invalid()
    values = _values(decision)
    identity = id(decision)
    with _ISSUER_LOCK:
        if identity in _DECISION_PROVENANCE:
            raise _error(
                "TRAINING_EXECUTION_DECISION_REPLAYED",
                "The training execution decision was replayed.",
            )
        replay_key: tuple[str, str] | None = None
        if isinstance(decision.authorization_id, str) and isinstance(
            decision.request_fingerprint, str
        ):
            replay_key = (
                decision.authorization_id,
                decision.request_fingerprint,
            )
            if replay_key in _DECISION_REPLAY_KEYS:
                raise _error(
                    "TRAINING_EXECUTION_DECISION_REPLAYED",
                    "The training execution decision was replayed.",
                )
        _DECISION_PROVENANCE[identity] = _DecisionProvenance(
            decision, adapter, request, values
        )
        if replay_key is not None:
            _DECISION_REPLAY_KEYS.add(replay_key)
    return values


def _validate_returned_decision(
    decision: object,
    request: TrainingExecutionRequest,
) -> None:
    if type(decision) is not TrainingExecutionIssuerDecision:
        raise _decision_invalid()
    if type(decision.decision) is not TrainingExecutionIssuerDecisionValue:
        raise _decision_invalid()
    evidence = (
        decision.authorization_id,
        decision.issuer_id,
        decision.approver_reference,
        decision.evidence_reference,
        decision.request_fingerprint,
        decision.issued_at,
    )
    if not all(isinstance(value, str) and value.strip() for value in evidence):
        raise _decision_invalid()
    if not _valid_timestamp(decision.issued_at):
        raise _decision_invalid()
    if decision.request_fingerprint != request.request_fingerprint:
        raise _error(
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
            "The approval target does not match the execution request.",
        )


def _validate_returned_decision_fail_closed(
    decision: object,
    request: TrainingExecutionRequest,
) -> None:
    try:
        _validate_returned_decision(decision, request)
    except TrainingError as exc:
        if type(exc) is TrainingError and exc.code in {
            "TRAINING_EXECUTION_DECISION_INVALID",
            "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH",
        }:
            raise
        raise _decision_invalid() from None
    except Exception:
        raise _decision_invalid() from None


def issue_training_execution_approval(
    request: TrainingExecutionRequest,
) -> TrainingExecutionApproval:
    """Invoke the registered adapter and issue one request-bound capability."""

    permission: DatasetTrainingPermission = (
        _dataset_permission_for_training_execution_request(request)
    )
    registration = _registered_adapter()
    try:
        decision = registration.adapter.decide(request)
    except _TrainingExecutionDecisionUnavailable as exc:
        if type(exc) is _TrainingExecutionDecisionUnavailable:
            raise _error(
                "TRAINING_EXECUTION_DECISION_UNAVAILABLE",
                "A training execution decision is unavailable.",
            ) from None
        raise _decision_invalid() from None
    except _TrainingExecutionDecisionReplay as exc:
        if type(exc) is _TrainingExecutionDecisionReplay:
            raise _error(
                "TRAINING_EXECUTION_DECISION_REPLAYED",
                "The training execution decision was replayed.",
            ) from None
        raise _decision_invalid() from None
    except Exception:
        raise _decision_invalid() from None
    _validate_returned_decision_fail_closed(decision, request)
    _claim_returned_decision(decision, registration.adapter, request)
    if decision.decision is TrainingExecutionIssuerDecisionValue.DENIED:
        raise _error(
            "TRAINING_EXECUTION_APPROVAL_DENIED",
            "The accountable issuer denied this execution request.",
        )
    return _issue_training_execution_approval_from_trusted_adapter(
        request,
        dataset_permission=permission,
        decision=decision.decision.value,
        authorization_id=decision.authorization_id,
        issuer_id=decision.issuer_id,
        approver_reference=decision.approver_reference,
        evidence_reference=decision.evidence_reference,
        request_fingerprint=decision.request_fingerprint,
        issued_at=decision.issued_at,
    )


__all__ = ["issue_training_execution_approval"]
