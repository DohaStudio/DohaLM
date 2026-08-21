"""Immutable product Dataset composition before Dataset governance."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .checksums import checksum_value
from .common_dataset_contracts import (
    COMMON_CONTRACT_AUTHORITY_COMMIT,
    COMMON_CONTRACT_PACKAGE_VERSION,
    COMMON_CONTRACT_POLICY_VERSION,
    validate_dataset_version,
)
from .learning_candidate_consumer import CommonObjectReference, ProducerIdentity
from .learning_candidate_dataset_handoff import (
    DatasetInclusionHandoff,
    DatasetInclusionHandoffError,
    evaluate_current_handoff_evidence,
    validate_dataset_inclusion_handoff,
)
from .learning_candidate_review import LearningCandidateReviewAuthority

_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{1,127}")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
)
_SPLITS = ("train", "validation", "test")


class ProductDatasetCompositionStatus(str, Enum):
    """Local state that grants only entry to proposal integration."""

    READY_FOR_DATASET_VERSION_PROPOSAL = "READY_FOR_DATASET_VERSION_PROPOSAL"


class ProductDatasetCompositionError(ValueError):
    """A product Dataset composition invariant failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:product_dataset_composition")


@dataclass(frozen=True, order=True)
class ProductDatasetMemberAllocation:
    """Explicit Dataset-level split and group ownership for one handoff."""

    handoff_id: str
    split: str
    group_key: str


@dataclass(frozen=True)
class ProductDatasetCompositionAuthorityInput:
    """Explicit DohaLM Dataset-level authority input; not a Common object."""

    object_id: str
    dataset_id: str
    dataset_version: str
    created_at: datetime
    created_by: str
    producer: ProducerIdentity
    workspace_id: str | None
    schema_manifest_id: str
    dataset_manifest_id: str
    dataset_eligibility_evidence_id: str
    approval_evidence_ids: tuple[str, ...]
    allocations: tuple[ProductDatasetMemberAllocation, ...]


@dataclass(frozen=True, order=True)
class ProductDatasetCompositionMember:
    """Safe immutable member projection derived only from one handoff."""

    handoff_id: str
    candidate_id: str
    candidate_schema_version: str
    candidate_content_fingerprint: str
    review_evidence_reference: str
    reviewer_id: str
    reviewed_at: str
    split: str
    group_key: str
    source_type: str
    task: str
    usage_purpose: str
    workspace_id: str | None
    rights_metadata_id: str
    training_eligibility_id: str
    candidate_producer: ProducerIdentity
    rights_producer: ProducerIdentity
    eligibility_producer: ProducerIdentity
    input_references: tuple[CommonObjectReference, ...]
    output_references: tuple[CommonObjectReference, ...]
    parent_candidate_ids: tuple[str, ...]
    candidate_review_evidence_ids: tuple[str, ...]
    consent_evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ProductDatasetComposition:
    """Complete immutable input for DatasetVersion proposal integration."""

    composition_id: str
    status: ProductDatasetCompositionStatus
    object_id: str
    dataset_id: str
    dataset_version: str
    created_at: str
    composed_at: str
    created_by: str
    producer: ProducerIdentity
    workspace_id: str | None
    schema_manifest_id: str
    dataset_manifest_id: str
    dataset_eligibility_evidence_id: str
    approval_evidence_ids: tuple[str, ...]
    task: str
    usage_purpose: str
    train_members: tuple[ProductDatasetCompositionMember, ...]
    validation_members: tuple[ProductDatasetCompositionMember, ...]
    test_members: tuple[ProductDatasetCompositionMember, ...]
    source_fingerprint: str
    content_fingerprint: str
    contract_package_version: str = COMMON_CONTRACT_PACKAGE_VERSION
    contract_policy_version: str = COMMON_CONTRACT_POLICY_VERSION
    contract_authority_commit: str = COMMON_CONTRACT_AUTHORITY_COMMIT

    @property
    def members(self) -> tuple[ProductDatasetCompositionMember, ...]:
        return self.train_members + self.validation_members + self.test_members


