"""Fail-closed consumer projection for canonical Common LearningCandidate input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .common_dataset_contracts import (
    COMMON_CONTRACT_AUTHORITY_COMMIT,
    COMMON_CONTRACT_PACKAGE_VERSION,
    COMMON_CONTRACT_POLICY_VERSION,
    CommonContractRuntimeError,
    CommonDatasetValidationError,
    validate_learning_candidate,
    validate_rights_metadata,
    validate_training_eligibility,
)

_LINEAGE_REQUIRED_SOURCE_TYPES = frozenset(
    {"human_edited", "preference", "similarity_revision"}
)
_UNSUPPORTED_VERSION_CODES = frozenset(
    {
        "DEPRECATED_SCHEMA_VERSION",
        "INVALID_SCHEMA_VERSION",
        "UNSUPPORTED_SCHEMA_VERSION",
    }
)


class LearningCandidateConsumerError(ValueError):
    """A canonical object or local consumption invariant failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:learning_candidate_consumer")


@dataclass(frozen=True, order=True)
class CommonObjectReference:
    """Immutable, non-payload projection of a Common object reference."""

    object_id: str
    schema_name: str
    schema_version: str
    content_fingerprint: str | None = None


@dataclass(frozen=True, order=True)
class ProducerIdentity:
    """Canonical producer identity preserved without assigning local ownership."""

    name: str
    version: str


@dataclass(frozen=True)
class ValidatedLearningCandidate:
    """Immutable consumer view; this is not a canonical Common schema."""

    candidate_id: str
    canonical_status: str
    source_type: str
    task: str
    schema_version: str
    content_fingerprint: str
    input_references: tuple[CommonObjectReference, ...]
    output_references: tuple[CommonObjectReference, ...]
    parent_candidate_ids: tuple[str, ...]
    review_evidence_ids: tuple[str, ...]
    rights_metadata_id: str
    consent_evidence_refs: tuple[str, ...]
    training_eligibility_id: str
    usage_purpose: str
    workspace_id: str | None
    candidate_producer: ProducerIdentity
    rights_producer: ProducerIdentity
    eligibility_producer: ProducerIdentity
    evaluated_at: str
    rights_expires_at: str | None
    eligibility_expires_at: str
    contract_package_version: str = COMMON_CONTRACT_PACKAGE_VERSION
    contract_policy_version: str = COMMON_CONTRACT_POLICY_VERSION
    contract_authority_commit: str = COMMON_CONTRACT_AUTHORITY_COMMIT


def validate_learning_candidate_for_consumption(
    candidate: Any,
    *,
    rights_metadata: Any,
    training_eligibility: Any,
    evaluated_at: datetime,
    usage_purpose: str,
    expected_workspace_id: str | None = None,
) -> ValidatedLearningCandidate:
    """Validate canonical inputs and return an immutable, side-effect-free view."""

    evaluation_time = _require_evaluation_time(evaluated_at)
    if not isinstance(usage_purpose, str) or not usage_purpose:
        raise LearningCandidateConsumerError("ELIGIBILITY_INVALID", "usage_purpose")
    if rights_metadata is None:
        raise LearningCandidateConsumerError("RIGHTS_MISSING", "rights")
    if training_eligibility is None:
        raise LearningCandidateConsumerError("ELIGIBILITY_MISSING", "eligibility")

    _validate_authority_object(candidate, "candidate")
    _validate_authority_object(rights_metadata, "rights")
    _validate_authority_object(training_eligibility, "eligibility")

    candidate_id = candidate["candidate_id"]
    rights_id = rights_metadata["rights_metadata_id"]
    if (
        candidate["object_id"] != candidate_id
        or candidate["rights_metadata_id"] != rights_id
        or training_eligibility["candidate_id"] != candidate_id
        or training_eligibility["rights_metadata_id"] != rights_id
        or training_eligibility["candidate_status"] != candidate["status"]
    ):
        raise LearningCandidateConsumerError("IDENTITY_MISMATCH", "binding")

    _require_candidate_state(candidate)
    rights_expiry = _require_rights(rights_metadata, evaluation_time)
    eligibility_expiry = _require_eligibility(
        training_eligibility,
        evaluation_time,
        usage_purpose,
    )
    _require_evidence(candidate, rights_metadata)
    _require_lineage(candidate)
    workspace_id = _require_scope(
        candidate,
        rights_metadata,
        training_eligibility,
        expected_workspace_id,
    )
    _require_not_future(candidate["created_at"], evaluation_time, "lineage")
    _require_not_future(rights_metadata["reviewed_at"], evaluation_time, "rights")
    _require_not_future(
        training_eligibility["reviewed_at"], evaluation_time, "eligibility"
    )

    return ValidatedLearningCandidate(
        candidate_id=candidate_id,
        canonical_status=candidate["status"],
        source_type=candidate["source_type"],
        task=candidate["task"],
        schema_version=candidate["schema_version"],
        content_fingerprint=candidate["content_fingerprint"],
        input_references=_references(candidate["input_refs"]),
        output_references=_references(candidate["output_refs"]),
        parent_candidate_ids=tuple(candidate["parent_candidate_ids"]),
        review_evidence_ids=tuple(candidate["review_evidence_ids"]),
        rights_metadata_id=rights_id,
        consent_evidence_refs=tuple(rights_metadata["consent_evidence_refs"]),
        training_eligibility_id=training_eligibility["training_eligibility_id"],
        usage_purpose=training_eligibility["usage_purpose"],
        workspace_id=workspace_id,
        candidate_producer=_producer(candidate),
        rights_producer=_producer(rights_metadata),
        eligibility_producer=_producer(training_eligibility),
        evaluated_at=_utc_text(evaluation_time),
        rights_expires_at=rights_expiry,
        eligibility_expires_at=eligibility_expiry,
    )


