"""Explicit, side-effect-free review Gate for validated LearningCandidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from .common_dataset_contracts import (
    COMMON_CONTRACT_AUTHORITY_COMMIT,
    COMMON_CONTRACT_PACKAGE_VERSION,
    COMMON_CONTRACT_POLICY_VERSION,
    CommonContractRuntimeError,
    CommonDatasetValidationError,
    validate_rights_metadata,
    validate_training_eligibility,
)
from .learning_candidate_consumer import (
    CommonObjectReference,
    ProducerIdentity,
    ValidatedLearningCandidate,
)

_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_UNSUPPORTED_VERSION_CODES = frozenset(
    {
        "DEPRECATED_SCHEMA_VERSION",
        "INVALID_SCHEMA_VERSION",
        "UNSUPPORTED_SCHEMA_VERSION",
    }
)


class ReviewDecision(str, Enum):
    """Explicit reviewer intent and final local review state."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ReviewReason(str, Enum):
    """Sanitized, audit-oriented local reason taxonomy."""

    ACCEPTED_VALID_CURRENT_ELIGIBILITY = "ACCEPTED_VALID_CURRENT_ELIGIBILITY"
    REJECTED_BY_REVIEWER = "REJECTED_BY_REVIEWER"
    REJECTED_RIGHTS_EXPIRED = "REJECTED_RIGHTS_EXPIRED"
    REJECTED_RIGHTS_REVOKED = "REJECTED_RIGHTS_REVOKED"
    REJECTED_RIGHTS_INVALID = "REJECTED_RIGHTS_INVALID"
    REJECTED_ELIGIBILITY_EXPIRED = "REJECTED_ELIGIBILITY_EXPIRED"
    REJECTED_ELIGIBILITY_REVOKED = "REJECTED_ELIGIBILITY_REVOKED"
    REJECTED_ELIGIBILITY_INVALID = "REJECTED_ELIGIBILITY_INVALID"
    NEEDS_REVIEW_REQUESTED = "NEEDS_REVIEW_REQUESTED"
    NEEDS_REVIEW_EVIDENCE_UNRESOLVED = "NEEDS_REVIEW_EVIDENCE_UNRESOLVED"