def compose_product_dataset(
    handoffs: Sequence[DatasetInclusionHandoff],
    *,
    authority_input: ProductDatasetCompositionAuthorityInput,
    current_authority: LearningCandidateReviewAuthority,
    composed_at: datetime,
) -> ProductDatasetComposition:
    """Validate and compose exact handoffs without governance side effects."""

    _require_authority_input(authority_input)
    checked_at = _require_time(composed_at, "composed_at")
    created_at = _require_time(authority_input.created_at, "created_at")
    if created_at > checked_at:
        raise ProductDatasetCompositionError("COMPOSITION_TIMESTAMP_INVALID", "time")
    if isinstance(handoffs, (str, bytes)) or not isinstance(handoffs, Sequence):
        raise ProductDatasetCompositionError("HANDOFF_COLLECTION_INVALID", "handoffs")
    values = tuple(handoffs)
    if not values or any(
        type(value) is not DatasetInclusionHandoff for value in values
    ):
        raise ProductDatasetCompositionError("HANDOFF_COLLECTION_INVALID", "handoffs")

    allocation_by_handoff = _allocation_index(authority_input.allocations)
    if set(allocation_by_handoff) != {value.handoff_id for value in values}:
        raise ProductDatasetCompositionError(
            "ALLOCATION_COVERAGE_MISMATCH", "allocation"
        )

    members: list[ProductDatasetCompositionMember] = []
    for handoff in values:
        if handoff.workspace_id != authority_input.workspace_id:
            raise ProductDatasetCompositionError(
                "WORKSPACE_SCOPE_MISMATCH",
                "workspace",
            )
        try:
            validate_dataset_inclusion_handoff(
                handoff,
                expected_workspace_id=handoff.workspace_id,
            )
            evaluate_current_handoff_evidence(
                handoff,
                authority=current_authority,
                checked_at=checked_at,
            )
        except DatasetInclusionHandoffError as exc:
            raise ProductDatasetCompositionError(exc.code, exc.stage) from None
        members.append(_member(handoff, allocation_by_handoff[handoff.handoff_id]))

    _require_member_invariants(members)
    task = _single_value((member.task for member in members), "TASK_MISMATCH")
    purpose = _single_value(
        (member.usage_purpose for member in members),
        "USAGE_PURPOSE_MISMATCH",
    )
    canonical_members = tuple(sorted(members, key=lambda value: value.candidate_id))
    source_fingerprint = checksum_value(
        [_source_projection(member) for member in canonical_members]
    )
    content_fingerprint = checksum_value(
        [_content_projection(member) for member in canonical_members]
    )
    identity = {
        "approval_evidence_ids": list(authority_input.approval_evidence_ids),
        "content_fingerprint": content_fingerprint,
        "created_at": _utc_text(created_at),
        "created_by": authority_input.created_by,
        "dataset_eligibility_evidence_id": (
            authority_input.dataset_eligibility_evidence_id
        ),
        "dataset_id": authority_input.dataset_id,
        "dataset_manifest_id": authority_input.dataset_manifest_id,
        "dataset_version": authority_input.dataset_version,
        "members": [_identity_projection(member) for member in canonical_members],
        "object_id": authority_input.object_id,
        "producer": _producer_projection(authority_input.producer),
        "schema_manifest_id": authority_input.schema_manifest_id,
        "source_fingerprint": source_fingerprint,
        "task": task,
        "usage_purpose": purpose,
        "workspace_id": authority_input.workspace_id,
    }
    composition = ProductDatasetComposition(
        composition_id=f"composition:{checksum_value(identity)}",
        status=ProductDatasetCompositionStatus.READY_FOR_DATASET_VERSION_PROPOSAL,
        object_id=authority_input.object_id,
        dataset_id=authority_input.dataset_id,
        dataset_version=authority_input.dataset_version,
        created_at=_utc_text(created_at),
        composed_at=_utc_text(checked_at),
        created_by=authority_input.created_by,
        producer=authority_input.producer,
        workspace_id=authority_input.workspace_id,
        schema_manifest_id=authority_input.schema_manifest_id,
        dataset_manifest_id=authority_input.dataset_manifest_id,
        dataset_eligibility_evidence_id=(
            authority_input.dataset_eligibility_evidence_id
        ),
        approval_evidence_ids=authority_input.approval_evidence_ids,
        task=task,
        usage_purpose=purpose,
        train_members=_split_members(canonical_members, "train"),
        validation_members=_split_members(canonical_members, "validation"),
        test_members=_split_members(canonical_members, "test"),
        source_fingerprint=source_fingerprint,
        content_fingerprint=content_fingerprint,
    )
    build_dataset_version_proposal_mapping(composition)
    return composition


