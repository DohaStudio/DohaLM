"""Pure DatasetVersion proposal, review, and approval domain boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from .checksums import canonical_json_bytes, checksum_value
from .common_dataset_contracts import validate_dataset_version


@dataclass(frozen=True, order=True)
class DatasetVersionIdentity:
    """Canonical logical identity of one Common DatasetVersion."""

    object_id: str
    dataset_id: str
    dataset_version: str


@dataclass(frozen=True, order=True)
class DatasetGovernanceIssue:
    """A non-sensitive Dataset governance domain issue."""

    code: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


class DatasetGovernanceError(RuntimeError):
    """A proposal, transition, or approval failed closed."""

    contract_kind = "dataset_version"

    def __init__(
        self,
        code: str,
        stage: str,
        issues: tuple[DatasetGovernanceIssue, ...] = (),
    ) -> None:
        self.code = code
        self.stage = stage
        self.issues = issues
        issue_codes = ",".join(sorted({issue.code for issue in issues})) or "NONE"
        super().__init__(f"{code}:{stage}:{self.contract_kind}:{issue_codes}")


@dataclass(frozen=True, init=False)
class DatasetVersionProposal:
    """Immutable in-memory snapshot in the draft or reviewing state."""

    _canonical_payload: bytes = field(repr=False)
    _authority_root: bytes | None = field(repr=False, default=None)

    @classmethod
    def _create(
        cls,
        payload: Mapping[str, Any],
        *,
        authority_root: bytes | None = None,
    ) -> DatasetVersionProposal:
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_payload", _canonicalize(payload))
        object.__setattr__(value, "_authority_root", authority_root)
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return _decode_payload(self._canonical_payload)

    @property
    def identity(self) -> DatasetVersionIdentity:
        return _identity(self.payload)

    @property
    def status(self) -> str:
        return cast(str, self.payload["status"])

    @property
    def authority_root(self) -> dict[str, Any] | None:
        """Return the bounded v2 authority root, when this is a manifest proposal."""

        if self._authority_root is None:
            return None
        return _decode_payload(self._authority_root)


@dataclass(frozen=True, init=False)
class ApprovedDatasetVersion:
    """Immutable, publication-free result of an approved DatasetVersion."""

    identity: DatasetVersionIdentity
    fingerprint: str
    _canonical_payload: bytes = field(repr=False, compare=False)

    @classmethod
    def _create(cls, payload: Mapping[str, Any]) -> ApprovedDatasetVersion:
        value = object.__new__(cls)
        object.__setattr__(value, "identity", _identity(payload))
        object.__setattr__(value, "fingerprint", _fingerprint(payload))
        object.__setattr__(value, "_canonical_payload", _canonicalize(payload))
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return _decode_payload(self._canonical_payload)


def propose_dataset_version(payload: Mapping[str, Any]) -> DatasetVersionProposal:
    """Validate and snapshot an explicit draft DatasetVersion payload."""

    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"draft"}))
    return DatasetVersionProposal._create(payload)


def propose_manifest_reference_dataset_version(
    payload: Mapping[str, Any],
    *,
    authority_root: Mapping[str, Any],
) -> DatasetVersionProposal:
    """Validate a full draft while binding its bounded manifest-reference root."""

    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"draft"}))
    root = _canonicalize(authority_root)
    decoded = _decode_payload(root)
    if (
        decoded.get("schema_name") != "dataset_version_proposal_root"
        or decoded.get("schema_version") != "2.0.0"
        or decoded.get("status") != "draft"
        or any(
            decoded.get(name) != payload.get(name)
            for name in (
                "object_id",
                "dataset_id",
                "dataset_version",
            )
        )
    ):
        raise DatasetGovernanceError("PROPOSAL_ROOT_INVALID", "snapshot")
    return DatasetVersionProposal._create(payload, authority_root=root)


def begin_dataset_review(proposal: DatasetVersionProposal) -> DatasetVersionProposal:
    """Perform the only pre-approval transition: draft to reviewing."""

    payload = _proposal_payload(proposal, required_status="draft", stage="review")
    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"draft"}))
    payload["status"] = "reviewing"
    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"reviewing"}))
    return DatasetVersionProposal._create(payload)


def approve_dataset_version(
    proposal: DatasetVersionProposal,
    *,
    approval_evidence_ids: Sequence[str],
    existing: ApprovedDatasetVersion | None = None,
) -> ApprovedDatasetVersion:
    """Approve a reviewing proposal without persistence or publication effects."""

    payload = _proposal_payload(proposal, required_status="reviewing", stage="approval")
    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"reviewing"}))
    _require_approval_evidence(payload, approval_evidence_ids)

    payload["status"] = "approved"
    payload["approved"] = True
    validate_dataset_version(payload)
    _require_domain_valid(payload, allowed_statuses=frozenset({"approved"}))
    approved = ApprovedDatasetVersion._create(payload)
    return _resolve_existing_approval(approved, existing)


def _proposal_payload(
    proposal: DatasetVersionProposal,
    *,
    required_status: str,
    stage: str,
) -> dict[str, Any]:
    if (
        not isinstance(proposal, DatasetVersionProposal)
        or proposal.status != required_status
    ):
        raise DatasetGovernanceError("INVALID_STATE_TRANSITION", stage)
    return proposal.payload


def _require_domain_valid(
    payload: Mapping[str, Any],
    *,
    allowed_statuses: frozenset[str],
) -> None:
    issues = _domain_issues(payload, allowed_statuses=allowed_statuses)
    if issues:
        raise DatasetGovernanceError(
            "DATASET_DOMAIN_INVALID", "domain_validation", issues
        )


def _domain_issues(
    payload: Mapping[str, Any],
    *,
    allowed_statuses: frozenset[str],
) -> tuple[DatasetGovernanceIssue, ...]:
    issues: list[DatasetGovernanceIssue] = []
    status = payload["status"]
    if status not in allowed_statuses:
        issues.append(DatasetGovernanceIssue("INVALID_DATASET_STATE", "$.status"))

    expected_approved = status == "approved"
    if payload["approved"] is not expected_approved:
        issues.append(DatasetGovernanceIssue("APPROVAL_STATE_MISMATCH", "$.approved"))
    if payload["frozen"] is not False:
        issues.append(DatasetGovernanceIssue("FREEZE_NOT_ALLOWED", "$.frozen"))
    if payload["training_allowed"] is not False:
        issues.append(
            DatasetGovernanceIssue(
                "TRAINING_PERMISSION_NOT_ALLOWED", "$.training_allowed"
            )
        )
    if payload["rights_summary"] != {"status": "pass", "exception_count": 0}:
        issues.append(
            DatasetGovernanceIssue("RIGHTS_SUMMARY_NOT_PASS", "$.rights_summary")
        )

    split = payload["split_manifest"]
    split_names = ("train", "validation", "test")
    split_sets = {name: set(split[name]) for name in split_names}
    candidate_ids = set().union(*split_sets.values())
    if any(
        split_sets[left] & split_sets[right]
        for index, left in enumerate(split_names)
        for right in split_names[index + 1 :]
    ):
        issues.append(
            DatasetGovernanceIssue("SPLIT_CANDIDATE_LEAKAGE", "$.split_manifest")
        )
    if payload["candidate_count"] != len(candidate_ids):
        issues.append(
            DatasetGovernanceIssue("CANDIDATE_COUNT_MISMATCH", "$.candidate_count")
        )

    group_keys = split["group_keys"]
    if set(group_keys) != candidate_ids:
        issues.append(
            DatasetGovernanceIssue(
                "GROUP_KEY_COVERAGE_MISMATCH", "$.split_manifest.group_keys"
            )
        )
    else:
        group_owners: dict[str, str] = {}
        for split_name in split_names:
            for candidate_id in split_sets[split_name]:
                group_id = group_keys[candidate_id]
                owner = group_owners.setdefault(group_id, split_name)
                if owner != split_name:
                    issues.append(
                        DatasetGovernanceIssue(
                            "SPLIT_GROUP_LEAKAGE", "$.split_manifest.group_keys"
                        )
                    )
                    break

    return tuple(sorted(set(issues)))


def _require_approval_evidence(
    payload: Mapping[str, Any], approval_evidence_ids: Sequence[str]
) -> None:
    if isinstance(approval_evidence_ids, (str, bytes)):
        raise DatasetGovernanceError("APPROVAL_EVIDENCE_MISSING", "approval")
    provided = tuple(approval_evidence_ids)
    declared = tuple(payload["approval_evidence_ids"])
    if not provided or any(not isinstance(item, str) for item in provided):
        raise DatasetGovernanceError("APPROVAL_EVIDENCE_MISSING", "approval")
    if len(set(provided)) != len(provided) or set(provided) != set(declared):
        raise DatasetGovernanceError("APPROVAL_EVIDENCE_MISMATCH", "approval")


def _resolve_existing_approval(
    approved: ApprovedDatasetVersion,
    existing: ApprovedDatasetVersion | None,
) -> ApprovedDatasetVersion:
    if existing is None:
        return approved
    if not isinstance(existing, ApprovedDatasetVersion):
        raise DatasetGovernanceError("APPROVAL_RESULT_INVALID", "approval")
    if existing.identity != approved.identity:
        raise DatasetGovernanceError("APPROVAL_IDENTITY_MISMATCH", "approval")
    if existing.fingerprint != approved.fingerprint:
        raise DatasetGovernanceError("APPROVAL_FINGERPRINT_CONFLICT", "approval")
    return existing


def _identity(payload: Mapping[str, Any]) -> DatasetVersionIdentity:
    return DatasetVersionIdentity(
        object_id=cast(str, payload["object_id"]),
        dataset_id=cast(str, payload["dataset_id"]),
        dataset_version=cast(str, payload["dataset_version"]),
    )


def _canonicalize(payload: Mapping[str, Any]) -> bytes:
    try:
        return canonical_json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise DatasetGovernanceError("CANONICALIZATION_FAILED", "snapshot") from exc


def _fingerprint(payload: Mapping[str, Any]) -> str:
    try:
        return checksum_value(payload)
    except (TypeError, ValueError) as exc:
        raise DatasetGovernanceError("CANONICALIZATION_FAILED", "fingerprint") from exc


def _decode_payload(value: bytes) -> dict[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise DatasetGovernanceError("APPROVAL_RESULT_INVALID", "snapshot")
    return payload


__all__ = [
    "ApprovedDatasetVersion",
    "DatasetGovernanceError",
    "DatasetGovernanceIssue",
    "DatasetVersionIdentity",
    "DatasetVersionProposal",
    "approve_dataset_version",
    "begin_dataset_review",
    "propose_dataset_version",
    "propose_manifest_reference_dataset_version",
]