class LearningCandidateReviewError(ValueError):
    """The review request or current authority boundary failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:learning_candidate_review")


class LearningCandidateReviewAuthority(Protocol):
    """Current-state lookup port; implementations remain outside this boundary."""

    def resolve_rights_metadata(
        self, rights_metadata_id: str, *, checked_at: datetime
    ) -> object | None: ...

    def resolve_training_eligibility(
        self, training_eligibility_id: str, *, checked_at: datetime
    ) -> object | None: ...


@dataclass(frozen=True)
class LearningCandidateReviewResult:
    """Immutable local review result; never a Common canonical object."""

    candidate_id: str
    reviewer_id: str
    reviewed_at: str
    requested_decision: ReviewDecision
    decision: ReviewDecision
    reason_code: ReviewReason
    review_evidence_reference: str
    candidate_schema_version: str
    candidate_content_fingerprint: str
    candidate_producer: ProducerIdentity
    source_type: str
    task: str
    input_references: tuple[CommonObjectReference, ...]
    output_references: tuple[CommonObjectReference, ...]
    parent_candidate_ids: tuple[str, ...]
    candidate_review_evidence_ids: tuple[str, ...]
    rights_metadata_id: str
    consent_evidence_refs: tuple[str, ...]
    training_eligibility_id: str
    usage_purpose: str
    workspace_id: str | None
    rights_checked_at: str
    eligibility_checked_at: str
    current_evidence_resolved: bool
    dataset_inclusion_review_allowed: bool
    dataset_publication_allowed: bool = False
    training_allowed: bool = False
    evaluation_allowed: bool = False
    promotion_allowed: bool = False
    contract_package_version: str = COMMON_CONTRACT_PACKAGE_VERSION
    contract_policy_version: str = COMMON_CONTRACT_POLICY_VERSION
    contract_authority_commit: str = COMMON_CONTRACT_AUTHORITY_COMMIT


@dataclass(frozen=True)
class _CurrentEvidenceDecision:
    reason: ReviewReason | None
    resolved: bool


def review_learning_candidate(
    candidate: ValidatedLearningCandidate,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    requested_decision: ReviewDecision,
    review_evidence_reference: str,
    authority: LearningCandidateReviewAuthority,
    expected_workspace_id: str | None = None,
) -> LearningCandidateReviewResult:
    """Review a validated candidate against current canonical authority evidence."""

    review_time = _require_review_time(reviewed_at)
    _require_reference(reviewer_id, "REVIEWER_INVALID", "reviewer")
    _require_reference(
        review_evidence_reference,
        "REVIEW_EVIDENCE_INVALID",
        "review_evidence",
    )
    if not isinstance(requested_decision, ReviewDecision):
        raise LearningCandidateReviewError("REVIEW_DECISION_INVALID", "decision")
    _require_validated_candidate(candidate, review_time, expected_workspace_id)

    current = _resolve_current_evidence(candidate, authority, review_time)
    decision, reason = _final_decision(requested_decision, current)
    checked_at = _utc_text(review_time)
    return LearningCandidateReviewResult(
        candidate_id=candidate.candidate_id,
        reviewer_id=reviewer_id,
        reviewed_at=checked_at,
        requested_decision=requested_decision,
        decision=decision,
        reason_code=reason,
        review_evidence_reference=review_evidence_reference,
        candidate_schema_version=candidate.schema_version,
        candidate_content_fingerprint=candidate.content_fingerprint,
        candidate_producer=candidate.candidate_producer,
        source_type=candidate.source_type,
        task=candidate.task,
        input_references=candidate.input_references,
        output_references=candidate.output_references,
        parent_candidate_ids=candidate.parent_candidate_ids,
        candidate_review_evidence_ids=candidate.review_evidence_ids,
        rights_metadata_id=candidate.rights_metadata_id,
        consent_evidence_refs=candidate.consent_evidence_refs,
        training_eligibility_id=candidate.training_eligibility_id,
        usage_purpose=candidate.usage_purpose,
        workspace_id=candidate.workspace_id,
        rights_checked_at=checked_at,
        eligibility_checked_at=checked_at,
        current_evidence_resolved=current.resolved,
        dataset_inclusion_review_allowed=decision is ReviewDecision.ACCEPTED,
    )


def _require_validated_candidate(
    candidate: object,
    reviewed_at: datetime,
    expected_workspace_id: str | None,
) -> None:
    if type(candidate) is not ValidatedLearningCandidate:
        raise LearningCandidateReviewError("VALIDATED_CANDIDATE_INVALID", "candidate")
    if (
        candidate.contract_package_version != COMMON_CONTRACT_PACKAGE_VERSION
        or candidate.contract_policy_version != COMMON_CONTRACT_POLICY_VERSION
        or candidate.contract_authority_commit != COMMON_CONTRACT_AUTHORITY_COMMIT
        or candidate.canonical_status != "approved"
        or not _is_reference(candidate.candidate_id)
        or not _is_reference(candidate.rights_metadata_id)
        or not _is_reference(candidate.training_eligibility_id)
        or not _FINGERPRINT.fullmatch(candidate.content_fingerprint)
        or not candidate.review_evidence_ids
        or not candidate.consent_evidence_refs
    ):
        raise LearningCandidateReviewError("VALIDATED_CANDIDATE_INVALID", "candidate")
    if (
        not isinstance(candidate.input_references, tuple)
        or not isinstance(candidate.output_references, tuple)
        or not isinstance(candidate.parent_candidate_ids, tuple)
        or any(
            type(item) is not CommonObjectReference
            for item in candidate.input_references
        )
        or any(
            type(item) is not CommonObjectReference
            for item in candidate.output_references
        )
        or candidate.candidate_id in candidate.parent_candidate_ids
    ):
        raise LearningCandidateReviewError("LINEAGE_MISMATCH", "lineage")
    evaluated_at = _parse_time(candidate.evaluated_at, "candidate")
    if evaluated_at > reviewed_at:
        raise LearningCandidateReviewError("REVIEW_TIMESTAMP_INVALID", "reviewed_at")
    if (
        expected_workspace_id is not None
        and candidate.workspace_id != expected_workspace_id
    ):
        raise LearningCandidateReviewError("WORKSPACE_SCOPE_MISMATCH", "workspace")


def _resolve_current_evidence(
    candidate: ValidatedLearningCandidate,
    authority: LearningCandidateReviewAuthority,
    checked_at: datetime,
) -> _CurrentEvidenceDecision:
    rights_resolver = getattr(authority, "resolve_rights_metadata", None)
    eligibility_resolver = getattr(authority, "resolve_training_eligibility", None)
    if not callable(rights_resolver) or not callable(eligibility_resolver):
        raise LearningCandidateReviewError("CURRENT_AUTHORITY_INVALID", "authority")
    try:
        rights = rights_resolver(candidate.rights_metadata_id, checked_at=checked_at)
        eligibility = eligibility_resolver(
            candidate.training_eligibility_id,
            checked_at=checked_at,
        )
    except Exception:
        raise LearningCandidateReviewError(
            "CURRENT_AUTHORITY_UNAVAILABLE", "authority"
        ) from None
    if rights is None or eligibility is None:
        return _CurrentEvidenceDecision(
            ReviewReason.NEEDS_REVIEW_EVIDENCE_UNRESOLVED,
            False,
        )

    _validate_current_contract(rights, "rights")
    _validate_current_contract(eligibility, "eligibility")
    _require_current_identity(candidate, rights, eligibility, checked_at)
    rights_reason = _rights_reason(rights, checked_at)
    if rights_reason is not None:
        return _CurrentEvidenceDecision(rights_reason, True)
    eligibility_reason = _eligibility_reason(candidate, eligibility, checked_at)
    if eligibility_reason is not None:
        return _CurrentEvidenceDecision(eligibility_reason, True)
    return _CurrentEvidenceDecision(None, True)


def _validate_current_contract(payload: object, stage: str) -> None:
    validator = {
        "rights": validate_rights_metadata,
        "eligibility": validate_training_eligibility,
    }[stage]
    try:
        validator(payload)
    except CommonContractRuntimeError:
        raise LearningCandidateReviewError(
            "COMMON_CONTRACT_UNAVAILABLE", "contract_runtime"
        ) from None
    except CommonDatasetValidationError as exc:
        if any(issue.code in _UNSUPPORTED_VERSION_CODES for issue in exc.issues):
            code = "UNSUPPORTED_CONTRACT_VERSION"
        else:
            code = f"CURRENT_{stage.upper()}_CONTRACT_INVALID"
        raise LearningCandidateReviewError(code, stage) from None


def _require_current_identity(
    candidate: ValidatedLearningCandidate,
    rights: Any,
    eligibility: Any,
    checked_at: datetime,
) -> None:
    if (
        rights["object_id"] != candidate.rights_metadata_id
        or rights["rights_metadata_id"] != candidate.rights_metadata_id
        or eligibility["object_id"] != candidate.training_eligibility_id
        or eligibility["training_eligibility_id"] != candidate.training_eligibility_id
        or eligibility["candidate_id"] != candidate.candidate_id
        or eligibility["rights_metadata_id"] != candidate.rights_metadata_id
        or eligibility["candidate_status"] != candidate.canonical_status
        or eligibility["usage_purpose"] != candidate.usage_purpose
    ):
        raise LearningCandidateReviewError("CURRENT_IDENTITY_MISMATCH", "identity")
    if (
        _producer(rights) != candidate.rights_producer
        or _producer(eligibility) != candidate.eligibility_producer
    ):
        raise LearningCandidateReviewError("CURRENT_AUTHORITY_MISMATCH", "producer")
    if (
        rights.get("workspace_id") != candidate.workspace_id
        or eligibility.get("workspace_id") != candidate.workspace_id
    ):
        raise LearningCandidateReviewError("WORKSPACE_SCOPE_MISMATCH", "workspace")
    if tuple(rights["consent_evidence_refs"]) != candidate.consent_evidence_refs:
        raise LearningCandidateReviewError("EVIDENCE_IDENTITY_MISMATCH", "evidence")
    if (
        _parse_time(rights["created_at"], "rights") > checked_at
        or _parse_time(rights["reviewed_at"], "rights") > checked_at
        or _parse_time(eligibility["created_at"], "eligibility") > checked_at
        or _parse_time(eligibility["reviewed_at"], "eligibility") > checked_at
    ):
        raise LearningCandidateReviewError("CURRENT_EVIDENCE_FROM_FUTURE", "evidence")


def _rights_reason(rights: Any, checked_at: datetime) -> ReviewReason | None:
    status = rights["rights_status"]
    if status == "revoked":
        return ReviewReason.REJECTED_RIGHTS_REVOKED
    if status == "expired":
        return ReviewReason.REJECTED_RIGHTS_EXPIRED
    retention = rights["retention_allowed"]
    if (
        status not in {"approved", "approved_limited"}
        or rights["training_allowed"] is not True
        or not isinstance(retention, dict)
        or retention.get("allowed") is not True
        or retention.get("scope") != "training"
    ):
        return ReviewReason.REJECTED_RIGHTS_INVALID
    if not rights["consent_evidence_refs"]:
        return ReviewReason.NEEDS_REVIEW_EVIDENCE_UNRESOLVED
    if _parse_time(retention.get("expires_at"), "rights") <= checked_at:
        return ReviewReason.REJECTED_RIGHTS_EXPIRED
    return None


def _eligibility_reason(
    candidate: ValidatedLearningCandidate,
    eligibility: Any,
    checked_at: datetime,
) -> ReviewReason | None:
    if eligibility["decision"] == "revoked":
        return ReviewReason.REJECTED_ELIGIBILITY_REVOKED
    if (
        eligibility["usage_purpose"] != candidate.usage_purpose
        or eligibility["candidate_status"] != "approved"
        or eligibility["decision"] != "eligible"
        or eligibility["approved"] is not True
        or eligibility["training_allowed"] is not True
        or any(value != "pass" for value in eligibility["checks"].values())
    ):
        return ReviewReason.REJECTED_ELIGIBILITY_INVALID
    if _parse_time(eligibility["expires_at"], "eligibility") <= checked_at:
        return ReviewReason.REJECTED_ELIGIBILITY_EXPIRED
    return None


def _final_decision(
    requested: ReviewDecision,
    current: _CurrentEvidenceDecision,
) -> tuple[ReviewDecision, ReviewReason]:
    if current.reason is not None and current.reason.name.startswith("REJECTED_"):
        return ReviewDecision.REJECTED, current.reason
    if requested is ReviewDecision.REJECTED:
        return ReviewDecision.REJECTED, ReviewReason.REJECTED_BY_REVIEWER
    if current.reason is ReviewReason.NEEDS_REVIEW_EVIDENCE_UNRESOLVED:
        return ReviewDecision.NEEDS_REVIEW, current.reason
    if requested is ReviewDecision.NEEDS_REVIEW:
        return ReviewDecision.NEEDS_REVIEW, ReviewReason.NEEDS_REVIEW_REQUESTED
    return ReviewDecision.ACCEPTED, ReviewReason.ACCEPTED_VALID_CURRENT_ELIGIBILITY


def _require_review_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise LearningCandidateReviewError("REVIEW_TIMESTAMP_INVALID", "reviewed_at")
    return value


def _parse_time(value: object, stage: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise LearningCandidateReviewError("CURRENT_TIMESTAMP_INVALID", stage) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LearningCandidateReviewError("CURRENT_TIMESTAMP_INVALID", stage)
    return parsed


def _is_reference(value: object) -> bool:
    return isinstance(value, str) and _SAFE_REFERENCE.fullmatch(value) is not None


def _require_reference(value: object, code: str, stage: str) -> None:
    if not _is_reference(value):
        raise LearningCandidateReviewError(code, stage)


def _producer(value: Any) -> ProducerIdentity:
    return ProducerIdentity(value["producer"]["name"], value["producer"]["version"])


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "LearningCandidateReviewAuthority",
    "LearningCandidateReviewError",
    "LearningCandidateReviewResult",
    "ReviewDecision",
    "ReviewReason",
    "review_learning_candidate",
]
