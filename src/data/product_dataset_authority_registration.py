"""Pure Product Dataset publication-to-authority registration material."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .checksums import canonical_json_bytes, sha256_bytes
from .dataset_publication import DatasetPublicationError, DatasetPublicationResult


def _error(code: str) -> DatasetPublicationError:
    return DatasetPublicationError(code, "authority_registration")


@dataclass(frozen=True, slots=True)
class InternalProductionDatasetEligibility:
    reference: str
    source_lineage_reference: str
    internal_training_allowed: bool
    commercial_usage_allowed: bool
    redistribution_allowed: bool

    def __post_init__(self) -> None:
        if (
            not self.reference
            or not self.source_lineage_reference
            or self.internal_training_allowed is not True
            or self.commercial_usage_allowed is not False
            or self.redistribution_allowed is not False
        ):
            raise _error("PRODUCTION_DATASET_ELIGIBILITY_INVALID")


@dataclass(frozen=True, slots=True, repr=False)
class ProductDatasetAuthorityRegistration:
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

    def __repr__(self) -> str:
        return "ProductDatasetAuthorityRegistration(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class ProductDatasetPairReplacement:
    """One immutable v2 authority payload replacing a historical pair authority."""

    previous_pair_authority_id: str
    previous_pair_fingerprint: str
    pair_authority_id: str
    pair_domain_key: str
    pair_payload: bytes
    pair_payload_fingerprint: str
    pair_fingerprint: str
    dataset_version_id: str
    dataset_manifest_id: str
    source_commit: str
    publication_scenario: str
    valid_until: datetime | None
    pair_event_id: str
    supersede_event_id: str
    correlation_reference: str
    eligibility_reference: str

    def __repr__(self) -> str:
        return "ProductDatasetPairReplacement(<redacted>)"


def _snapshot_sequence(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)):
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID")
    try:
        value = json.loads(canonical_json_bytes(list(values)))
    except (TypeError, ValueError):
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID") from None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID")
    return value


def build_compatible_product_dataset_pair_replacement(
    publication: DatasetPublicationResult,
    *,
    previous_pair_authority_id: str,
    eligibility: InternalProductionDatasetEligibility,
    upstream_objects: Sequence[Mapping[str, Any]],
    evaluated_at: str,
    expected_split_id: str,
    artifact_references: Sequence[Mapping[str, Any]],
    source_commit: str,
    valid_until: datetime | None,
    correlation_reference: str,
) -> ProductDatasetPairReplacement:
    """Build a C3-complete pair payload without changing published Dataset bytes."""

    if (
        type(publication) is not DatasetPublicationResult
        or type(eligibility) is not InternalProductionDatasetEligibility
        or not previous_pair_authority_id
        or not evaluated_at
        or not expected_split_id
    ):
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID")
    version = publication.dataset_version
    manifest = publication.dataset_manifest
    upstream = _snapshot_sequence(upstream_objects)
    artifacts = _snapshot_sequence(artifact_references)
    try:
        evaluation_time = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    except ValueError:
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID") from None
    if (
        not upstream
        or evaluation_time.tzinfo is None
        or evaluation_time.utcoffset() is None
        or version.get("status") != "frozen"
        or version.get("training_allowed") is not True
        or manifest.get("manifest_status") != "issued"
        or manifest.get("training_allowed") is not True
        or expected_split_id != manifest.get("split_id")
        or artifacts != manifest.get("object_file_artifact_refs")
    ):
        raise _error("PRODUCTION_DATASET_PAIR_COMPATIBILITY_INVALID")
    payload = canonical_json_bytes(
        {
            "artifact_references": artifacts,
            "dataset_manifest_id": manifest["object_id"],
            "dataset_version_id": version["object_id"],
            "eligibility_reference": eligibility.reference,
            "evaluated_at": evaluated_at,
            "expected_split_id": expected_split_id,
            "pair_fingerprint": publication.pair_fingerprint,
            "payload_schema": "dataset_pair_payload_v2",
            "publication_scenario": "internal-production-training-c3-compatible",
            "source_lineage_reference": eligibility.source_lineage_reference,
            "upstream_objects": upstream,
        }
    )
    payload_fingerprint = sha256_bytes(payload)
    key = f"dataset-pair-v2:{payload_fingerprint.removeprefix('sha256:')}"

    def stable_uuid(kind: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"dohalm:production-authority:{kind}:{key}"))

    return ProductDatasetPairReplacement(
        previous_pair_authority_id=previous_pair_authority_id,
        previous_pair_fingerprint=publication.pair_fingerprint,
        pair_authority_id=stable_uuid("authority"),
        pair_domain_key=key,
        pair_payload=payload,
        pair_payload_fingerprint=payload_fingerprint,
        pair_fingerprint=publication.pair_fingerprint,
        dataset_version_id=version["object_id"],
        dataset_manifest_id=manifest["object_id"],
        source_commit=source_commit,
        publication_scenario="internal-production-training-c3-compatible",
        valid_until=valid_until,
        pair_event_id=stable_uuid("event:published"),
        supersede_event_id=stable_uuid("event:superseded"),
        correlation_reference=correlation_reference,
        eligibility_reference=eligibility.reference,
    )


def build_product_dataset_authority_registration(
    publication: DatasetPublicationResult,
    *,
    eligibility: InternalProductionDatasetEligibility,
    source_commit: str,
    valid_from: datetime,
    valid_until: datetime | None,
    correlation_reference: str,
) -> ProductDatasetAuthorityRegistration:
    """Freeze an existing publication; never reads or republishes Dataset bytes."""

    if (
        type(publication) is not DatasetPublicationResult
        or type(eligibility) is not InternalProductionDatasetEligibility
    ):
        raise _error("PRODUCTION_DATASET_REGISTRATION_INVALID")
    version = publication.dataset_version
    manifest = publication.dataset_manifest
    if (
        version.get("training_allowed") is not True
        or manifest.get("training_allowed") is not True
        or version.get("status") != "frozen"
        or manifest.get("manifest_status") != "issued"
    ):
        raise _error("PRODUCTION_DATASET_ELIGIBILITY_INVALID")
    version_payload = canonical_json_bytes(version)
    manifest_payload = canonical_json_bytes(manifest)
    pair_payload = canonical_json_bytes(
        {
            "dataset_manifest_id": manifest["object_id"],
            "dataset_version_id": version["object_id"],
            "eligibility_reference": eligibility.reference,
            "pair_fingerprint": publication.pair_fingerprint,
            "publication_scenario": "internal-production-training",
            "source_lineage_reference": eligibility.source_lineage_reference,
        }
    )
    short_pair = publication.pair_fingerprint.removeprefix("sha256:")
    version_key = f"dataset-version:{version['object_id']}"
    manifest_key = f"dataset-manifest:{manifest['object_id']}"
    pair_key = f"dataset-pair:{short_pair}"

    def stable_uuid(kind: str, key: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"dohalm:production-authority:{kind}:{key}"))

    return ProductDatasetAuthorityRegistration(
        version_authority_id=stable_uuid("authority", version_key),
        manifest_authority_id=stable_uuid("authority", manifest_key),
        pair_authority_id=stable_uuid("authority", pair_key),
        version_domain_key=version_key,
        manifest_domain_key=manifest_key,
        pair_domain_key=pair_key,
        version_payload=version_payload,
        manifest_payload=manifest_payload,
        pair_payload=pair_payload,
        dataset_version_id=version["object_id"],
        dataset_manifest_id=manifest["object_id"],
        pair_fingerprint=publication.pair_fingerprint,
        source_commit=source_commit,
        publication_scenario="internal-production-training",
        eligibility_reference=eligibility.reference,
        source_lineage_reference=eligibility.source_lineage_reference,
        valid_from=valid_from,
        valid_until=valid_until,
        version_event_id=stable_uuid("event", version_key),
        manifest_event_id=stable_uuid("event", manifest_key),
        pair_event_id=stable_uuid("event", pair_key),
        correlation_reference=correlation_reference,
    )


__all__ = [
    "InternalProductionDatasetEligibility",
    "ProductDatasetAuthorityRegistration",
    "ProductDatasetPairReplacement",
    "build_compatible_product_dataset_pair_replacement",
    "build_product_dataset_authority_registration",
]