def build_dataset_version_proposal_mapping(
    composition: ProductDatasetComposition,
) -> dict[str, Any]:
    """Build and Common-validate a draft mapping without governance mutation."""

    if type(composition) is not ProductDatasetComposition:
        raise ProductDatasetCompositionError("COMPOSITION_INVALID", "composition")
    _require_valid_composition(composition)
    members = tuple(sorted(composition.members, key=lambda value: value.candidate_id))
    payload: dict[str, Any] = {
        "schema_name": "dataset_version",
        "schema_version": "1.0.0",
        "object_id": composition.object_id,
        "created_at": composition.created_at,
        "created_by": composition.created_by,
        "producer": _producer_projection(composition.producer),
        "dataset_id": composition.dataset_id,
        "dataset_version": composition.dataset_version,
        "status": "draft",
        "usage_purpose": composition.usage_purpose,
        "task": composition.task,
        "lineage": [
            {
                "object_id": member.candidate_id,
                "schema_name": "learning_candidate",
                "schema_version": member.candidate_schema_version,
                "content_fingerprint": member.candidate_content_fingerprint,
            }
            for member in members
        ],
        "created_from": composition.source_fingerprint,
        "candidate_count": len(members),
        "split_manifest": {
            split: [member.candidate_id for member in _split_members(members, split)]
            for split in _SPLITS
        },
        "schema_manifest_id": composition.schema_manifest_id,
        "rights_summary": {"status": "pass", "exception_count": 0},
        "dataset_eligibility_evidence_id": (
            composition.dataset_eligibility_evidence_id
        ),
        "approval_evidence_ids": list(composition.approval_evidence_ids),
        "approved": False,
        "frozen": False,
        "training_allowed": False,
        "dataset_manifest_id": composition.dataset_manifest_id,
        "content_fingerprint": composition.content_fingerprint,
        "extensions": {
            "dohalm.product_dataset_composition": {
                "composition_id": composition.composition_id,
                "handoff_ids": [member.handoff_id for member in members],
                "member_bindings": [_identity_projection(member) for member in members],
                "review_evidence_references": [
                    member.review_evidence_reference for member in members
                ],
                "contract_package_version": composition.contract_package_version,
                "contract_policy_version": composition.contract_policy_version,
                "contract_authority_commit": composition.contract_authority_commit,
            }
        },
    }
    payload["split_manifest"]["group_keys"] = {
        member.candidate_id: member.group_key for member in members
    }
    if composition.workspace_id is not None:
        payload["workspace_id"] = composition.workspace_id
    validate_dataset_version(payload)
    return payload


def _require_valid_composition(composition: ProductDatasetComposition) -> None:
    members = tuple(sorted(composition.members, key=lambda value: value.candidate_id))
    if (
        composition.status
        is not ProductDatasetCompositionStatus.READY_FOR_DATASET_VERSION_PROPOSAL
        or composition.contract_package_version != COMMON_CONTRACT_PACKAGE_VERSION
        or composition.contract_policy_version != COMMON_CONTRACT_POLICY_VERSION
        or composition.contract_authority_commit != COMMON_CONTRACT_AUTHORITY_COMMIT
        or any(
            type(member) is not ProductDatasetCompositionMember for member in members
        )
        or any(member.workspace_id != composition.workspace_id for member in members)
        or any(member.task != composition.task for member in members)
        or any(member.usage_purpose != composition.usage_purpose for member in members)
    ):
        raise ProductDatasetCompositionError("COMPOSITION_INVALID", "composition")
    _require_member_invariants(members)
    expected_source = checksum_value([_source_projection(member) for member in members])
    expected_content = checksum_value(
        [_content_projection(member) for member in members]
    )
    identity = {
        "approval_evidence_ids": list(composition.approval_evidence_ids),
        "content_fingerprint": expected_content,
        "created_at": composition.created_at,
        "created_by": composition.created_by,
        "dataset_eligibility_evidence_id": (
            composition.dataset_eligibility_evidence_id
        ),
        "dataset_id": composition.dataset_id,
        "dataset_manifest_id": composition.dataset_manifest_id,
        "dataset_version": composition.dataset_version,
        "members": [_identity_projection(member) for member in members],
        "object_id": composition.object_id,
        "producer": _producer_projection(composition.producer),
        "schema_manifest_id": composition.schema_manifest_id,
        "source_fingerprint": expected_source,
        "task": composition.task,
        "usage_purpose": composition.usage_purpose,
        "workspace_id": composition.workspace_id,
    }
    if (
        composition.source_fingerprint != expected_source
        or composition.content_fingerprint != expected_content
        or composition.composition_id != f"composition:{checksum_value(identity)}"
    ):
        raise ProductDatasetCompositionError(
            "COMPOSITION_IDENTITY_MISMATCH",
            "identity",
        )