def _validate_authority_object(payload: Any, stage: str) -> None:
    validator = {
        "candidate": validate_learning_candidate,
        "rights": validate_rights_metadata,
        "eligibility": validate_training_eligibility,
    }[stage]
    try:
        validator(payload)
    except CommonContractRuntimeError as exc:
        raise LearningCandidateConsumerError(
            "COMMON_CONTRACT_UNAVAILABLE", "contract_runtime"
        ) from exc
    except CommonDatasetValidationError as exc:
        if any(issue.code in _UNSUPPORTED_VERSION_CODES for issue in exc.issues):
            code = "UNSUPPORTED_CONTRACT_VERSION"
        else:
            code = {
                "candidate": "CONTRACT_INVALID",
                "rights": "RIGHTS_INVALID",
                "eligibility": "ELIGIBILITY_INVALID",
            }[stage]
        raise LearningCandidateConsumerError(code, stage) from exc


def _require_candidate_state(candidate: dict[str, Any]) -> None:
    if candidate["status"] != "approved":
        raise LearningCandidateConsumerError("ELIGIBILITY_INVALID", "candidate_state")


def _require_rights(rights: dict[str, Any], evaluated_at: datetime) -> str | None:
    status = rights["rights_status"]
    if status == "revoked":
        raise LearningCandidateConsumerError("RIGHTS_REVOKED", "rights")
    if status == "expired":
        raise LearningCandidateConsumerError("RIGHTS_EXPIRED", "rights")
    retention = rights["retention_allowed"]
    if (
        status not in {"approved", "approved_limited"}
        or rights["training_allowed"] is not True
    ):
        raise LearningCandidateConsumerError("RIGHTS_INVALID", "rights")
    if retention is True:
        return None
    if (
        not isinstance(retention, dict)
        or retention.get("allowed") is not True
        or retention.get("scope") != "training"
    ):
        raise LearningCandidateConsumerError("RIGHTS_INVALID", "rights")
    expires_at = _parse_time(retention.get("expires_at"), "rights")
    if expires_at <= evaluated_at:
        raise LearningCandidateConsumerError("RIGHTS_EXPIRED", "rights")
    return retention["expires_at"]


