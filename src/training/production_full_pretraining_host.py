"""Non-CLI same-process Production Full Pretraining Host.

Importing this module never installs an issuer, resolves authority, creates a
request, or enters the backend. A future production composition root must call
the package-private bootstrap exactly once with construction-owned dependencies.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, fields
from typing import Callable, Iterator

from src.data.checksums import checksum_value

from .errors import TrainingError
from .execution_approval import TrainingExecutionRequest
from .execution_issuer import (
    TrainingExecutionIssuerDecisionValue,
    _TrainingExecutionDecisionSubmission,
    _TrainingExecutionSubmissionCapability,
    _compose_production_training_execution_issuer,
    _release_production_training_execution_issuer,
    _submit_training_execution_decision_from_trusted_orchestrator,
)
from .production_host_foundation import (
    DurableTrainingOrchestrationJournal,
    ProductionTrainingHostIntent,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationClaimResult,
    TrainingOrchestrationClaimStatus,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrainingOrchestrationTransition,
    TrustedTrainingDecisionResolver,
    _is_uuid,
    _resolve_trusted_training_decision_resolution,
)
from .production_orchestration_seams import (
    ResolvedTrainingPrerequisites,
    _FullPretrainingLifecycleResult,
    _HostFullPretrainingBackendLifecycle,
    _TrustedTrainingPrerequisiteResolver,
    _build_training_execution_request_from_prerequisites,
    _resolve_training_prerequisites,
    _run_host_full_pretraining,
    _thaw_json,
)


_REASON_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_TERMINAL_PHASES = frozenset(
    {
        TrainingOrchestrationPhase.COMPLETED,
        TrainingOrchestrationPhase.FAILED,
        TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
    }
)


def _host_error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _construction_unauthorized() -> TrainingError:
    return _host_error(
        "TRAINING_HOST_CONSTRUCTION_UNAUTHORIZED",
        "The production training Host must be installed by its composition root.",
    )


def _bootstrap_conflict() -> TrainingError:
    return _host_error(
        "TRAINING_HOST_BOOTSTRAP_CONFLICT",
        "The production training Host is already bound to another object graph.",
    )


def _journal_unavailable() -> TrainingError:
    return _host_error(
        "TRAINING_HOST_JOURNAL_UNAVAILABLE",
        "The training orchestration journal is unavailable.",
    )


def _journal_conflict() -> TrainingError:
    return _host_error(
        "TRAINING_HOST_JOURNAL_CONFLICT",
        "The training orchestration journal state conflicts with this operation.",
    )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ProductionTrainingHostResult:
    """Sanitized caller result; never contains authority or backend payload."""

    identity: TrainingOrchestrationIdentity
    phase: TrainingOrchestrationPhase
    backend_entered: bool
    reconciliation_required: bool
    replayed: bool
    reason_code: str | None

    def __init__(
        self,
        *,
        identity: TrainingOrchestrationIdentity,
        phase: TrainingOrchestrationPhase,
        backend_entered: bool,
        reconciliation_required: bool,
        replayed: bool,
        reason_code: str | None,
    ) -> None:
        if (
            type(identity) is not TrainingOrchestrationIdentity
            or type(phase) is not TrainingOrchestrationPhase
            or type(backend_entered) is not bool
            or type(reconciliation_required) is not bool
            or type(replayed) is not bool
            or (phase is TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED)
            is not reconciliation_required
            or (
                phase
                in {
                    TrainingOrchestrationPhase.BACKEND_ENTERED,
                    TrainingOrchestrationPhase.COMPLETED,
                }
                and not backend_entered
            )
            or (
                phase is TrainingOrchestrationPhase.APPROVAL_CONSUMED
                and backend_entered
            )
            or (
                reason_code is not None
                and (
                    type(reason_code) is not str
                    or _REASON_CODE_PATTERN.fullmatch(reason_code) is None
                )
            )
        ):
            raise _journal_conflict()
        values = (
            identity,
            phase,
            backend_entered,
            reconciliation_required,
            replayed,
            reason_code,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "ProductionTrainingHostResult(<redacted>)"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class _HostBackendBinding:
    _runner: Callable[..., _FullPretrainingLifecycleResult]
    _identity: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise _construction_unauthorized()

    def __repr__(self) -> str:
        return "_HostBackendBinding(<redacted>)"

    def _run(
        self,
        lifecycle: _HostFullPretrainingBackendLifecycle,
        resolved: ResolvedTrainingPrerequisites,
        request: TrainingExecutionRequest,
    ) -> _FullPretrainingLifecycleResult:
        return self._runner(
            lifecycle,
            resolved.config_path,
            resolved.manifest_path,
            _thaw_json(resolved.readiness_report),
            dataset_permission=resolved.dataset_permission,
            dataset_version_id=resolved.dataset_version_id,
            dataset_manifest_id=resolved.dataset_manifest_id,
            dataset_pair_fingerprint=resolved.dataset_pair_fingerprint,
            execution_request=request,
        )


def _new_backend_binding(
    runner: Callable[..., _FullPretrainingLifecycleResult], *, identity: object
) -> _HostBackendBinding:
    if not callable(runner):
        raise _construction_unauthorized()
    binding = object.__new__(_HostBackendBinding)
    object.__setattr__(binding, "_runner", runner)
    object.__setattr__(binding, "_identity", identity)
    return binding


_CANONICAL_BACKEND_IDENTITY = object()
_CANONICAL_BACKEND_BINDING = _new_backend_binding(
    _run_host_full_pretraining,
    identity=_CANONICAL_BACKEND_IDENTITY,
)


def _bind_fake_host_backend_for_tests(
    runner: Callable[..., _FullPretrainingLifecycleResult],
) -> _HostBackendBinding:
    """Package-private test composition seam; never a runtime caller input."""

    return _new_backend_binding(runner, identity=runner)


class ProductionFullPretrainingHost:
    """The sole non-CLI application boundary for one installed object graph."""

    __slots__ = (
        "_active",
        "_backend_binding",
        "_decision_authority_id",
        "_decision_resolver",
        "_journal",
        "_lifecycle_lease",
        "_lock",
        "_prerequisite_resolver",
        "_process_boundary_id",
        "_submission_capability",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise _construction_unauthorized()

    def __repr__(self) -> str:
        return "ProductionFullPretrainingHost(<redacted>)"

    def run(self, intent: ProductionTrainingHostIntent) -> ProductionTrainingHostResult:
        """Resolve, claim, submit, and delegate exactly one orchestration attempt."""

        with self._lifecycle_lease.host_operation():
            return self._run(intent)

    def _run(
        self, intent: ProductionTrainingHostIntent
    ) -> ProductionTrainingHostResult:
        """Execute the existing orchestration while the lifecycle lease is held."""

        if type(intent) is not ProductionTrainingHostIntent:
            raise _host_error(
                "TRAINING_HOST_INTENT_INVALID",
                "A valid immutable production training intent is required.",
            )

        resolved = _resolve_training_prerequisites(self._prerequisite_resolver, intent)
        request = _build_training_execution_request_from_prerequisites(intent, resolved)
        identity = TrainingOrchestrationIdentity(
            run_id=request.run_id,
            request_fingerprint=request.request_fingerprint,
        )
        try:
            existing = self._journal.read(identity.run_id)
        except Exception:
            raise _journal_unavailable() from None
        if existing is not None:
            if (
                type(existing) is not TrainingOrchestrationRecord
                or existing.identity != identity
            ):
                raise _journal_conflict()
            return self._replay_result(existing)
        decision_request = TrainingDecisionResolutionRequest(
            intent=intent,
            decision_authority_id=self._decision_authority_id,
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
        resolution = _resolve_trusted_training_decision_resolution(
            self._decision_resolver,
            decision_request,
        )
        decision = resolution.decision
        if decision.decision is TrainingExecutionIssuerDecisionValue.DENIED:
            return ProductionTrainingHostResult(
                identity=identity,
                phase=TrainingOrchestrationPhase.FAILED,
                backend_entered=False,
                reconciliation_required=False,
                replayed=False,
                reason_code="TRAINING_EXECUTION_APPROVAL_DENIED",
            )
        claim_request = TrainingOrchestrationClaimRequest(
            identity=identity,
            intent_fingerprint=resolved.intent_fingerprint,
            orchestration_correlation_id=identity.run_id,
            dataset_version_id=resolved.dataset_version_id,
            dataset_manifest_id=resolved.dataset_manifest_id,
            dataset_pair_fingerprint=resolved.dataset_pair_fingerprint,
            config_fingerprint=resolved.config_fingerprint,
            readiness_fingerprint=resolved.readiness_fingerprint,
            source_commit=resolved.source_commit,
            prerequisite_policy_reference=resolved.provenance.resolution_policy_reference,
            process_boundary_id=self._process_boundary_id,
        )

        acquired = False
        with self._lock:
            claim = self._claim(claim_request)
            if claim.status is TrainingOrchestrationClaimStatus.REPLAY:
                return self._replay_result(claim.record)
            self._active.add(identity)
            acquired = True

        try:
            self._transition(
                identity,
                TrainingOrchestrationPhase.CLAIMED,
                TrainingOrchestrationPhase.RESOLVED,
            )
            self._transition(
                identity,
                TrainingOrchestrationPhase.RESOLVED,
                TrainingOrchestrationPhase.VALIDATED,
            )
            submission = _TrainingExecutionDecisionSubmission(
                decision=decision.decision,
                authorization_id=decision.authorization_id,
                issuer_id=decision.issuer_id,
                approver_reference=decision.approver_reference,
                evidence_reference=decision.evidence_reference,
                request_fingerprint=decision.request_fingerprint,
                issued_at=decision.issued_at,
            )
            try:
                _submit_training_execution_decision_from_trusted_orchestrator(
                    self._submission_capability, submission
                )
            except TrainingError as exc:
                self._record_known_failure(
                    identity,
                    TrainingOrchestrationPhase.VALIDATED,
                    exc.code,
                )
                raise
            except Exception:
                return self._record_outcome_unknown(
                    identity,
                    TrainingOrchestrationPhase.VALIDATED,
                    "TRAINING_EXECUTION_SUBMISSION_OUTCOME_UNKNOWN",
                )

            try:
                self._transition(
                    identity,
                    TrainingOrchestrationPhase.VALIDATED,
                    TrainingOrchestrationPhase.DECISION_SUBMITTED,
                    authorization_id=decision.authorization_id,
                    issuer_id=decision.issuer_id,
                    approver_reference=decision.approver_reference,
                    evidence_reference=decision.evidence_reference,
                    decision_policy_reference=resolution.provenance.policy_reference,
                    authorization_fingerprint=checksum_value(decision.authorization_id),
                    decision_evidence_fingerprint=checksum_value(
                        decision.evidence_reference
                    ),
                )
            except TrainingError:
                return self._record_outcome_unknown(
                    identity,
                    TrainingOrchestrationPhase.VALIDATED,
                    "TRAINING_HOST_DECISION_SUBMISSION_UNCERTAIN",
                )

            lifecycle = _HostFullPretrainingBackendLifecycle(self._journal, identity)
            try:
                lifecycle_result = self._backend_binding._run(
                    lifecycle, resolved, request
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                record = self._read_record(identity)
                return self._record_outcome_unknown(
                    identity,
                    record.phase,
                    "TRAINING_BACKEND_OUTCOME_UNKNOWN",
                )
            if type(lifecycle_result) is not _FullPretrainingLifecycleResult:
                return self._record_outcome_unknown(
                    identity,
                    TrainingOrchestrationPhase.DECISION_SUBMITTED,
                    "TRAINING_BACKEND_OUTCOME_UNKNOWN",
                )
            return self._lifecycle_result(lifecycle_result)
        finally:
            if acquired:
                with self._lock:
                    self._active.discard(identity)

    def _claim(
        self, request: TrainingOrchestrationClaimRequest
    ) -> TrainingOrchestrationClaimResult:
        try:
            claim = self._journal.claim(request)
        except TrainingError as exc:
            if (
                type(exc) is TrainingError
                and exc.code == "TRAINING_HOST_JOURNAL_CONFLICT"
            ):
                raise
            raise _journal_unavailable() from None
        except Exception:
            raise _journal_unavailable() from None
        if (
            type(claim) is not TrainingOrchestrationClaimResult
            or type(claim.record) is not TrainingOrchestrationRecord
            or claim.record.identity != request.identity
            or claim.record.claim != request
            or (
                claim.status is TrainingOrchestrationClaimStatus.ACQUIRED
                and claim.record.phase is not TrainingOrchestrationPhase.CLAIMED
            )
        ):
            raise _journal_conflict()
        return claim

    def _read_record(
        self, identity: TrainingOrchestrationIdentity
    ) -> TrainingOrchestrationRecord:
        try:
            record = self._journal.read(identity.run_id)
        except Exception:
            raise _journal_unavailable() from None
        if (
            type(record) is not TrainingOrchestrationRecord
            or record.identity != identity
        ):
            raise _journal_conflict()
        return record

    def _transition(
        self,
        identity: TrainingOrchestrationIdentity,
        expected: TrainingOrchestrationPhase,
        next_phase: TrainingOrchestrationPhase,
        *,
        authorization_id: str | None = None,
        issuer_id: str | None = None,
        approver_reference: str | None = None,
        evidence_reference: str | None = None,
        decision_policy_reference: str | None = None,
        authorization_fingerprint: str | None = None,
        decision_evidence_fingerprint: str | None = None,
        reason_code: str | None = None,
    ) -> TrainingOrchestrationRecord:
        current = self._read_record(identity)
        if current.phase is not expected:
            raise _journal_conflict()
        transition = TrainingOrchestrationTransition(
            identity=identity,
            process_boundary_id=self._process_boundary_id,
            expected_phase=expected,
            expected_version=current.journal_version,
            next_phase=next_phase,
            authorization_id=authorization_id,
            issuer_id=issuer_id,
            approver_reference=approver_reference,
            evidence_reference=evidence_reference,
            decision_policy_reference=decision_policy_reference,
            authorization_fingerprint=authorization_fingerprint,
            decision_evidence_fingerprint=decision_evidence_fingerprint,
            reason_code=reason_code,
        )
        try:
            record = self._journal.transition(transition)
        except TrainingError as exc:
            if (
                type(exc) is TrainingError
                and exc.code == "TRAINING_HOST_JOURNAL_CONFLICT"
            ):
                raise
            raise _journal_unavailable() from None
        except Exception:
            raise _journal_unavailable() from None
        if (
            type(record) is not TrainingOrchestrationRecord
            or record.identity != identity
            or record.phase is not next_phase
        ):
            raise _journal_conflict()
        return record

    def _record_known_failure(
        self,
        identity: TrainingOrchestrationIdentity,
        expected: TrainingOrchestrationPhase,
        reason_code: str,
    ) -> TrainingOrchestrationRecord:
        stable = (
            reason_code
            if type(reason_code) is str
            and _REASON_CODE_PATTERN.fullmatch(reason_code) is not None
            else "TRAINING_HOST_FAILED"
        )
        return self._transition(
            identity,
            expected,
            TrainingOrchestrationPhase.FAILED,
            reason_code=stable,
        )

    def _record_outcome_unknown(
        self,
        identity: TrainingOrchestrationIdentity,
        expected: TrainingOrchestrationPhase,
        reason_code: str,
    ) -> ProductionTrainingHostResult:
        try:
            record = self._transition(
                identity,
                expected,
                TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
                reason_code=reason_code,
            )
            return self._record_result(record, replayed=False)
        except TrainingError:
            return ProductionTrainingHostResult(
                identity=identity,
                phase=TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
                backend_entered=expected is TrainingOrchestrationPhase.BACKEND_ENTERED,
                reconciliation_required=True,
                replayed=False,
                reason_code=reason_code,
            )

    def _replay_result(
        self, record: TrainingOrchestrationRecord
    ) -> ProductionTrainingHostResult:
        if record.identity in self._active or record.phase in _TERMINAL_PHASES:
            return self._record_result(record, replayed=True)
        return self._record_outcome_unknown(
            record.identity,
            record.phase,
            "TRAINING_HOST_RESTART_RECONCILIATION_REQUIRED",
        )

    @staticmethod
    def _record_result(
        record: TrainingOrchestrationRecord, *, replayed: bool
    ) -> ProductionTrainingHostResult:
        return ProductionTrainingHostResult(
            identity=record.identity,
            phase=record.phase,
            backend_entered=record.backend_entered,
            reconciliation_required=record.reconciliation_required,
            replayed=replayed,
            reason_code=record.reason_code,
        )

    def _lifecycle_result(
        self, result: _FullPretrainingLifecycleResult
    ) -> ProductionTrainingHostResult:
        try:
            record = self._journal.read(result.identity.run_id)
        except Exception:
            record = None
        if (
            type(record) is TrainingOrchestrationRecord
            and record.identity == result.identity
            and record.phase in _TERMINAL_PHASES
        ):
            return self._record_result(record, replayed=False)
        return ProductionTrainingHostResult(
            identity=result.identity,
            phase=TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
            backend_entered=result.backend_entered,
            reconciliation_required=True,
            replayed=False,
            reason_code=result.reason_code or "TRAINING_BACKEND_OUTCOME_UNKNOWN",
        )


@dataclass(frozen=True, slots=True, repr=False)
class _BootstrapRegistration:
    dependency_identity: tuple[int, int, int, int, int, str, str]
    host: ProductionFullPretrainingHost

    def __repr__(self) -> str:
        return "_BootstrapRegistration(<redacted>)"


_BOOTSTRAP_LOCK = threading.RLock()
_BOOTSTRAP_REGISTRATION: _BootstrapRegistration | None = None


class _UnrestrictedHostLifecycleLease:
    """Compatibility lease for non-C3 package-private test composition."""

    @contextmanager
    def host_operation(self) -> Iterator[None]:
        yield


_UNRESTRICTED_HOST_LIFECYCLE_LEASE = _UnrestrictedHostLifecycleLease()


def _validate_dependency(value: object, methods: tuple[str, ...]) -> None:
    if value is None or any(
        not callable(getattr(value, name, None)) for name in methods
    ):
        raise _construction_unauthorized()


def _bootstrap_production_full_pretraining_host(
    prerequisite_resolver: _TrustedTrainingPrerequisiteResolver,
    decision_resolver: TrustedTrainingDecisionResolver,
    journal: DurableTrainingOrchestrationJournal,
    *,
    process_boundary_id: str,
    decision_authority_id: str,
    backend_binding: _HostBackendBinding = _CANONICAL_BACKEND_BINDING,
    lifecycle_lease: object = _UNRESTRICTED_HOST_LIFECYCLE_LEASE,
) -> ProductionFullPretrainingHost:
    """Install one immutable process object graph; identical replay is a no-op."""

    _validate_dependency(prerequisite_resolver, ("resolve",))
    _validate_dependency(decision_resolver, ("resolve",))
    _validate_dependency(journal, ("claim", "read", "transition"))
    if (
        type(backend_binding) is not _HostBackendBinding
        or not callable(getattr(lifecycle_lease, "host_operation", None))
        or type(process_boundary_id) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}", process_boundary_id)
        is None
        or not _is_uuid(decision_authority_id)
    ):
        raise _construction_unauthorized()
    identity = (
        id(prerequisite_resolver),
        id(decision_resolver),
        id(journal),
        id(backend_binding._identity),
        id(lifecycle_lease),
        process_boundary_id,
        decision_authority_id,
    )
    global _BOOTSTRAP_REGISTRATION
    with _BOOTSTRAP_LOCK:
        current = _BOOTSTRAP_REGISTRATION
        if current is not None:
            if current.dependency_identity == identity:
                return current.host
            raise _bootstrap_conflict()

        host = object.__new__(ProductionFullPretrainingHost)
        object.__setattr__(host, "_prerequisite_resolver", prerequisite_resolver)
        object.__setattr__(host, "_process_boundary_id", process_boundary_id)
        object.__setattr__(host, "_decision_authority_id", decision_authority_id)
        object.__setattr__(host, "_decision_resolver", decision_resolver)
        object.__setattr__(host, "_journal", journal)
        object.__setattr__(host, "_backend_binding", backend_binding)
        object.__setattr__(host, "_lifecycle_lease", lifecycle_lease)
        object.__setattr__(host, "_active", set())
        object.__setattr__(host, "_lock", threading.RLock())

        capability: _TrainingExecutionSubmissionCapability | None = None
        try:
            capability = _compose_production_training_execution_issuer()
            if type(capability) is not _TrainingExecutionSubmissionCapability:
                raise _construction_unauthorized()
            object.__setattr__(host, "_submission_capability", capability)
            _BOOTSTRAP_REGISTRATION = _BootstrapRegistration(identity, host)
            return host
        except BaseException as error:
            if capability is not None:
                _release_production_training_execution_issuer(capability)
            if isinstance(error, TrainingError) or not isinstance(error, Exception):
                raise
            raise _host_error(
                "TRAINING_HOST_BOOTSTRAP_FAILED",
                "The production training Host could not be installed.",
            ) from None


def _release_production_full_pretraining_host(
    host: ProductionFullPretrainingHost,
) -> bool:
    """Compare-and-clear only the registration owned by ``host``."""

    global _BOOTSTRAP_REGISTRATION
    with _BOOTSTRAP_LOCK:
        current = _BOOTSTRAP_REGISTRATION
        if current is None or current.host is not host:
            return False
        _BOOTSTRAP_REGISTRATION = None
        _release_production_training_execution_issuer(host._submission_capability)
        return True


__all__ = ["ProductionFullPretrainingHost", "ProductionTrainingHostResult"]