def _require_authority_input(value: object) -> None:
    if type(value) is not ProductDatasetCompositionAuthorityInput:
        raise ProductDatasetCompositionError("AUTHORITY_INPUT_INVALID", "authority")
    fields = (
        value.object_id,
        value.dataset_id,
        value.created_by,
        value.schema_manifest_id,
        value.dataset_manifest_id,
        value.dataset_eligibility_evidence_id,
    )
    if (
        any(not _is_reference(item) for item in fields)
        or not _is_semver(value.dataset_version)
        or type(value.producer) is not ProducerIdentity
        or not value.producer.name
        or not _is_semver(value.producer.version)
        or (value.workspace_id is not None and not _is_reference(value.workspace_id))
        or not _valid_references(value.approval_evidence_ids)
        or not isinstance(value.allocations, tuple)
        or not value.allocations
    ):
        raise ProductDatasetCompositionError("AUTHORITY_INPUT_INVALID", "authority")


def _allocation_index(
    allocations: tuple[ProductDatasetMemberAllocation, ...],
) -> dict[str, ProductDatasetMemberAllocation]:
    result: dict[str, ProductDatasetMemberAllocation] = {}
    for allocation in allocations:
        if (
            type(allocation) is not ProductDatasetMemberAllocation
            or not _is_reference(allocation.handoff_id)
            or allocation.split not in _SPLITS
            or not _is_reference(allocation.group_key)
            or allocation.handoff_id in result
        ):
            raise ProductDatasetCompositionError("ALLOCATION_INVALID", "allocation")
        result[allocation.handoff_id] = allocation
    return result


def _require_member_invariants(
    members: Sequence[ProductDatasetCompositionMember],
) -> None:
    for field, code in (
        ("handoff_id", "DUPLICATE_HANDOFF"),
        ("candidate_id", "DUPLICATE_CANDIDATE"),
        ("candidate_content_fingerprint", "DUPLICATE_CONTENT"),
    ):
        values = [getattr(member, field) for member in members]
        if len(values) != len(set(values)):
            raise ProductDatasetCompositionError(code, "members")
    for split in _SPLITS:
        if not any(member.split == split for member in members):
            raise ProductDatasetCompositionError("SPLIT_EMPTY", split)
    group_owners: dict[str, str] = {}
    for member in members:
        owner = group_owners.setdefault(member.group_key, member.split)
        if owner != member.split:
            raise ProductDatasetCompositionError("CROSS_SPLIT_GROUP", "group_key")