def _require_eligibility(
    eligibility: dict[str, Any], evaluated_at: datetime, usage_purpose: str
) -> str:
    if eligibility["decision"] == "revoked":
        raise LearningCandidateConsumerError("ELIGIBILITY_REVOKED", "eligibility")
    if (
        eligibility["usage_purpose"] != usage_purpose
        or eligibility["candidate_status"] != "approved"
        or eligibility["decision"] != "eligible"
        or eligibility["approved"] is not True
        or eligibility["training_allowed"] is not True
        or any(value != "pass" for value in eligibility["checks"].values())
    ):
        raise LearningCandidateConsumerError("ELIGIBILITY_INVALID", "eligibility")
    expires_at = _parse_time(eligibility["expires_at"], "eligibility")
    if expires_at <= evaluated_at:
        raise LearningCandidateConsumerError("ELIGIBILITY_EXPIRED", "eligibility")
    return eligibility["expires_at"]


def _require_evidence(candidate: dict[str, Any], rights: dict[str, Any]) -> None:
    if not candidate["review_evidence_ids"]:
        raise LearningCandidateConsumerError("EVIDENCE_MISSING", "evidence")
    if rights["consent_evidence_refs"]:
        return
    extension = rights.get("extensions", {}).get("doharights.current_use", {})
    typed = extension.get("typed_evidence_references")
    if (
        rights.get("source_type") not in {"external", "reference"}
        or extension.get("consent_basis") != "not_applicable"
        or extension.get("current_use_authorized") is not True
        or not isinstance(typed, list)
        or not typed
        or any(
            not isinstance(value, dict)
            or not isinstance(value.get("reference_id"), str)
            or not value["reference_id"]
            or not isinstance(value.get("evidence_type"), str)
            or not value["evidence_type"]
            for value in typed
        )
    ):
        raise LearningCandidateConsumerError("EVIDENCE_MISSING", "evidence")


def _require_lineage(candidate: dict[str, Any]) -> None:
    parents = candidate["parent_candidate_ids"]
    if candidate["candidate_id"] in parents:
        raise LearningCandidateConsumerError("LINEAGE_INVALID", "lineage")
    if (
        candidate["source_type"] in _LINEAGE_REQUIRED_SOURCE_TYPES
        and not parents
        and not candidate["input_refs"]
    ):
        raise LearningCandidateConsumerError("LINEAGE_INVALID", "lineage")


def _require_scope(
    candidate: dict[str, Any],
    rights: dict[str, Any],
    eligibility: dict[str, Any],
    expected_workspace_id: str | None,
) -> str | None:
    workspace_ids = tuple(
        item.get("workspace_id") for item in (candidate, rights, eligibility)
    )
    present = tuple(item for item in workspace_ids if item is not None)
    if present and (len(present) != len(workspace_ids) or len(set(present)) != 1):
        raise LearningCandidateConsumerError("SCOPE_MISMATCH", "workspace")
    workspace_id = present[0] if present else None
    if expected_workspace_id is not None and workspace_id != expected_workspace_id:
        raise LearningCandidateConsumerError("SCOPE_MISMATCH", "workspace")
    return workspace_id


def _require_evaluation_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise LearningCandidateConsumerError("EVALUATION_TIME_INVALID", "input")
    return value


def _require_not_future(value: str, evaluated_at: datetime, stage: str) -> None:
    if _parse_time(value, stage) > evaluated_at:
        code = {
            "lineage": "LINEAGE_INVALID",
            "rights": "RIGHTS_INVALID",
            "eligibility": "ELIGIBILITY_INVALID",
        }[stage]
        raise LearningCandidateConsumerError(code, stage)


def _parse_time(value: Any, stage: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise LearningCandidateConsumerError("EVALUATION_TIME_INVALID", stage) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LearningCandidateConsumerError("EVALUATION_TIME_INVALID", stage)
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _references(values: list[dict[str, Any]]) -> tuple[CommonObjectReference, ...]:
    return tuple(
        CommonObjectReference(
            object_id=value["object_id"],
            schema_name=value["schema_name"],
            schema_version=value["schema_version"],
            content_fingerprint=value.get("content_fingerprint"),
        )
        for value in values
    )


def _producer(value: dict[str, Any]) -> ProducerIdentity:
    return ProducerIdentity(value["producer"]["name"], value["producer"]["version"])


__all__ = [
    "CommonObjectReference",
    "LearningCandidateConsumerError",
    "ProducerIdentity",
    "ValidatedLearningCandidate",
    "validate_learning_candidate_for_consumption",
]
