"""Dataset Review Authority start/read domain port contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from .checksums import checksum_value
from .dataset_governance import DatasetVersionIdentity

_SAFE_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9._:@-]{1,255}")
_IDENTITY_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_REVIEWING = "reviewing"


class DatasetReviewOutcome(str, Enum):
    """Authoritative outcome of one atomic review-start adjudication."""

    STARTED = "STARTED"
    REPLAYED = "REPLAYED"
    CONFLICT = "CONFLICT"


class DatasetReviewAuthorityError(RuntimeError):
    """A review request, authority result, or authoritative read failed closed."""

    def __init__(
        self,
        code: str,
        stage: str,
        *,
        identity: DatasetVersionIdentity | None = None,
        expected_fingerprint: str | None = None,
        actual_fingerprint: str | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.identity = identity
        self.expected_fingerprint = expected_fingerprint
        self.actual_fingerprint = actual_fingerprint
        super().__init__(f"{code}:{stage}:dataset_review_authority")


@dataclass(frozen=True, slots=True)
class DatasetReviewStartRequest:
    """Immutable local request for one DatasetVersion review lifecycle start."""

    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    reviewer_reference: str
    review_started_at: datetime
    request_reference: str | None = None

    def __post_init__(self) -> None:
        _require_request_integrity(self)


@dataclass(frozen=True, slots=True)
class DatasetReviewAuthorityRecord:
    """Immutable authoritative record of the first successful review start."""

    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    reviewer_reference: str
    review_started_at: datetime
    request_reference: str | None
    authority_reference: str
    authority_version: int
    record_fingerprint: str
    lifecycle_state: str = _REVIEWING

    def __post_init__(self) -> None:
        _require_record_integrity(self)

    @property
    def approved(self) -> bool:
        return False

    @property
    def frozen(self) -> bool:
        return False

    @property
    def training_allowed(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class DatasetReviewStartResult:
    """Validated result of an atomic STARTED/REPLAYED/CONFLICT decision."""

    outcome: DatasetReviewOutcome
    identity: DatasetVersionIdentity
    proposal_fingerprint: str
    authority_reference: str
    authority_version: int
    record: DatasetReviewAuthorityRecord | None = None

    def __post_init__(self) -> None:
        _require_result_integrity(self)


class DatasetReviewAuthority(Protocol):
    """Atomic review-start and authoritative review-read domain port.

    Implementations must bind one immutable review lifecycle to the exact
    ``DatasetVersionIdentity`` and canonical proposal fingerprint. Concurrent
    equivalent requests have one logical record (STARTED then REPLAYED), while
    conflicting requests return CONFLICT without overwrite.
    """

    def start_review(
        self,
        request: DatasetReviewStartRequest,
    ) -> DatasetReviewStartResult:
        """Atomically start, replay, or reject a conflicting review request."""

    def read_authoritative_review(
        self,
        identity: DatasetVersionIdentity,
        *,
        proposal_fingerprint: str,
    ) -> DatasetReviewAuthorityRecord:
        """Read the immutable record for one exact proposal binding."""


def build_dataset_review_authority_record(
    request: DatasetReviewStartRequest,
    *,
    authority_reference: str,
    authority_version: int,
) -> DatasetReviewAuthorityRecord:
    """Build a validated record without adding a clock or persistence metadata."""

    if type(request) is not DatasetReviewStartRequest:
        raise DatasetReviewAuthorityError("REVIEW_START_REQUEST_INVALID", "request")
    _require_request_integrity(request)
    _require_authority_metadata(authority_reference, authority_version, stage="record")
    semantic = _record_semantic_value(
        identity=request.identity,
        proposal_fingerprint=request.proposal_fingerprint,
        reviewer_reference=request.reviewer_reference,
        review_started_at=request.review_started_at,
        request_reference=request.request_reference,
        authority_reference=authority_reference,
        authority_version=authority_version,
        lifecycle_state=_REVIEWING,
        stage="record",
    )
    return DatasetReviewAuthorityRecord(
        identity=request.identity,
        proposal_fingerprint=request.proposal_fingerprint,
        reviewer_reference=request.reviewer_reference,
        review_started_at=request.review_started_at,
        request_reference=request.request_reference,
        authority_reference=authority_reference,
        authority_version=authority_version,
        record_fingerprint=checksum_value(semantic),
    )


def dataset_review_authority_record_fingerprint(
    record: DatasetReviewAuthorityRecord,
) -> str:
    """Return the deterministic fingerprint of a review record's meaning."""

    if type(record) is not DatasetReviewAuthorityRecord:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            "record",
        )
    semantic = _record_semantic_value(
        identity=record.identity,
        proposal_fingerprint=record.proposal_fingerprint,
        reviewer_reference=record.reviewer_reference,
        review_started_at=record.review_started_at,
        request_reference=record.request_reference,
        authority_reference=record.authority_reference,
        authority_version=record.authority_version,
        lifecycle_state=record.lifecycle_state,
        stage="record",
    )
    return checksum_value(semantic)


