"""Package-private prerequisite and backend lifecycle seams for a future Host.

Nothing in this module composes a production resolver, journal, issuer, or Host.
The future production composition root is the only permitted owner of these
internal contracts.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from src.data.checksums import checksum_value, file_checksum

from .dataset_training_entry import (
    DatasetTrainingPermission,
    require_dataset_training_activation,
)
from .errors import TrainingError
from .execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    _verified_source,
    build_training_execution_request,
)
from .full_pretraining import (
    FullPretrainingConfig,
    inspect_full_pretraining_readiness,
    require_full_pretraining_technical_readiness,
    resolve_full_pretraining_path,
)
from .production_host_foundation import (
    DurableTrainingOrchestrationJournal,
    ProductionTrainingHostIntent,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrainingOrchestrationTransition,
    _is_canonical_timestamp,
    _is_fingerprint,
    _is_logical_root,
    _is_reference,
)

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_REASON_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_PATH_TYPE = type(Path())


def _prerequisite_invalid() -> TrainingError:
    return TrainingError(
        "TRAINING_HOST_PREREQUISITE_INVALID",
        "Validated immutable training prerequisites are required.",
    )


def _prerequisite_unavailable() -> TrainingError:
    return TrainingError(
        "TRAINING_HOST_PREREQUISITE_UNAVAILABLE",
        "Authoritative training prerequisites are unavailable.",
    )


def _lifecycle_invalid() -> TrainingError:
    return TrainingError(
        "TRAINING_HOST_LIFECYCLE_INVALID",
        "A valid internal training backend lifecycle is required.",
    )


def _freeze_json(value: object) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _prerequisite_invalid()
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _prerequisite_invalid()
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    raise _prerequisite_invalid()


def _freeze_mapping(value: object) -> Mapping[str, Any]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise _prerequisite_invalid()
    return frozen


def _thaw_json(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TrustedPrerequisiteProvenance:
    dataset_source_identity: str
    config_source_identity: str
    readiness_source_identity: str
    resolution_policy_reference: str
    evaluated_at: str
    current: bool

    def __init__(
        self,
        *,
        dataset_source_identity: str,
        config_source_identity: str,
        readiness_source_identity: str,
        resolution_policy_reference: str,
        evaluated_at: str,
        current: bool,
    ) -> None:
        references = (
            dataset_source_identity,
            config_source_identity,
            readiness_source_identity,
            resolution_policy_reference,
        )
        if (
            not all(_is_reference(value) for value in references)
            or not _is_canonical_timestamp(evaluated_at)
            or current is not True
        ):
            raise _prerequisite_invalid()
        values = (*references, evaluated_at, current)
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "TrustedPrerequisiteProvenance(<redacted>)"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ResolvedTrainingPrerequisites:
    schema_version: int
    intent_fingerprint: str
    dataset_version_reference: str
    dataset_manifest_reference: str
    training_config_reference: str
    readiness_evidence_reference: str
    dataset_version_authority_id: str
    dataset_manifest_authority_id: str
    dataset_pair_authority_id: str
    config_authority_id: str
    readiness_authority_id: str
    config_path: Path
    config_snapshot: Mapping[str, Any]
    manifest_path: Path
    readiness_report: Mapping[str, Any]
    dataset_permission: DatasetTrainingPermission
    dataset_version_id: str
    dataset_manifest_id: str
    dataset_pair_fingerprint: str
    config_fingerprint: str
    readiness_fingerprint: str
    source_commit: str
    run_id: str
    output_logical_root: str
    provenance: TrustedPrerequisiteProvenance

    def __init__(
        self,
        *,
        schema_version: int,
        intent_fingerprint: str,
        dataset_version_reference: str,
        dataset_manifest_reference: str,
        training_config_reference: str,
        readiness_evidence_reference: str,
        dataset_version_authority_id: str,
        dataset_manifest_authority_id: str,
        dataset_pair_authority_id: str,
        config_authority_id: str,
        readiness_authority_id: str,
        config_path: Path,
        config_snapshot: Mapping[str, Any],
        manifest_path: Path,
        readiness_report: Mapping[str, Any],
        dataset_permission: DatasetTrainingPermission,
        dataset_version_id: str,
        dataset_manifest_id: str,
        dataset_pair_fingerprint: str,
        config_fingerprint: str,
        readiness_fingerprint: str,
        source_commit: str,
        run_id: str,
        output_logical_root: str,
        provenance: TrustedPrerequisiteProvenance,
    ) -> None:
        references = (
            dataset_version_reference,
            dataset_manifest_reference,
            training_config_reference,
            readiness_evidence_reference,
            dataset_version_id,
            dataset_manifest_id,
            run_id,
        )
        authority_ids = (
            dataset_version_authority_id,
            dataset_manifest_authority_id,
            dataset_pair_authority_id,
            config_authority_id,
            readiness_authority_id,
        )
        if (
            type(schema_version) is not int
            or schema_version != 1
            or not _is_fingerprint(intent_fingerprint)
            or not all(_is_reference(value) for value in references)
            or not all(_is_uuid(value) for value in authority_ids)
            or type(config_path) is not _PATH_TYPE
            or not config_path.is_absolute()
            or type(manifest_path) is not _PATH_TYPE
            or not manifest_path.is_absolute()
            or type(dataset_permission) is not DatasetTrainingPermission
            or not all(
                _is_fingerprint(value)
                for value in (
                    dataset_pair_fingerprint,
                    config_fingerprint,
                    readiness_fingerprint,
                )
            )
            or type(source_commit) is not str
            or _COMMIT_PATTERN.fullmatch(source_commit) is None
            or not _is_logical_root(output_logical_root)
            or type(provenance) is not TrustedPrerequisiteProvenance
        ):
            raise _prerequisite_invalid()
        values = (
            schema_version,
            intent_fingerprint,
            *references[:4],
            *authority_ids,
            config_path,
            _freeze_mapping(config_snapshot),
            manifest_path,
            _freeze_mapping(readiness_report),
            dataset_permission,
            *references[4:6],
            dataset_pair_fingerprint,
            config_fingerprint,
            readiness_fingerprint,
            source_commit,
            references[6],
            output_logical_root,
            provenance,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "ResolvedTrainingPrerequisites(<redacted>)"


def _is_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _authority_id(reference: str, namespace: str) -> str:
    prefix = f"{namespace}:"
    if type(reference) is not str or not reference.startswith(prefix):
        raise _prerequisite_invalid()
    value = reference[len(prefix) :]
    if not _is_uuid(value):
        raise _prerequisite_invalid()
    return value


@dataclass(frozen=True, slots=True, repr=False)
class TrainingPrerequisiteResolutionRequest:
    """Typed identities and expected bindings for one authority snapshot."""

    intent: ProductionTrainingHostIntent
    intent_fingerprint: str
    dataset_version_authority_id: str
    dataset_manifest_authority_id: str
    config_authority_id: str
    readiness_authority_id: str

    def __post_init__(self) -> None:
        if (
            type(self.intent) is not ProductionTrainingHostIntent
            or not _is_fingerprint(self.intent_fingerprint)
            or not all(
                _is_uuid(value)
                for value in (
                    self.dataset_version_authority_id,
                    self.dataset_manifest_authority_id,
                    self.config_authority_id,
                    self.readiness_authority_id,
                )
            )
        ):
            raise _prerequisite_invalid()

    def __repr__(self) -> str:
        return "TrainingPrerequisiteResolutionRequest(<redacted>)"


def _build_prerequisite_resolution_request(
    intent: ProductionTrainingHostIntent,
) -> TrainingPrerequisiteResolutionRequest:
    fingerprint = _canonical_training_host_intent_fingerprint(intent)
    return TrainingPrerequisiteResolutionRequest(
        intent=intent,
        intent_fingerprint=fingerprint,
        dataset_version_authority_id=_authority_id(
            intent.dataset_version_reference, "dataset-version"
        ),
        dataset_manifest_authority_id=_authority_id(
            intent.dataset_manifest_reference, "dataset-manifest"
        ),
        config_authority_id=_authority_id(intent.training_config_reference, "config"),
        readiness_authority_id=_authority_id(
            intent.readiness_evidence_reference, "readiness"
        ),
    )


class _TrustedTrainingPrerequisiteResolver(Protocol):
    def resolve(
        self, request: TrainingPrerequisiteResolutionRequest
    ) -> ResolvedTrainingPrerequisites:
        """Resolve authority objects bound at composition-root construction."""
        ...


def _canonical_training_host_intent_fingerprint(
    intent: ProductionTrainingHostIntent,
) -> str:
    if type(intent) is not ProductionTrainingHostIntent:
        raise _prerequisite_invalid()
    return checksum_value(
        {
            "action": intent.action,
            "execution_mode": intent.execution_mode,
            "dataset_version_reference": intent.dataset_version_reference,
            "dataset_manifest_reference": intent.dataset_manifest_reference,
            "expected_dataset_pair_fingerprint": intent.expected_dataset_pair_fingerprint,
            "training_config_reference": intent.training_config_reference,
            "expected_config_fingerprint": intent.expected_config_fingerprint,
            "readiness_evidence_reference": intent.readiness_evidence_reference,
            "expected_readiness_fingerprint": intent.expected_readiness_fingerprint,
            "run_id": intent.run_id,
            "output_logical_root": intent.output_logical_root,
            "decision_evidence_reference": intent.decision_evidence_reference,
        }
    )


@dataclass(frozen=True, slots=True, repr=False)
class _ValidatedPrerequisiteMaterial:
    config_path: Path
    manifest_path: Path
    readiness_report: dict[str, Any]

    def __repr__(self) -> str:
        return "_ValidatedPrerequisiteMaterial(<redacted>)"


def _validate_training_prerequisites(
    intent: ProductionTrainingHostIntent,
    resolved: ResolvedTrainingPrerequisites,
) -> _ValidatedPrerequisiteMaterial:
    try:
        intent_fingerprint = _canonical_training_host_intent_fingerprint(intent)
        if type(resolved) is not ResolvedTrainingPrerequisites:
            raise _prerequisite_invalid()
        if (
            resolved.schema_version != 1
            or resolved.intent_fingerprint != intent_fingerprint
            or resolved.dataset_version_reference != intent.dataset_version_reference
            or resolved.dataset_manifest_reference != intent.dataset_manifest_reference
            or resolved.training_config_reference != intent.training_config_reference
            or resolved.readiness_evidence_reference
            != intent.readiness_evidence_reference
            or resolved.dataset_version_authority_id
            != _authority_id(intent.dataset_version_reference, "dataset-version")
            or resolved.dataset_manifest_authority_id
            != _authority_id(intent.dataset_manifest_reference, "dataset-manifest")
            or resolved.config_authority_id
            != _authority_id(intent.training_config_reference, "config")
            or resolved.readiness_authority_id
            != _authority_id(intent.readiness_evidence_reference, "readiness")
            or resolved.dataset_pair_fingerprint
            != intent.expected_dataset_pair_fingerprint
            or resolved.config_fingerprint != intent.expected_config_fingerprint
            or resolved.readiness_fingerprint != intent.expected_readiness_fingerprint
            or resolved.run_id != intent.run_id
            or resolved.output_logical_root != intent.output_logical_root
            or type(resolved.provenance) is not TrustedPrerequisiteProvenance
            or resolved.provenance.current is not True
            or not _is_canonical_timestamp(resolved.provenance.evaluated_at)
        ):
            raise _prerequisite_invalid()

        require_dataset_training_activation(
            resolved.dataset_permission,
            dataset_version_id=resolved.dataset_version_id,
            dataset_manifest_id=resolved.dataset_manifest_id,
            pair_fingerprint=resolved.dataset_pair_fingerprint,
        )
        config_checksum_before = file_checksum(resolved.config_path)
        manifest_checksum_before = file_checksum(resolved.manifest_path)
        config = FullPretrainingConfig.from_yaml(resolved.config_path)
        report = inspect_full_pretraining_readiness(
            resolved.config_path, resolved.manifest_path
        )
        require_full_pretraining_technical_readiness(report)
        if (
            config.resume_checkpoint is not None
            or config_checksum_before != resolved.config_fingerprint
            or file_checksum(resolved.config_path) != config_checksum_before
            or file_checksum(resolved.manifest_path) != manifest_checksum_before
            or _freeze_mapping(config.to_dict()) != resolved.config_snapshot
            or _freeze_mapping(report) != resolved.readiness_report
            or report.get("source_commit") != resolved.source_commit
            or report.get("source_worktree_clean") is not True
            or config.output_dir != resolved.output_logical_root
            or resolve_full_pretraining_path(config, config.output_dir).name
            != resolved.run_id
        ):
            raise _prerequisite_invalid()
        _verified_source(resolved.source_commit)
        return _ValidatedPrerequisiteMaterial(
            config_path=resolved.config_path,
            manifest_path=resolved.manifest_path,
            readiness_report=_thaw_json(resolved.readiness_report),
        )
    except TrainingError as exc:
        if (
            type(exc) is TrainingError
            and exc.code == "TRAINING_HOST_PREREQUISITE_INVALID"
        ):
            raise
        raise _prerequisite_invalid() from None
    except Exception:
        raise _prerequisite_invalid() from None


def _resolve_training_prerequisites(
    resolver: _TrustedTrainingPrerequisiteResolver,
    intent: ProductionTrainingHostIntent,
) -> ResolvedTrainingPrerequisites:
    request = _build_prerequisite_resolution_request(intent)
    try:
        resolved = resolver.resolve(request)
    except BaseException as exc:
        if not isinstance(exc, Exception):
            raise
        raise _prerequisite_unavailable() from None
    _validate_training_prerequisites(intent, resolved)
    return resolved


def _build_training_execution_request_from_prerequisites(
    intent: ProductionTrainingHostIntent,
    resolved: ResolvedTrainingPrerequisites,
) -> TrainingExecutionRequest:
    material = _validate_training_prerequisites(intent, resolved)
    try:
        request = build_training_execution_request(
            material.config_path,
            material.readiness_report,
            readiness_fingerprint=resolved.readiness_fingerprint,
            dataset_permission=resolved.dataset_permission,
            dataset_version_id=resolved.dataset_version_id,
            dataset_manifest_id=resolved.dataset_manifest_id,
            dataset_pair_fingerprint=resolved.dataset_pair_fingerprint,
        )
        if (
            type(request) is not TrainingExecutionRequest
            or request.action != intent.action
            or request.execution_mode != intent.execution_mode
            or request.dataset_version_id != resolved.dataset_version_id
            or request.dataset_manifest_id != resolved.dataset_manifest_id
            or request.dataset_pair_fingerprint != resolved.dataset_pair_fingerprint
            or request.config_fingerprint != resolved.config_fingerprint
            or request.readiness_fingerprint != resolved.readiness_fingerprint
            or request.source_commit != resolved.source_commit
            or request.run_id != intent.run_id
            or request.output_logical_root != intent.output_logical_root
        ):
            raise _prerequisite_invalid()
        return request
    except TrainingError as exc:
        if (
            type(exc) is TrainingError
            and exc.code == "TRAINING_HOST_PREREQUISITE_INVALID"
        ):
            raise
        raise _prerequisite_invalid() from None
    except Exception:
        raise _prerequisite_invalid() from None


class _FullPretrainingLifecycleOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class _FullPretrainingLifecycleResult:
    identity: TrainingOrchestrationIdentity
    outcome: _FullPretrainingLifecycleOutcome
    approval_consumed: bool
    backend_entered: bool
    terminal_recorded: bool
    reason_code: str | None

    def __init__(
        self,
        *,
        identity: TrainingOrchestrationIdentity,
        outcome: _FullPretrainingLifecycleOutcome,
        approval_consumed: bool,
        backend_entered: bool,
        terminal_recorded: bool,
        reason_code: str | None,
    ) -> None:
        if (
            type(identity) is not TrainingOrchestrationIdentity
            or type(outcome) is not _FullPretrainingLifecycleOutcome
            or type(approval_consumed) is not bool
            or type(backend_entered) is not bool
            or type(terminal_recorded) is not bool
            or (backend_entered and not approval_consumed)
            or (
                reason_code is not None
                and (
                    type(reason_code) is not str
                    or _REASON_CODE_PATTERN.fullmatch(reason_code) is None
                )
            )
            or (
                outcome is _FullPretrainingLifecycleOutcome.SUCCEEDED
                and (
                    not approval_consumed
                    or not backend_entered
                    or not terminal_recorded
                    or reason_code is not None
                )
            )
        ):
            raise _lifecycle_invalid()
        values = (
            identity,
            outcome,
            approval_consumed,
            backend_entered,
            terminal_recorded,
            reason_code,
        )
        for item, value in zip(fields(self), values, strict=True):
            object.__setattr__(self, item.name, value)

    def __repr__(self) -> str:
        return "_FullPretrainingLifecycleResult(<redacted>)"


class _LifecycleJournalFailure(RuntimeError):
    pass


class _HostFullPretrainingBackendLifecycle:
    """Journal-bound lifecycle authority for the future production Host."""

    __slots__ = (
        "_approval_consumed",
        "_backend_entered",
        "_durable_phase",
        "_identity",
        "_journal",
        "_journal_version",
        "_lock",
        "_process_boundary_id",
        "_started",
    )

    def __init__(
        self,
        journal: DurableTrainingOrchestrationJournal,
        identity: TrainingOrchestrationIdentity,
    ) -> None:
        if type(identity) is not TrainingOrchestrationIdentity:
            raise _lifecycle_invalid()
        try:
            record = journal.read(identity.run_id)
        except Exception:
            raise _lifecycle_invalid() from None
        if (
            type(record) is not TrainingOrchestrationRecord
            or record.identity != identity
            or record.phase is not TrainingOrchestrationPhase.DECISION_SUBMITTED
            or record.backend_entered
            or record.reconciliation_required
        ):
            raise _lifecycle_invalid()
        self._journal = journal
        self._identity = identity
        self._durable_phase = TrainingOrchestrationPhase.DECISION_SUBMITTED
        self._journal_version = record.journal_version
        self._process_boundary_id = record.process_boundary_id
        self._approval_consumed = False
        self._backend_entered = False
        self._started = False
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "_HostFullPretrainingBackendLifecycle(<redacted>)"

    def _begin(self) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
            return True

    def _transition(
        self,
        next_phase: TrainingOrchestrationPhase,
        *,
        reason_code: str | None = None,
    ) -> None:
        transition = TrainingOrchestrationTransition(
            identity=self._identity,
            process_boundary_id=self._process_boundary_id,
            expected_phase=self._durable_phase,
            expected_version=self._journal_version,
            next_phase=next_phase,
            reason_code=reason_code,
        )
        try:
            record = self._journal.transition(transition)
        except Exception:
            raise _LifecycleJournalFailure() from None
        if (
            type(record) is not TrainingOrchestrationRecord
            or record.identity != self._identity
            or record.phase is not next_phase
        ):
            raise _LifecycleJournalFailure()
        self._durable_phase = next_phase
        self._journal_version = record.journal_version

    def _approval_was_consumed(self) -> None:
        self._approval_consumed = True
        self._transition(TrainingOrchestrationPhase.APPROVAL_CONSUMED)

    def _backend_was_entered(self) -> None:
        self._backend_entered = True
        self._transition(TrainingOrchestrationPhase.BACKEND_ENTERED)

    def _result(
        self,
        outcome: _FullPretrainingLifecycleOutcome,
        *,
        terminal_recorded: bool,
        reason_code: str | None,
    ) -> _FullPretrainingLifecycleResult:
        return _FullPretrainingLifecycleResult(
            identity=self._identity,
            outcome=outcome,
            approval_consumed=self._approval_consumed,
            backend_entered=self._backend_entered,
            terminal_recorded=terminal_recorded,
            reason_code=reason_code,
        )

    def _replay_result(self) -> _FullPretrainingLifecycleResult:
        return self._result(
            _FullPretrainingLifecycleOutcome.OUTCOME_UNKNOWN,
            terminal_recorded=False,
            reason_code="TRAINING_HOST_LIFECYCLE_REPLAY",
        )

    def _finish_success(self) -> _FullPretrainingLifecycleResult:
        try:
            self._transition(TrainingOrchestrationPhase.COMPLETED)
        except _LifecycleJournalFailure:
            return self._finish_unknown("TRAINING_HOST_TERMINAL_WRITE_FAILED")
        return self._result(
            _FullPretrainingLifecycleOutcome.SUCCEEDED,
            terminal_recorded=True,
            reason_code=None,
        )

    def _finish_failure(self, reason_code: str) -> _FullPretrainingLifecycleResult:
        stable_reason = (
            reason_code
            if _REASON_CODE_PATTERN.fullmatch(reason_code) is not None
            else "TRAINING_BACKEND_FAILED"
        )
        try:
            self._transition(
                TrainingOrchestrationPhase.FAILED,
                reason_code=stable_reason,
            )
        except (TrainingError, _LifecycleJournalFailure):
            return self._finish_unknown("TRAINING_HOST_TERMINAL_WRITE_FAILED")
        return self._result(
            _FullPretrainingLifecycleOutcome.FAILED,
            terminal_recorded=True,
            reason_code=stable_reason,
        )

    def _finish_unknown(self, reason_code: str) -> _FullPretrainingLifecycleResult:
        terminal_recorded = False
        try:
            self._transition(
                TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
                reason_code=reason_code,
            )
            terminal_recorded = True
        except (TrainingError, _LifecycleJournalFailure):
            pass
        return self._result(
            _FullPretrainingLifecycleOutcome.OUTCOME_UNKNOWN,
            terminal_recorded=terminal_recorded,
            reason_code=reason_code,
        )


def _run_host_full_pretraining(
    lifecycle: _HostFullPretrainingBackendLifecycle,
    config_path: Path,
    manifest_path: Path,
    readiness_report: dict[str, Any],
    *,
    dataset_permission: DatasetTrainingPermission,
    dataset_version_id: str,
    dataset_manifest_id: str,
    dataset_pair_fingerprint: str,
    execution_request: TrainingExecutionRequest,
    execution_approval: TrainingExecutionApproval,
) -> _FullPretrainingLifecycleResult:
    """Run the canonical backend once and return only sanitized lifecycle facts."""
    if type(lifecycle) is not _HostFullPretrainingBackendLifecycle:
        raise _lifecycle_invalid()
    if not lifecycle._begin():
        return lifecycle._replay_result()

    from .full_pretraining_backend import _run_full_pretraining

    try:
        _run_full_pretraining(
            config_path,
            manifest_path,
            readiness_report,
            dataset_permission=dataset_permission,
            dataset_version_id=dataset_version_id,
            dataset_manifest_id=dataset_manifest_id,
            dataset_pair_fingerprint=dataset_pair_fingerprint,
            execution_request=execution_request,
            execution_approval=execution_approval,
            _lifecycle=lifecycle,
        )
    except TrainingError as exc:
        return lifecycle._finish_failure(exc.code)
    except Exception:
        return lifecycle._finish_unknown("TRAINING_BACKEND_OUTCOME_UNKNOWN")
    return lifecycle._finish_success()


__all__: list[str] = []
