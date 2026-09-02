"""Typed production authority provisioning contracts and orchestration.

These contracts deliberately expose neither SQL nor generic CRUD.  Every command
describes one immutable authority family and every result is a redacted, frozen
identity projection suitable for trusted application composition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from src.data.checksums import sha256_bytes

from .errors import TrainingError
from .execution_approval import TrainingExecutionRequest
from .execution_issuer import TrainingExecutionIssuerDecisionValue
from .production_intent_authority import TrainingIntentSubmitterAuthorityRecord

_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _reference(value: object) -> bool:
    return type(value) is str and _REFERENCE.fullmatch(value) is not None


def _fingerprint(value: object) -> bool:
    return type(value) is str and _FINGERPRINT.fullmatch(value) is not None


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _error(
            "PRODUCTION_AUTHORITY_INPUT_INVALID",
            "Timezone-aware production authority timestamps are required.",
        )
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityProvisioningIdentity:
    authority_id: str
    domain_key: str
    payload_fingerprint: str
    state: str
    projection_version: int

    def __post_init__(self) -> None:
        if (
            not _uuid(self.authority_id)
            or not _reference(self.domain_key)
            or not _fingerprint(self.payload_fingerprint)
            or self.state != "current"
            or type(self.projection_version) is not int
            or self.projection_version < 1
        ):
            raise _error(
                "PRODUCTION_AUTHORITY_RESULT_INVALID",
                "A current immutable production authority result is required.",
            )

    def __repr__(self) -> str:
        return "AuthorityProvisioningIdentity(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class PrincipalProvisionCommand:
    authority_id: str
    domain_key: str
    payload: bytes
    source_commit: str
    valid_from: datetime
    valid_until: datetime | None
    principal_reference: str
    event_id: str
    correlation_reference: str
    evidence_reference: str

    def __post_init__(self) -> None:
        if (
            not _uuid(self.authority_id)
            or not _uuid(self.event_id)
            or not _reference(self.domain_key)
            or type(self.payload) is not bytes
            or not self.payload
            or type(self.source_commit) is not str
            or _COMMIT.fullmatch(self.source_commit) is None
            or not _reference(self.principal_reference)
            or not _reference(self.correlation_reference)
            or not _reference(self.evidence_reference)
        ):
            raise _error(
                "PRODUCTION_AUTHORITY_INPUT_INVALID",
                "Valid immutable principal authority material is required.",
            )
        object.__setattr__(self, "valid_from", _utc(self.valid_from))
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _utc(self.valid_until))
            if self.valid_until <= self.valid_from:
                raise _error(
                    "PRODUCTION_AUTHORITY_INPUT_INVALID",
                    "Principal validity must be ordered.",
                )

    @property
    def payload_fingerprint(self) -> str:
        return sha256_bytes(self.payload)

    def __repr__(self) -> str:
        return "PrincipalProvisionCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ConfigAuthorityProvisionCommand:
    authority_id: str
    domain_key: str
    canonical_payload: bytes
    source_commit: str
    valid_from: datetime
    valid_until: datetime | None
    event_id: str
    correlation_reference: str
    evidence_reference: str

    def __post_init__(self) -> None:
        PrincipalProvisionCommand(
            authority_id=self.authority_id,
            domain_key=self.domain_key,
            payload=self.canonical_payload,
            source_commit=self.source_commit,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            principal_reference="full-pretraining",
            event_id=self.event_id,
            correlation_reference=self.correlation_reference,
            evidence_reference=self.evidence_reference,
        )

    @property
    def payload_fingerprint(self) -> str:
        return sha256_bytes(self.canonical_payload)

    def __repr__(self) -> str:
        return "ConfigAuthorityProvisionCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ReadinessAuthorityProvisionCommand:
    authority_id: str
    domain_key: str
    canonical_payload: bytes
    source_commit: str
    dataset_pair_fingerprint: str
    config_fingerprint: str
    evaluated_at: datetime
    valid_from: datetime
    valid_until: datetime
    event_id: str
    correlation_reference: str
    evidence_reference: str

    def __post_init__(self) -> None:
        ConfigAuthorityProvisionCommand(
            authority_id=self.authority_id,
            domain_key=self.domain_key,
            canonical_payload=self.canonical_payload,
            source_commit=self.source_commit,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            event_id=self.event_id,
            correlation_reference=self.correlation_reference,
            evidence_reference=self.evidence_reference,
        )
        if not _fingerprint(self.dataset_pair_fingerprint) or not _fingerprint(
            self.config_fingerprint
        ):
            raise _error(
                "PRODUCTION_AUTHORITY_INPUT_INVALID",
                "Exact Dataset and config readiness bindings are required.",
            )
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at))
        if not self.valid_from <= self.evaluated_at < self.valid_until:
            raise _error(
                "PRODUCTION_AUTHORITY_INPUT_INVALID",
                "Readiness evaluation must fall within authority validity.",
            )

    @property
    def payload_fingerprint(self) -> str:
        return sha256_bytes(self.canonical_payload)

    def __repr__(self) -> str:
        return "ReadinessAuthorityProvisionCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DatasetAuthorityRegistrationCommand:
    version_authority_id: str
    manifest_authority_id: str
    pair_authority_id: str
    version_domain_key: str
    manifest_domain_key: str
    pair_domain_key: str
    version_payload: bytes
    manifest_payload: bytes
    pair_payload: bytes
    dataset_version_id: str
    dataset_manifest_id: str
    pair_fingerprint: str
    source_commit: str
    publication_scenario: str
    eligibility_reference: str
    source_lineage_reference: str
    valid_from: datetime
    valid_until: datetime | None
    version_event_id: str
    manifest_event_id: str
    pair_event_id: str
    correlation_reference: str

    def __post_init__(self) -> None:
        if (
            not all(
                _uuid(value)
                for value in (
                    self.version_authority_id,
                    self.manifest_authority_id,
                    self.pair_authority_id,
                    self.version_event_id,
                    self.manifest_event_id,
                    self.pair_event_id,
                )
            )
            or len(
                {
                    self.version_authority_id,
                    self.manifest_authority_id,
                    self.pair_authority_id,
                }
            )
            != 3
            or not all(
                _reference(value)
                for value in (
                    self.version_domain_key,
                    self.manifest_domain_key,
                    self.pair_domain_key,
                    self.dataset_version_id,
                    self.dataset_manifest_id,
                    self.publication_scenario,
                    self.eligibility_reference,
                    self.source_lineage_reference,
                    self.correlation_reference,
                )
            )
            or not all(
                type(value) is bytes and bool(value)
                for value in (
                    self.version_payload,
                    self.manifest_payload,
                    self.pair_payload,
                )
            )
            or not _fingerprint(self.pair_fingerprint)
            or _COMMIT.fullmatch(self.source_commit) is None
        ):
            raise _error(
                "PRODUCTION_DATASET_REGISTRATION_INVALID",
                "An exact typed Dataset publication registration is required.",
            )
        object.__setattr__(self, "valid_from", _utc(self.valid_from))
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _utc(self.valid_until))
            if self.valid_until <= self.valid_from:
                raise _error(
                    "PRODUCTION_DATASET_REGISTRATION_INVALID",
                    "Dataset authority validity must be ordered.",
                )

    def __repr__(self) -> str:
        return "DatasetAuthorityRegistrationCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DatasetAuthorityRegistrationResult:
    version: AuthorityProvisioningIdentity
    manifest: AuthorityProvisioningIdentity
    pair: AuthorityProvisioningIdentity
    dataset_version_id: str
    dataset_manifest_id: str
    pair_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not _reference(self.dataset_version_id)
            or not _reference(self.dataset_manifest_id)
            or not _fingerprint(self.pair_fingerprint)
            or len(
                {
                    self.version.authority_id,
                    self.manifest.authority_id,
                    self.pair.authority_id,
                }
            )
            != 3
        ):
            raise _error(
                "PRODUCTION_DATASET_REGISTRATION_INVALID",
                "A complete atomic Dataset registration result is required.",
            )

    def __repr__(self) -> str:
        return "DatasetAuthorityRegistrationResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DatasetPairReplacementCommand:
    previous_pair_authority_id: str
    expected_previous_projection_version: int
    version_authority_id: str
    manifest_authority_id: str
    pair_authority_id: str
    pair_domain_key: str
    version_payload: bytes
    manifest_payload: bytes
    pair_payload: bytes
    dataset_version_id: str
    dataset_manifest_id: str
    pair_fingerprint: str
    source_commit: str
    publication_scenario: str
    valid_until: datetime | None
    pair_event_id: str
    supersede_event_id: str
    correlation_reference: str
    evidence_reference: str

    def __post_init__(self) -> None:
        if (
            not all(
                _uuid(value)
                for value in (
                    self.previous_pair_authority_id,
                    self.version_authority_id,
                    self.manifest_authority_id,
                    self.pair_authority_id,
                    self.pair_event_id,
                    self.supersede_event_id,
                )
            )
            or len(
                {
                    self.previous_pair_authority_id,
                    self.version_authority_id,
                    self.manifest_authority_id,
                    self.pair_authority_id,
                }
            )
            != 4
            or type(self.expected_previous_projection_version) is not int
            or self.expected_previous_projection_version < 1
            or not all(
                _reference(value)
                for value in (
                    self.pair_domain_key,
                    self.dataset_version_id,
                    self.dataset_manifest_id,
                    self.publication_scenario,
                    self.correlation_reference,
                    self.evidence_reference,
                )
            )
            or not all(
                type(value) is bytes and bool(value)
                for value in (
                    self.version_payload,
                    self.manifest_payload,
                    self.pair_payload,
                )
            )
            or not _fingerprint(self.pair_fingerprint)
            or _COMMIT.fullmatch(self.source_commit) is None
        ):
            raise _error(
                "PRODUCTION_DATASET_PAIR_REPLACEMENT_INVALID",
                "An exact immutable Dataset pair replacement is required.",
            )
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _utc(self.valid_until))

    @property
    def pair_payload_fingerprint(self) -> str:
        return sha256_bytes(self.pair_payload)

    def __repr__(self) -> str:
        return "DatasetPairReplacementCommand(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DatasetPairReplacementResult:
    version: AuthorityProvisioningIdentity
    manifest: AuthorityProvisioningIdentity
    pair: AuthorityProvisioningIdentity
    previous_pair_authority_id: str
    previous_pair_state: str
    previous_pair_projection_version: int
    pair_fingerprint: str
    pair_schema_version: int

    def __post_init__(self) -> None:
        if (
            not _uuid(self.previous_pair_authority_id)
            or self.previous_pair_state != "superseded"
            or type(self.previous_pair_projection_version) is not int
            or self.previous_pair_projection_version < 2
            or not _fingerprint(self.pair_fingerprint)
            or self.pair_schema_version != 2
        ):
            raise _error(
                "PRODUCTION_DATASET_PAIR_REPLACEMENT_INVALID",
                "A superseded legacy pair and current v2 replacement are required.",
            )

    def __repr__(self) -> str:
        return "DatasetPairReplacementResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DecisionAuthorityProvisionCommand:
    authority_id: str
    domain_key: str
    canonical_payload: bytes
    source_commit: str
    request: TrainingExecutionRequest
    decision: TrainingExecutionIssuerDecisionValue
    authorization_id: str
    issuer_authority_id: str
    issuer_id: str
    approver_authority_id: str
    approver_reference: str
    evidence_reference: str
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    event_id: str
    correlation_reference: str

    def __post_init__(self) -> None:
        if (
            not all(
                _uuid(value)
                for value in (
                    self.authority_id,
                    self.issuer_authority_id,
                    self.approver_authority_id,
                    self.event_id,
                )
            )
            or self.issuer_authority_id == self.approver_authority_id
            or not all(
                _reference(value)
                for value in (
                    self.domain_key,
                    self.authorization_id,
                    self.issuer_id,
                    self.approver_reference,
                    self.evidence_reference,
                    self.correlation_reference,
                )
            )
            or not self.evidence_reference.startswith("decision:")
            or not _uuid(self.evidence_reference.removeprefix("decision:"))
            or type(self.canonical_payload) is not bytes
            or not self.canonical_payload
            or _COMMIT.fullmatch(self.source_commit) is None
            or type(self.request) is not TrainingExecutionRequest
            or self.request.source_commit != self.source_commit
            or type(self.decision) is not TrainingExecutionIssuerDecisionValue
        ):
            raise _error(
                "PRODUCTION_DECISION_AUTHORITY_INVALID",
                "A canonical decision with distinct issuer and approver is required.",
            )
        object.__setattr__(self, "valid_from", _utc(self.valid_from))
        object.__setattr__(self, "valid_until", _utc(self.valid_until))
        object.__setattr__(self, "issued_at", _utc(self.issued_at))
        if not self.valid_from <= self.issued_at < self.valid_until:
            raise _error(
                "PRODUCTION_DECISION_AUTHORITY_INVALID",
                "Decision issuance must fall within validity.",
            )

    @property
    def payload_fingerprint(self) -> str:
        return sha256_bytes(self.canonical_payload)

    def __repr__(self) -> str:
        return "DecisionAuthorityProvisionCommand(<redacted>)"


class ProductionAuthorityProvisioningPort(Protocol):
    def provision_issuer(
        self, command: PrincipalProvisionCommand
    ) -> AuthorityProvisioningIdentity: ...

    def provision_approver(
        self, command: PrincipalProvisionCommand
    ) -> AuthorityProvisioningIdentity: ...

    def provision_config(
        self, command: ConfigAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity: ...

    def provision_readiness(
        self, command: ReadinessAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity: ...

    def register_dataset_publication(
        self, command: DatasetAuthorityRegistrationCommand
    ) -> DatasetAuthorityRegistrationResult: ...

    def replace_dataset_pair(
        self, command: DatasetPairReplacementCommand
    ) -> DatasetPairReplacementResult: ...

    def create_decision(
        self, command: DecisionAuthorityProvisionCommand
    ) -> AuthorityProvisioningIdentity: ...


class SubmitterProvisioningPort(Protocol):
    def provision_submitter(
        self, **values: object
    ) -> TrainingIntentSubmitterAuthorityRecord: ...


@dataclass(frozen=True, slots=True, repr=False)
class ProductionAuthorityProvisioningPackage:
    submitter: TrainingIntentSubmitterAuthorityRecord
    issuer: AuthorityProvisioningIdentity
    approver: AuthorityProvisioningIdentity
    dataset: DatasetAuthorityRegistrationResult
    config: AuthorityProvisioningIdentity
    readiness: AuthorityProvisioningIdentity

    def __post_init__(self) -> None:
        identities = {
            self.submitter.authority_id,
            self.issuer.authority_id,
            self.approver.authority_id,
        }
        if len(identities) != 3 or not self.submitter.current:
            raise _error(
                "PRODUCTION_AUTHORITY_ROLE_COLLISION",
                "Submitter, issuer, and approver authorities must be current and distinct.",
            )

    def __repr__(self) -> str:
        return "ProductionAuthorityProvisioningPackage(<redacted>)"


class ProductionTrainingAuthorityProvisioner:
    """Replay-safe staged coordinator; each family retains its own transaction."""

    def __init__(
        self,
        *,
        submitters: SubmitterProvisioningPort,
        authorities: ProductionAuthorityProvisioningPort,
    ) -> None:
        self._submitters = submitters
        self._authorities = authorities

    def provision(
        self,
        *,
        submitter_values: dict[str, object],
        issuer: PrincipalProvisionCommand,
        approver: PrincipalProvisionCommand,
        dataset: DatasetAuthorityRegistrationCommand,
        config: ConfigAuthorityProvisionCommand,
        readiness: ReadinessAuthorityProvisionCommand,
    ) -> ProductionAuthorityProvisioningPackage:
        requested_ids = {
            str(submitter_values.get("authority_id")),
            issuer.authority_id,
            approver.authority_id,
        }
        if len(requested_ids) != 3:
            raise _error(
                "PRODUCTION_AUTHORITY_ROLE_COLLISION",
                "Requested role authority UUIDs must be pairwise distinct.",
            )
        submitter = self._submitters.provision_submitter(**submitter_values)
        issuer_result = self._authorities.provision_issuer(issuer)
        approver_result = self._authorities.provision_approver(approver)
        dataset_result = self._authorities.register_dataset_publication(dataset)
        config_result = self._authorities.provision_config(config)
        readiness_result = self._authorities.provision_readiness(readiness)
        return ProductionAuthorityProvisioningPackage(
            submitter=submitter,
            issuer=issuer_result,
            approver=approver_result,
            dataset=dataset_result,
            config=config_result,
            readiness=readiness_result,
        )


__all__ = [
    "AuthorityProvisioningIdentity",
    "ConfigAuthorityProvisionCommand",
    "DatasetAuthorityRegistrationCommand",
    "DatasetAuthorityRegistrationResult",
    "DatasetPairReplacementCommand",
    "DatasetPairReplacementResult",
    "DecisionAuthorityProvisionCommand",
    "PrincipalProvisionCommand",
    "ProductionAuthorityProvisioningPackage",
    "ProductionAuthorityProvisioningPort",
    "ProductionTrainingAuthorityProvisioner",
    "ReadinessAuthorityProvisionCommand",
]