def dataset_review_start_requests_equivalent(
    left: DatasetReviewStartRequest,
    right: DatasetReviewStartRequest,
) -> bool:
    """Compare logical retry identity while intentionally ignoring start time."""

    if (
        type(left) is not DatasetReviewStartRequest
        or type(right) is not DatasetReviewStartRequest
    ):
        raise DatasetReviewAuthorityError("REVIEW_START_REQUEST_INVALID", "request")
    _require_request_integrity(left)
    _require_request_integrity(right)
    return (
        left.identity == right.identity
        and left.proposal_fingerprint == right.proposal_fingerprint
        and left.reviewer_reference == right.reviewer_reference
        and left.request_reference == right.request_reference
    )


def validate_dataset_review_authority_record(
    record: object,
    *,
    expected_identity: DatasetVersionIdentity,
    expected_proposal_fingerprint: str,
) -> DatasetReviewAuthorityRecord:
    """Validate an authoritative read against its exact caller lookup binding."""

    _require_identity(expected_identity, stage="read")
    _require_fingerprint(expected_proposal_fingerprint, stage="read")
    if type(record) is not DatasetReviewAuthorityRecord:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            "read",
        )
    _require_record_integrity(record)
    if record.identity != expected_identity:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_IDENTITY_MISMATCH",
            "read",
            identity=expected_identity,
        )
    if record.proposal_fingerprint != expected_proposal_fingerprint:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH",
            "read",
            identity=expected_identity,
            expected_fingerprint=expected_proposal_fingerprint,
            actual_fingerprint=record.proposal_fingerprint,
        )
    return record


def validate_dataset_review_start_request(
    request: object,
) -> DatasetReviewStartRequest:
    """Validate an untrusted request object without normalization or fallback."""

    if type(request) is not DatasetReviewStartRequest:
        raise DatasetReviewAuthorityError("REVIEW_START_REQUEST_INVALID", "request")
    _require_request_integrity(request)
    return request


def validate_dataset_review_start_result(
    result: object,
    request: DatasetReviewStartRequest,
) -> DatasetReviewStartResult:
    """Validate an authority result against the submitted request binding."""

    if type(request) is not DatasetReviewStartRequest:
        raise DatasetReviewAuthorityError("REVIEW_START_REQUEST_INVALID", "request")
    _require_request_integrity(request)
    if type(result) is not DatasetReviewStartResult:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
            "result",
        )
    _require_result_integrity(result)
    if result.identity != request.identity:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_IDENTITY_MISMATCH",
            "result",
            identity=request.identity,
        )
    if result.proposal_fingerprint != request.proposal_fingerprint:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_PROPOSAL_FINGERPRINT_MISMATCH",
            "result",
            identity=request.identity,
            expected_fingerprint=request.proposal_fingerprint,
            actual_fingerprint=result.proposal_fingerprint,
        )
    return result


def _require_result_integrity(result: DatasetReviewStartResult) -> None:
    if not isinstance(result.outcome, DatasetReviewOutcome):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
            "result",
        )
    _require_identity(result.identity, stage="result")
    _require_fingerprint(result.proposal_fingerprint, stage="result")
    _require_authority_metadata(
        result.authority_reference,
        result.authority_version,
        stage="result",
    )
    if result.outcome is DatasetReviewOutcome.CONFLICT:
        if result.record is not None:
            raise DatasetReviewAuthorityError(
                "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
                "result",
            )
        return
    if type(result.record) is not DatasetReviewAuthorityRecord:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
            "result",
        )
    _require_record_integrity(result.record)
    if (
        result.record.identity != result.identity
        or result.record.proposal_fingerprint != result.proposal_fingerprint
        or result.record.authority_reference != result.authority_reference
        or result.record.authority_version != result.authority_version
    ):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
            "result",
        )


def _require_request_integrity(request: DatasetReviewStartRequest) -> None:
    _require_identity(request.identity, stage="request")
    _require_fingerprint(request.proposal_fingerprint, stage="request")
    _require_reference(
        request.reviewer_reference,
        code="REVIEWER_REFERENCE_INVALID",
        stage="request",
    )
    _require_timestamp(request.review_started_at, stage="request")
    _require_optional_reference(request.request_reference, stage="request")


