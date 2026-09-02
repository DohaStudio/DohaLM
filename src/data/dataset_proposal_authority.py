"""Atomic DatasetVersion proposal lifecycle authority contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from .checksums import checksum_value, sha256_bytes
from .dataset_governance import (
    DatasetVersionIdentity,
    DatasetVersionProposal,
    propose_dataset_version,
    propose_manifest_reference_dataset_version,
)

if TYPE_CHECKING:
    from .product_dataset_proposal_manifest import ManifestReferenceDatasetProposal

_SAFE_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9._:@-]{1,255}")


class DatasetProposalOutcome(str, Enum):
    """Authoritative outcome of one atomic proposal adjudication."""

    CREATED = "CREATED"
    REPLAYED = "REPLAYED"


class DatasetProposalEvidenceStatus(str, Enum):
    """Current evidence decision returned by the canonical evidence coordinator."""

    CURRENT = "CURRENT"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    INVALID = "INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class DatasetProposalAuthorityError(RuntimeError):
    """A proposal authority, evidence, replay, or conflict Gate failed closed."""

    def __init__(
        self,
        code: str,
        stage: str,
        *,
        identity: DatasetVersionIdentity | None = None,
        existing_fingerprint: str | None = None,
        incoming_fingerprint: str | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.identity = identity
        self.existing_fingerprint = existing_fingerprint
        self.incoming_fingerprint = incoming_fingerprint
        super().__init__(f"{code}:{stage}:dataset_proposal_authority")


@dataclass(frozen=True)
class DatasetProposalEvidenceDecision:
    """Safe result of current Rights/Eligibility evidence coordination."""

    status: DatasetProposalEvidenceStatus
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    authority_reference: str
    authority_version: int


@dataclass(frozen=True)
class DatasetProposalAuthorityResult:
    """Safe result returned by an atomic compare-and-create authority."""

    outcome: DatasetProposalOutcome
    proposal: DatasetVersionProposal
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    authority_reference: str
    authority_version: int


@dataclass(frozen=True, slots=True)
class DatasetProposalAuthorityRecord:
    """Validated immutable proposal loaded from the authoritative store."""

    proposal: DatasetVersionProposal
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    authority_reference: str
    authority_version: int


class DatasetProposalCurrentEvidenceAuthority(Protocol):
    """Coordinator over canonical current Rights/Eligibility authorities."""

    def evaluate_current_proposal_evidence(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
        proposed_at: datetime,
    ) -> DatasetProposalEvidenceDecision:
        """Validate all Dataset/member evidence bindings at ``proposed_at``."""


class DatasetProposalAuthority(Protocol):
    """Atomic proposal lookup and put-if-absent authority port.

    Implementations must use ``DatasetVersionIdentity`` as the lookup key. The
    lookup and create decision are one atomic operation: absent creates,
    identical canonical bytes replay, and different bytes conflict without
    overwrite. Implementations must not expose a lookup-bypass path.
    """

    def compare_and_create(
        self,
        proposal: DatasetVersionProposal,
        *,
        proposal_fingerprint: str,
    ) -> DatasetProposalAuthorityResult:
        """Atomically resolve the existing proposal or create this proposal."""

    def read_authoritative_proposal(
        self,
        identity: DatasetVersionIdentity,
    ) -> DatasetProposalAuthorityRecord:
        """Read and validate the immutable proposal for one exact identity."""


def adjudicate_dataset_version_proposal(
    payload: Mapping[str, Any],
    *,
    authority: DatasetProposalAuthority,
    current_evidence_authority: DatasetProposalCurrentEvidenceAuthority,
    proposed_at: datetime,
    manifest_submission: ManifestReferenceDatasetProposal | None = None,
) -> DatasetProposalAuthorityResult:
    """Validate, recheck current evidence, then atomically create or replay."""

    proposal_time = _require_proposed_at(proposed_at)
    if manifest_submission is None:
        proposal = propose_dataset_version(payload)
    else:
        proposal = manifest_submission.proposal
        if proposal.payload != payload:
            raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "manifest")
    fingerprint = dataset_version_proposal_fingerprint(proposal)
    if (
        manifest_submission is not None
        and manifest_submission.proposal_fingerprint != fingerprint
    ):
        raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "manifest")
    require_current_dataset_evidence(
        proposal,
        proposal_fingerprint=fingerprint,
        authority=current_evidence_authority,
        evaluated_at=proposal_time,
    )
    compare_and_create = getattr(authority, "compare_and_create", None)
    if not callable(compare_and_create):
        raise DatasetProposalAuthorityError("PROPOSAL_AUTHORITY_MISSING", "authority")
    try:
        result = compare_and_create(
            proposal,
            proposal_fingerprint=fingerprint,
        )
    except DatasetProposalAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetProposalAuthorityError(
            "PROPOSAL_AUTHORITY_UNAVAILABLE",
            "authority",
        ) from None
    _require_authority_result(result, proposal, fingerprint)
    return result


def dataset_version_proposal_fingerprint(proposal: DatasetVersionProposal) -> str:
    """Return a deterministic audit fingerprint of canonical proposal bytes."""

    if type(proposal) is not DatasetVersionProposal or proposal.status != "draft":
        raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "fingerprint")
    if proposal._authority_root is not None:
        return sha256_bytes(proposal._authority_root)
    return checksum_value(proposal.payload)


def require_current_dataset_evidence(
    proposal: DatasetVersionProposal,
    *,
    proposal_fingerprint: str,
    authority: DatasetProposalCurrentEvidenceAuthority,
    evaluated_at: datetime,
) -> None:
    """Require the existing current Rights/Eligibility decision at one time."""

    evaluation_time = _require_proposed_at(evaluated_at)
    try:
        actual_fingerprint = dataset_version_proposal_fingerprint(proposal)
    except DatasetProposalAuthorityError:
        raise DatasetProposalAuthorityError("PROPOSAL_INVALID", "evidence") from None
    if actual_fingerprint != proposal_fingerprint:
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_FINGERPRINT_MISMATCH",
            "evidence",
            identity=proposal.identity,
            existing_fingerprint=actual_fingerprint,
            incoming_fingerprint=proposal_fingerprint,
        )
    _require_current_evidence(
        proposal,
        fingerprint=proposal_fingerprint,
        authority=authority,
        proposed_at=evaluation_time,
    )


def validate_dataset_proposal_authority_record(
    record: object,
    *,
    expected_identity: DatasetVersionIdentity,
    expected_proposal_fingerprint: str,
) -> DatasetProposalAuthorityRecord:
    """Validate an authoritative proposal read against its exact lookup binding."""

    if type(record) is not DatasetProposalAuthorityRecord:
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_CORRUPT",
            "read",
        )
    try:
        if type(record.proposal) is not DatasetVersionProposal:
            raise TypeError
        if record.proposal._authority_root is None:
            proposal = propose_dataset_version(record.proposal.payload)
        else:
            proposal = propose_manifest_reference_dataset_version(
                record.proposal.payload,
                authority_root=record.proposal.authority_root,
            )
        actual_fingerprint = dataset_version_proposal_fingerprint(proposal)
    except Exception:  # noqa: BLE001 - untrusted record access must fail closed
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_CORRUPT",
            "read",
        ) from None
    if (
        record.proposal._canonical_payload != proposal._canonical_payload
        or record.proposal._authority_root != proposal._authority_root
    ):
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_CORRUPT",
            "read",
            identity=expected_identity,
        )
    if record.identity != expected_identity or proposal.identity != expected_identity:
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_IDENTITY_MISMATCH",
            "read",
            identity=expected_identity,
        )
    if (
        record.proposal_fingerprint != expected_proposal_fingerprint
        or actual_fingerprint != expected_proposal_fingerprint
    ):
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_FINGERPRINT_MISMATCH",
            "read",
            identity=expected_identity,
            existing_fingerprint=record.proposal_fingerprint,
            incoming_fingerprint=expected_proposal_fingerprint,
        )
    if not _valid_authority_metadata(
        record.authority_reference,
        record.authority_version,
    ):
        raise DatasetProposalAuthorityError(
            "DATASET_PROPOSAL_AUTHORITY_CORRUPT",
            "read",
            identity=expected_identity,
        )
    return record


def _require_current_evidence(
    proposal: DatasetVersionProposal,
    *,
    fingerprint: str,
    authority: DatasetProposalCurrentEvidenceAuthority,
    proposed_at: datetime,
) -> None:
    evaluate = getattr(authority, "evaluate_current_proposal_evidence", None)
    if not callable(evaluate):
        raise DatasetProposalAuthorityError(
            "PROPOSAL_EVIDENCE_AUTHORITY_MISSING",
            "evidence",
        )
    try:
        decision = evaluate(
            proposal,
            proposal_fingerprint=fingerprint,
            proposed_at=proposed_at,
        )
    except DatasetProposalAuthorityError:
        raise
    except Exception:  # noqa: BLE001 - authority failures cross a sanitized boundary
        raise DatasetProposalAuthorityError(
            "PROPOSAL_EVIDENCE_AUTHORITY_UNAVAILABLE",
            "evidence",
        ) from None
    if type(decision) is not DatasetProposalEvidenceDecision:
        raise DatasetProposalAuthorityError(
            "PROPOSAL_EVIDENCE_RESULT_INVALID",
            "evidence",
        )
    if (
        decision.identity != proposal.identity
        or decision.proposal_fingerprint != fingerprint
        or not _valid_authority_metadata(
            decision.authority_reference,
            decision.authority_version,
        )
    ):
        raise DatasetProposalAuthorityError(
            "PROPOSAL_EVIDENCE_IDENTITY_MISMATCH",
            "evidence",
        )
    if decision.status is not DatasetProposalEvidenceStatus.CURRENT:
        code = {
            DatasetProposalEvidenceStatus.MISSING: "PROPOSAL_EVIDENCE_MISSING",
            DatasetProposalEvidenceStatus.EXPIRED: "PROPOSAL_EVIDENCE_EXPIRED",
            DatasetProposalEvidenceStatus.REVOKED: "PROPOSAL_EVIDENCE_REVOKED",
            DatasetProposalEvidenceStatus.INVALID: "PROPOSAL_EVIDENCE_INVALID",
            DatasetProposalEvidenceStatus.IDENTITY_MISMATCH: (
                "PROPOSAL_EVIDENCE_IDENTITY_MISMATCH"
            ),
        }.get(decision.status, "PROPOSAL_EVIDENCE_RESULT_INVALID")
        raise DatasetProposalAuthorityError(code, "evidence")


def _require_authority_result(
    result: object,
    incoming: DatasetVersionProposal,
    fingerprint: str,
) -> None:
    if (
        type(result) is not DatasetProposalAuthorityResult
        or not isinstance(result.outcome, DatasetProposalOutcome)
        or type(result.proposal) is not DatasetVersionProposal
        or result.proposal.status != "draft"
        or result.identity != incoming.identity
        or result.proposal.identity != incoming.identity
        or result.proposal_fingerprint != fingerprint
        or dataset_version_proposal_fingerprint(result.proposal) != fingerprint
        or not _valid_authority_metadata(
            result.authority_reference,
            result.authority_version,
        )
    ):
        raise DatasetProposalAuthorityError(
            "PROPOSAL_AUTHORITY_RESULT_INVALID",
            "authority",
        )


def _require_proposed_at(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DatasetProposalAuthorityError("PROPOSED_AT_INVALID", "timestamp")
    return value


def _valid_authority_metadata(reference: object, version: object) -> bool:
    return (
        isinstance(reference, str)
        and _SAFE_REFERENCE.fullmatch(reference) is not None
        and isinstance(version, int)
        and not isinstance(version, bool)
        and version >= 1
    )


__all__ = [
    "DatasetProposalAuthority",
    "DatasetProposalAuthorityError",
    "DatasetProposalAuthorityRecord",
    "DatasetProposalAuthorityResult",
    "DatasetProposalCurrentEvidenceAuthority",
    "DatasetProposalEvidenceDecision",
    "DatasetProposalEvidenceStatus",
    "DatasetProposalOutcome",
    "adjudicate_dataset_version_proposal",
    "dataset_version_proposal_fingerprint",
    "require_current_dataset_evidence",
    "validate_dataset_proposal_authority_record",
]
