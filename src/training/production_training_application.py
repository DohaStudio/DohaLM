"""Non-CLI production Training application entrypoint and activation dry-run.

The entrypoint accepts only a durable intent identity plus the observed source
commit.  Construction-bound authorities and composition dependencies resolve
everything else.  A successful call returns immutable, transient readiness
evidence and stops before Host bootstrap, journal claim, or backend execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from src.data.checksums import checksum_value

from .errors import TrainingError
from .execution_approval import TrainingExecutionRequest
from .production_host_foundation import (
    ProductionTrainingHostIntent,
    _is_canonical_timestamp,
)
from .production_intent_authority import (
    TrainingIntentContinuation,
    TrainingIntentValidationPort,
    ValidatedTrainingIntent,
    _valid_fingerprint,
    _valid_reference,
    _valid_uuid,
    validate_intent_for_execution,
)
from .production_full_pretraining_host import (
    ProductionTrainingHostResult,
)


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _host_matches(
    readiness: ProductionTrainingCompositionReadiness,
    validated: ValidatedTrainingIntent,
) -> bool:
    host = readiness.host_intent
    request = validated.execution_request
    submission = validated.intent.submission
    return (
        readiness.execution_request == request
        and host.action == request.action
        and host.execution_mode == request.execution_mode
        and host.dataset_version_reference
        == f"dataset-version:{submission.dataset_version_authority_id}"
        and host.dataset_manifest_reference
        == f"dataset-manifest:{submission.dataset_manifest_authority_id}"
        and host.expected_dataset_pair_fingerprint == request.dataset_pair_fingerprint
        and host.training_config_reference == f"config:{submission.config_authority_id}"
        and host.expected_config_fingerprint == request.config_fingerprint
        and host.readiness_evidence_reference
        == f"readiness:{submission.readiness_authority_id}"
        and host.expected_readiness_fingerprint == request.readiness_fingerprint
        and host.run_id == request.run_id
        and host.output_logical_root == request.output_logical_root
        and host.decision_evidence_reference == validated.binding.evidence_reference
    )


@dataclass(frozen=True, slots=True, repr=False)
class ProductionTrainingApplicationCommand:
    """Transport-independent input; no caller-owned Training overrides."""

    intent_id: str
    expected_source_commit: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not _valid_uuid(self.intent_id)
            or type(self.expected_source_commit) is not str
            or len(self.expected_source_commit) != 40
            or any(
                char not in "0123456789abcdef" for char in self.expected_source_commit
            )
        ):
            raise _error(
                "TRAINING_APPLICATION_COMMAND_INVALID",
                "A valid durable intent identity and observed source commit are required.",
            )

    def __repr__(self) -> str:
        return "ProductionTrainingApplicationCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ProductionTrainingCompositionReadiness:
    """Read-only C3 facts needed to construct an activation plan."""

    host_intent: ProductionTrainingHostIntent
    execution_request: TrainingExecutionRequest
    provider: str
    process_boundary_id: str
    prerequisite_policy_reference: str
    decision_policy_reference: str
    prerequisite_evaluated_at: str
    decision_issued_at: str
    run_unused: bool
    output_available: bool
    continuation_verified: bool
    host_contract_compatible: bool
    mutation_count: int

    def __post_init__(self) -> None:
        references = (
            self.provider,
            self.process_boundary_id,
            self.prerequisite_policy_reference,
            self.decision_policy_reference,
        )
        if (
            type(self.host_intent) is not ProductionTrainingHostIntent
            or type(self.execution_request) is not TrainingExecutionRequest
            or not all(_valid_reference(value) for value in references)
            or not _is_canonical_timestamp(self.prerequisite_evaluated_at)
            or not _is_canonical_timestamp(self.decision_issued_at)
            or self.run_unused is not True
            or self.output_available is not True
            or self.continuation_verified is not True
            or self.host_contract_compatible is not True
            or self.mutation_count != 0
        ):
            raise _error(
                "TRAINING_APPLICATION_COMPOSITION_INVALID",
                "Exact read-only production composition readiness is required.",
            )

    def __repr__(self) -> str:
        return "ProductionTrainingCompositionReadiness(<redacted>)"


class ProductionTrainingActivationComposition(Protocol):
    def preflight(self) -> object: ...

    def prepare_activation(
        self, validated: ValidatedTrainingIntent
    ) -> ProductionTrainingCompositionReadiness: ...

    def activate(
        self, readiness: ProductionTrainingCompositionReadiness
    ) -> ProductionTrainingHostResult: ...

    def shutdown(self) -> None: ...


class ProductionTrainingActivationCompositionFactory(Protocol):
    def compose(self) -> ProductionTrainingActivationComposition: ...


@dataclass(frozen=True, slots=True, repr=False)
class ProductionTrainingActivationPlan:
    """Immutable execution-adjacent projection; never a durable authority row."""

    intent_id: str
    intent_fingerprint: str
    submitter_authority_id: str
    execution_request: TrainingExecutionRequest
    decision_authority_id: str
    authorization_id: str
    issuer_authority_id: str
    approver_authority_id: str
    host_intent: ProductionTrainingHostIntent
    provider: str
    process_boundary_id: str
    prerequisite_policy_reference: str
    decision_policy_reference: str
    prerequisite_evaluated_at: str
    decision_issued_at: str
    continuation: TrainingIntentContinuation | None
    schema_version: int = 1
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        authority_ids = (
            self.intent_id,
            self.submitter_authority_id,
            self.decision_authority_id,
            self.issuer_authority_id,
            self.approver_authority_id,
        )
        references = (
            self.authorization_id,
            self.provider,
            self.process_boundary_id,
            self.prerequisite_policy_reference,
            self.decision_policy_reference,
        )
        if (
            self.schema_version != 1
            or not all(_valid_uuid(value) for value in authority_ids)
            or not _valid_fingerprint(self.intent_fingerprint)
            or type(self.execution_request) is not TrainingExecutionRequest
            or type(self.host_intent) is not ProductionTrainingHostIntent
            or not all(_valid_reference(value) for value in references)
            or not _is_canonical_timestamp(self.prerequisite_evaluated_at)
            or not _is_canonical_timestamp(self.decision_issued_at)
            or (
                self.continuation is not None
                and type(self.continuation) is not TrainingIntentContinuation
            )
        ):
            raise _error(
                "TRAINING_APPLICATION_PLAN_INVALID",
                "A valid immutable production Training activation plan is required.",
            )
        request = self.execution_request
        continuation = self.continuation
        payload = {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "intent_fingerprint": self.intent_fingerprint,
            "submitter_authority_id": self.submitter_authority_id,
            "request_fingerprint": request.request_fingerprint,
            "run_id": request.run_id,
            "execution_mode": request.execution_mode,
            "source_commit": request.source_commit,
            "output_logical_root": request.output_logical_root,
            "decision_authority_id": self.decision_authority_id,
            "authorization_id": self.authorization_id,
            "issuer_authority_id": self.issuer_authority_id,
            "approver_authority_id": self.approver_authority_id,
            "provider": self.provider,
            "process_boundary_id": self.process_boundary_id,
            "prerequisite_policy_reference": self.prerequisite_policy_reference,
            "decision_policy_reference": self.decision_policy_reference,
            "prerequisite_evaluated_at": self.prerequisite_evaluated_at,
            "decision_issued_at": self.decision_issued_at,
            "continuation": (
                None
                if continuation is None
                else {
                    "predecessor_run_id": continuation.predecessor_run_id,
                    "checkpoint_reference": continuation.checkpoint_reference,
                    "source_step": continuation.source_step,
                    "target_cumulative_steps": continuation.target_cumulative_steps,
                }
            ),
        }
        object.__setattr__(self, "plan_fingerprint", checksum_value(payload))

    def __repr__(self) -> str:
        return "ProductionTrainingActivationPlan(<redacted>)"


class ProductionTrainingDryRunStatus(str, Enum):
    READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION"


@dataclass(frozen=True, slots=True, repr=False)
class ProductionTrainingDryRunResult:
    status: ProductionTrainingDryRunStatus
    plan: ProductionTrainingActivationPlan
    currentness_must_be_revalidated: bool = True

    def __post_init__(self) -> None:
        if (
            self.status is not ProductionTrainingDryRunStatus.READY_FOR_ACTIVATION
            or type(self.plan) is not ProductionTrainingActivationPlan
            or self.currentness_must_be_revalidated is not True
        ):
            raise _error(
                "TRAINING_APPLICATION_RESULT_INVALID",
                "Valid transient activation readiness evidence is required.",
            )

    def __repr__(self) -> str:
        return "ProductionTrainingDryRunResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ProductionTrainingActivationResult:
    """Sanitized application result for one Host-owned activation attempt."""

    plan: ProductionTrainingActivationPlan
    execution: ProductionTrainingHostResult

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not ProductionTrainingActivationPlan
            or type(self.execution) is not ProductionTrainingHostResult
            or self.execution.identity.run_id != self.plan.execution_request.run_id
            or self.execution.identity.request_fingerprint
            != self.plan.execution_request.request_fingerprint
        ):
            raise _error(
                "TRAINING_APPLICATION_RESULT_INVALID",
                "The Host result must match the exact approved activation plan.",
            )

    def __repr__(self) -> str:
        return "ProductionTrainingActivationResult(<redacted>)"


class ProductionTrainingApplicationEntrypoint:
    """Construction-bound non-CLI application service for dry-run and activation."""

    def __init__(
        self,
        authority: TrainingIntentValidationPort,
        compositions: ProductionTrainingActivationCompositionFactory,
    ) -> None:
        self._authority = authority
        self._compositions = compositions

    def dry_run(
        self, command: ProductionTrainingApplicationCommand
    ) -> ProductionTrainingDryRunResult:
        validated = self._validated(command)
        composition = self._compositions.compose()
        try:
            readiness = composition.prepare_activation(validated)
            plan = self._plan(validated, readiness)
        finally:
            composition.shutdown()
        return ProductionTrainingDryRunResult(
            ProductionTrainingDryRunStatus.READY_FOR_ACTIVATION,
            plan,
        )

    def activate(
        self, command: ProductionTrainingApplicationCommand
    ) -> ProductionTrainingActivationResult:
        """Revalidate, reserve only through Host, and execute one approved intent."""

        validated = self._validated(command)
        composition = self._compositions.compose()
        try:
            composition.preflight()
            readiness = composition.prepare_activation(validated)
            plan = self._plan(validated, readiness)
            self._authority.verify_current_evidence(validated.intent)
            execution = composition.activate(readiness)
            return ProductionTrainingActivationResult(plan=plan, execution=execution)
        finally:
            composition.shutdown()

    def _validated(
        self, command: ProductionTrainingApplicationCommand
    ) -> ValidatedTrainingIntent:
        if type(command) is not ProductionTrainingApplicationCommand:
            raise _error(
                "TRAINING_APPLICATION_COMMAND_INVALID",
                "A typed production Training application command is required.",
            )
        return validate_intent_for_execution(
            command.intent_id,
            command.expected_source_commit,
            self._authority,
        )

    @staticmethod
    def _plan(
        validated: ValidatedTrainingIntent,
        readiness: ProductionTrainingCompositionReadiness,
    ) -> ProductionTrainingActivationPlan:
        if type(
            readiness
        ) is not ProductionTrainingCompositionReadiness or not _host_matches(
            readiness, validated
        ):
            raise _error(
                "TRAINING_APPLICATION_HOST_INCOMPATIBLE",
                "The activation plan is incompatible with the existing Host contract.",
            )
        intent = validated.intent
        binding = validated.binding
        plan = ProductionTrainingActivationPlan(
            intent_id=intent.intent_id,
            intent_fingerprint=intent.intent_fingerprint,
            submitter_authority_id=intent.submitter_authority_id,
            execution_request=validated.execution_request,
            decision_authority_id=binding.decision_authority_id,
            authorization_id=binding.authorization_id,
            issuer_authority_id=binding.issuer_authority_id,
            approver_authority_id=binding.approver_authority_id,
            host_intent=readiness.host_intent,
            provider=readiness.provider,
            process_boundary_id=readiness.process_boundary_id,
            prerequisite_policy_reference=readiness.prerequisite_policy_reference,
            decision_policy_reference=readiness.decision_policy_reference,
            prerequisite_evaluated_at=readiness.prerequisite_evaluated_at,
            decision_issued_at=readiness.decision_issued_at,
            continuation=intent.submission.continuation,
        )
        return plan


__all__ = [
    "ProductionTrainingActivationComposition",
    "ProductionTrainingActivationCompositionFactory",
    "ProductionTrainingActivationPlan",
    "ProductionTrainingActivationResult",
    "ProductionTrainingApplicationCommand",
    "ProductionTrainingApplicationEntrypoint",
    "ProductionTrainingCompositionReadiness",
    "ProductionTrainingDryRunResult",
    "ProductionTrainingDryRunStatus",
]