def _require_record_integrity(record: DatasetReviewAuthorityRecord) -> None:
    semantic = _record_semantic_value(
        identity=record.identity,
        proposal_fingerprint=record.proposal_fingerprint,
        reviewer_reference=record.reviewer_reference,
        review_started_at=record.review_started_at,
        request_reference=record.request_reference,
        authority_reference=record.authority_reference,
        authority_version=record.authority_version,
        lifecycle_state=record.lifecycle_state,
        stage="record",
    )
    if (
        not isinstance(record.record_fingerprint, str)
        or _FINGERPRINT.fullmatch(record.record_fingerprint) is None
        or checksum_value(semantic) != record.record_fingerprint
    ):
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            "record",
        )


def _record_semantic_value(
    *,
    identity: DatasetVersionIdentity,
    proposal_fingerprint: str,
    reviewer_reference: str,
    review_started_at: datetime,
    request_reference: str | None,
    authority_reference: str,
    authority_version: int,
    lifecycle_state: str,
    stage: str,
) -> dict[str, object]:
    _require_identity(identity, stage=stage)
    _require_fingerprint(proposal_fingerprint, stage=stage)
    _require_reference(
        reviewer_reference,
        code="DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
        stage=stage,
    )
    _require_timestamp(review_started_at, stage=stage)
    _require_optional_reference(request_reference, stage=stage)
    _require_authority_metadata(authority_reference, authority_version, stage=stage)
    if lifecycle_state != _REVIEWING:
        raise DatasetReviewAuthorityError(
            "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            stage,
        )
    return {
        "identity": {
            "object_id": identity.object_id,
            "dataset_id": identity.dataset_id,
            "dataset_version": identity.dataset_version,
        },
        "proposal_fingerprint": proposal_fingerprint,
        "lifecycle_state": lifecycle_state,
        "reviewer_reference": reviewer_reference,
        "review_started_at": _utc_text(review_started_at),
        "request_reference": request_reference,
        "authority_reference": authority_reference,
        "authority_version": authority_version,
    }


def _require_identity(value: object, *, stage: str) -> None:
    if type(value) is not DatasetVersionIdentity or any(
        not isinstance(item, str) or _IDENTITY_COMPONENT.fullmatch(item) is None
        for item in (value.object_id, value.dataset_id, value.dataset_version)
    ):
        code = {
            "record": "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            "result": "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
        }.get(stage, "DATASET_REVIEW_IDENTITY_INVALID")
        raise DatasetReviewAuthorityError(code, stage)


def _require_fingerprint(value: object, *, stage: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        code = {
            "record": "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT",
            "result": "DATASET_REVIEW_AUTHORITY_RESULT_INVALID",
        }.get(stage, "DATASET_REVIEW_PROPOSAL_FINGERPRINT_INVALID")
        raise DatasetReviewAuthorityError(code, stage)


def _require_reference(value: object, *, code: str, stage: str) -> None:
    if not _is_reference(value):
        raise DatasetReviewAuthorityError(code, stage)


def _require_optional_reference(value: object, *, stage: str) -> None:
    if value is not None and not _is_reference(value):
        code = (
            "REVIEW_REQUEST_REFERENCE_INVALID"
            if stage == "request"
            else "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"
        )
        raise DatasetReviewAuthorityError(code, stage)


def _require_timestamp(value: object, *, stage: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        code = (
            "REVIEW_STARTED_AT_INVALID"
            if stage == "request"
            else "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"
        )
        raise DatasetReviewAuthorityError(code, stage)


def _require_authority_metadata(
    reference: object,
    version: object,
    *,
    stage: str,
) -> None:
    if (
        not _is_reference(reference)
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
    ):
        code = (
            "DATASET_REVIEW_AUTHORITY_RESULT_INVALID"
            if stage == "result"
            else "DATASET_REVIEW_AUTHORITY_RECORD_CORRUPT"
        )
        raise DatasetReviewAuthorityError(code, stage)


def _is_reference(value: object) -> bool:
    return isinstance(value, str) and _SAFE_REFERENCE.fullmatch(value) is not None


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


__all__ = [
    "DatasetReviewAuthority",
    "DatasetReviewAuthorityError",
    "DatasetReviewAuthorityRecord",
    "DatasetReviewOutcome",
    "DatasetReviewStartRequest",
    "DatasetReviewStartResult",
    "build_dataset_review_authority_record",
    "dataset_review_authority_record_fingerprint",
    "dataset_review_start_requests_equivalent",
    "validate_dataset_review_authority_record",
    "validate_dataset_review_start_request",
    "validate_dataset_review_start_result",
]
