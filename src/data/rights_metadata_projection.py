"""Deterministic DohaRights read-model to Common RightsMetadata projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from .common_dataset_contracts import validate_rights_metadata

_FP = re.compile(r"sha256:[0-9a-f]{64}")
_EVIDENCE_TYPE = re.compile(r"[a-z][a-z0-9_]{2,63}")
_RIGHTS_PRODUCER = {"name": "DohaRights", "version": "0.2.0"}


class RightsMetadataProjectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}:rights_metadata_projection")


@dataclass(frozen=True, slots=True)
class TypedRightsEvidence:
    reference_id: str
    evidence_type: str

    def __post_init__(self) -> None:
        if (
            not _common_id(self.reference_id)
            or _EVIDENCE_TYPE.fullmatch(self.evidence_type) is None
        ):
            raise RightsMetadataProjectionError("RIGHTS_EVIDENCE_INVALID")


@dataclass(frozen=True, slots=True)
class AuthorityRightsMetadata:
    dataset_source_identity: str
    subject_kind: str
    bound_identity: str
    rights_status: str
    source_type: str
    user_created: bool
    generated: bool
    reference: bool
    uploaded: bool
    external: bool
    analysis_allowed: bool
    derivative_generation_allowed: bool
    retention_mode: str
    retention_scope: str
    retention_expires_at: datetime | None
    consent_evidence_references: tuple[str, ...]
    jurisdiction: str
    reviewer_authority_id: str
    reviewed_at: datetime
    producer_authority_id: str
    effective_at: datetime
    current_use_authorized: bool
    current_use_scope: str
    fresh_acquisition_required: bool
    existing_material_reuse: bool
    historical_acquisition_receipt: str
    provider_reacquisition_requirement_found: bool
    typed_evidence_references: tuple[TypedRightsEvidence, ...]

    def __post_init__(self) -> None:
        booleans = (
            self.user_created,
            self.generated,
            self.reference,
            self.uploaded,
            self.external,
            self.analysis_allowed,
            self.derivative_generation_allowed,
            self.current_use_authorized,
            self.fresh_acquisition_required,
            self.existing_material_reuse,
            self.provider_reacquisition_requirement_found,
        )
        if (
            self.dataset_source_identity.strip() == ""
            or self.subject_kind
            not in {"source_dataset", "dataset_version", "derived_artifact"}
            or self.bound_identity.strip() == ""
            or self.rights_status not in {"approved", "approved_limited", "rejected"}
            or self.source_type
            not in {
                "user_created",
                "generated",
                "reference",
                "uploaded",
                "external",
                "mixed",
            }
            or not all(type(value) is bool for value in booleans)
            or not _uuid(self.reviewer_authority_id)
            or not _uuid(self.producer_authority_id)
            or self.reviewer_authority_id == self.producer_authority_id
            or not _aware(self.reviewed_at)
            or not _aware(self.effective_at)
            or not self.jurisdiction.strip()
            or not self.current_use_scope.strip()
            or not self.typed_evidence_references
            or len({value.reference_id for value in self.typed_evidence_references})
            != len(self.typed_evidence_references)
            or any(not _common_id(value) for value in self.consent_evidence_references)
        ):
            raise RightsMetadataProjectionError("RIGHTS_METADATA_FACTS_INVALID")
        if self.retention_mode == "indefinite_while_current":
            if self.retention_expires_at is not None:
                raise RightsMetadataProjectionError("RIGHTS_RETENTION_INVALID")
        elif self.retention_mode == "fixed_expiry":
            if not _aware(self.retention_expires_at):
                raise RightsMetadataProjectionError("RIGHTS_RETENTION_INVALID")
        else:
            raise RightsMetadataProjectionError("RIGHTS_RETENTION_INVALID")
        if self.retention_scope not in {"training", "runtime"}:
            raise RightsMetadataProjectionError("RIGHTS_RETENTION_INVALID")


class RightsRead(Protocol):
    record_id: str
    record_fingerprint: str
    subject_id: str
    source_authority_id: str
    internal_training: bool
    commercial_use: bool
    redistribution: bool
    model_publication: bool
    metadata: AuthorityRightsMetadata | None
    token: object


def project_common_rights_metadata(rights: RightsRead) -> dict[str, object]:
    """Materialize Common v1 only from authenticated owner-issued facts."""

    facts = rights.metadata
    token_fingerprint = getattr(rights.token, "token_fingerprint", None)
    if (
        facts is None
        or not _uuid(rights.record_id)
        or not _uuid(rights.subject_id)
        or not _uuid(rights.source_authority_id)
        or _FP.fullmatch(rights.record_fingerprint) is None
        or not isinstance(token_fingerprint, str)
        or _FP.fullmatch(token_fingerprint) is None
        or facts.current_use_authorized is not True
        or rights.internal_training is not True
    ):
        raise RightsMetadataProjectionError("RIGHTS_AUTHORITY_FACTS_MISSING")
    retention: bool | dict[str, object]
    if facts.retention_mode == "indefinite_while_current":
        retention = True
    else:
        if facts.retention_expires_at is None:
            raise RightsMetadataProjectionError("RIGHTS_RETENTION_INVALID")
        retention = {
            "allowed": True,
            "expires_at": _utc(facts.retention_expires_at),
            "scope": facts.retention_scope,
        }
    rights_id = f"rights:{rights.record_id}"
    payload: dict[str, object] = {
        "schema_name": "rights_metadata",
        "schema_version": "1.0.0",
        "object_id": rights_id,
        "created_at": _utc(facts.effective_at),
        "created_by": f"authority:{facts.producer_authority_id}",
        "producer": dict(_RIGHTS_PRODUCER),
        "rights_metadata_id": rights_id,
        "source_type": facts.source_type,
        "rights_status": facts.rights_status,
        "user_created": facts.user_created,
        "generated": facts.generated,
        "reference": facts.reference,
        "uploaded": facts.uploaded,
        "external": facts.external,
        "analysis_allowed": facts.analysis_allowed,
        "training_allowed": rights.internal_training,
        "redistribution_allowed": rights.redistribution,
        "retention_allowed": retention,
        "derivative_generation_allowed": facts.derivative_generation_allowed,
        "consent_evidence_refs": list(facts.consent_evidence_references),
        "jurisdiction": facts.jurisdiction,
        "reviewed_at": _utc(facts.reviewed_at),
        "reviewed_by": f"authority:{facts.reviewer_authority_id}",
        "extensions": {
            "doharights.current_use": {
                "rights_subject_id": rights.subject_id,
                "dataset_source_identity": facts.dataset_source_identity,
                "subject_kind": facts.subject_kind,
                "bound_identity": facts.bound_identity,
                "rights_record_fingerprint": rights.record_fingerprint,
                "rights_source_authority_id": rights.source_authority_id,
                "rights_source_token_fingerprint": token_fingerprint,
                "current_use_authorized": facts.current_use_authorized,
                "current_use_scope": facts.current_use_scope,
                "fresh_acquisition_required": facts.fresh_acquisition_required,
                "existing_material_reuse": facts.existing_material_reuse,
                "historical_acquisition_receipt": facts.historical_acquisition_receipt,
                "provider_reacquisition_requirement_found": (
                    facts.provider_reacquisition_requirement_found
                ),
                "commercial_use_allowed": rights.commercial_use,
                "external_model_publication_allowed": rights.model_publication,
                "consent_basis": (
                    "evidence_references"
                    if facts.consent_evidence_references
                    else "not_applicable"
                ),
                "typed_evidence_references": [
                    {
                        "reference_id": value.reference_id,
                        "evidence_type": value.evidence_type,
                    }
                    for value in facts.typed_evidence_references
                ],
            }
        },
    }
    validate_rights_metadata(payload)
    return payload


def _common_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 2 <= len(value) <= 128
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9._:-]+", value) is not None
    )


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "AuthorityRightsMetadata",
    "RightsMetadataProjectionError",
    "TypedRightsEvidence",
    "project_common_rights_metadata",
]