def _member(
    handoff: DatasetInclusionHandoff,
    allocation: ProductDatasetMemberAllocation,
) -> ProductDatasetCompositionMember:
    return ProductDatasetCompositionMember(
        handoff_id=handoff.handoff_id,
        candidate_id=handoff.candidate_id,
        candidate_schema_version=handoff.candidate_schema_version,
        candidate_content_fingerprint=handoff.candidate_content_fingerprint,
        review_evidence_reference=handoff.review_evidence_reference,
        reviewer_id=handoff.reviewer_id,
        reviewed_at=handoff.reviewed_at,
        split=allocation.split,
        group_key=allocation.group_key,
        source_type=handoff.source_type,
        task=handoff.task,
        usage_purpose=handoff.usage_purpose,
        workspace_id=handoff.workspace_id,
        rights_metadata_id=handoff.rights_metadata_id,
        training_eligibility_id=handoff.training_eligibility_id,
        candidate_producer=handoff.candidate_producer,
        rights_producer=handoff.rights_producer,
        eligibility_producer=handoff.eligibility_producer,
        input_references=handoff.input_references,
        output_references=handoff.output_references,
        parent_candidate_ids=handoff.parent_candidate_ids,
        candidate_review_evidence_ids=handoff.candidate_review_evidence_ids,
        consent_evidence_refs=handoff.consent_evidence_refs,
    )


def _identity_projection(member: ProductDatasetCompositionMember) -> dict[str, Any]:
    return {
        **_content_projection(member),
        "candidate_producer": _producer_projection(member.candidate_producer),
        "candidate_review_evidence_ids": list(member.candidate_review_evidence_ids),
        "consent_evidence_refs": list(member.consent_evidence_refs),
        "eligibility_producer": _producer_projection(member.eligibility_producer),
        "handoff_id": member.handoff_id,
        "input_references": [
            _reference_projection(value) for value in member.input_references
        ],
        "output_references": [
            _reference_projection(value) for value in member.output_references
        ],
        "parent_candidate_ids": list(member.parent_candidate_ids),
        "review_evidence_reference": member.review_evidence_reference,
        "reviewed_at": member.reviewed_at,
        "reviewer_id": member.reviewer_id,
        "rights_metadata_id": member.rights_metadata_id,
        "rights_producer": _producer_projection(member.rights_producer),
        "source_type": member.source_type,
        "training_eligibility_id": member.training_eligibility_id,
    }


def _content_projection(member: ProductDatasetCompositionMember) -> dict[str, str]:
    return {
        "candidate_content_fingerprint": member.candidate_content_fingerprint,
        "candidate_id": member.candidate_id,
        "group_key": member.group_key,
        "split": member.split,
    }


def _source_projection(member: ProductDatasetCompositionMember) -> dict[str, Any]:
    return {
        "candidate_id": member.candidate_id,
        "handoff_id": member.handoff_id,
        "input_references": [
            _reference_projection(value) for value in member.input_references
        ],
        "output_references": [
            _reference_projection(value) for value in member.output_references
        ],
        "parent_candidate_ids": list(member.parent_candidate_ids),
    }


def _reference_projection(value: CommonObjectReference) -> dict[str, Any]:
    return {
        "content_fingerprint": value.content_fingerprint,
        "object_id": value.object_id,
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
    }


def _producer_projection(value: ProducerIdentity) -> dict[str, str]:
    return {"name": value.name, "version": value.version}


def _split_members(
    members: Sequence[ProductDatasetCompositionMember], split: str
) -> tuple[ProductDatasetCompositionMember, ...]:
    return tuple(member for member in members if member.split == split)


def _single_value(values: Sequence[str] | Any, code: str) -> str:
    unique = set(values)
    if len(unique) != 1:
        raise ProductDatasetCompositionError(code, "members")
    return unique.pop()


def _valid_references(values: object) -> bool:
    return (
        isinstance(values, tuple)
        and bool(values)
        and all(_is_reference(value) for value in values)
        and len(values) == len(set(values))
    )


def _is_reference(value: object) -> bool:
    return isinstance(value, str) and _REFERENCE.fullmatch(value) is not None


def _is_semver(value: object) -> bool:
    return isinstance(value, str) and _SEMVER.fullmatch(value) is not None


def _require_time(value: object, stage: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProductDatasetCompositionError("TIMESTAMP_INVALID", stage)
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ProductDatasetComposition",
    "ProductDatasetCompositionAuthorityInput",
    "ProductDatasetCompositionError",
    "ProductDatasetCompositionMember",
    "ProductDatasetCompositionStatus",
    "ProductDatasetMemberAllocation",
    "build_dataset_version_proposal_mapping",
    "compose_product_dataset",
]
