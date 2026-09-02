"""Bridge a verified Product Dataset publication into PostgreSQL authorities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.data.checksums import canonical_json_bytes, sha256_bytes
from src.data.dataset_publication import DatasetPublicationResult
from src.data.product_dataset_authority_registration import (
    InternalProductionDatasetEligibility,
    build_compatible_product_dataset_pair_replacement,
    build_product_dataset_authority_registration,
)

from .errors import TrainingError
from .production_authority_provisioning import (
    DatasetAuthorityRegistrationCommand,
    DatasetAuthorityRegistrationResult,
    DatasetPairReplacementCommand,
    DatasetPairReplacementResult,
    ProductionAuthorityProvisioningPort,
)


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


class DatasetPublicationAuthorityBridge:
    """Register one already-published pair atomically; never republishes bytes."""

    def __init__(self, authorities: ProductionAuthorityProvisioningPort) -> None:
        self._authorities = authorities

    def register(
        self,
        publication: DatasetPublicationResult,
        *,
        eligibility: InternalProductionDatasetEligibility,
        source_commit: str,
        valid_from: datetime,
        valid_until: datetime | None,
        correlation_reference: str,
    ) -> DatasetAuthorityRegistrationResult:
        if (
            type(publication) is not DatasetPublicationResult
            or type(eligibility) is not InternalProductionDatasetEligibility
        ):
            raise _error(
                "PRODUCTION_DATASET_REGISTRATION_INVALID",
                "A verified Product Dataset publication result is required.",
            )
        material = build_product_dataset_authority_registration(
            publication,
            eligibility=eligibility,
            source_commit=source_commit,
            valid_from=valid_from,
            valid_until=valid_until,
            correlation_reference=correlation_reference,
        )
        command = DatasetAuthorityRegistrationCommand(
            version_authority_id=material.version_authority_id,
            manifest_authority_id=material.manifest_authority_id,
            pair_authority_id=material.pair_authority_id,
            version_domain_key=material.version_domain_key,
            manifest_domain_key=material.manifest_domain_key,
            pair_domain_key=material.pair_domain_key,
            version_payload=material.version_payload,
            manifest_payload=material.manifest_payload,
            pair_payload=material.pair_payload,
            dataset_version_id=material.dataset_version_id,
            dataset_manifest_id=material.dataset_manifest_id,
            pair_fingerprint=material.pair_fingerprint,
            source_commit=material.source_commit,
            publication_scenario=material.publication_scenario,
            eligibility_reference=material.eligibility_reference,
            source_lineage_reference=material.source_lineage_reference,
            valid_from=material.valid_from,
            valid_until=material.valid_until,
            version_event_id=material.version_event_id,
            manifest_event_id=material.manifest_event_id,
            pair_event_id=material.pair_event_id,
            correlation_reference=material.correlation_reference,
        )
        result = self._authorities.register_dataset_publication(command)
        version = publication.dataset_version
        manifest = publication.dataset_manifest
        if (
            result.dataset_version_id != version["object_id"]
            or result.dataset_manifest_id != manifest["object_id"]
            or result.pair_fingerprint != publication.pair_fingerprint
            or result.version.payload_fingerprint
            != sha256_bytes(material.version_payload)
            or result.manifest.payload_fingerprint
            != sha256_bytes(material.manifest_payload)
            or result.pair.payload_fingerprint != sha256_bytes(material.pair_payload)
        ):
            raise _error(
                "PRODUCTION_DATASET_REGISTRATION_MISMATCH",
                "PostgreSQL authority registration differs from Product publication.",
            )
        return result

    def replace_pair(
        self,
        publication: DatasetPublicationResult,
        *,
        previous_pair_authority_id: str,
        expected_previous_projection_version: int,
        version_authority_id: str,
        manifest_authority_id: str,
        eligibility: InternalProductionDatasetEligibility,
        upstream_objects: Sequence[Mapping[str, Any]],
        evaluated_at: str,
        expected_split_id: str,
        artifact_references: Sequence[Mapping[str, Any]],
        source_commit: str,
        valid_until: datetime | None,
        correlation_reference: str,
    ) -> DatasetPairReplacementResult:
        material = build_compatible_product_dataset_pair_replacement(
            publication,
            previous_pair_authority_id=previous_pair_authority_id,
            eligibility=eligibility,
            upstream_objects=upstream_objects,
            evaluated_at=evaluated_at,
            expected_split_id=expected_split_id,
            artifact_references=artifact_references,
            source_commit=source_commit,
            valid_until=valid_until,
            correlation_reference=correlation_reference,
        )
        command = DatasetPairReplacementCommand(
            previous_pair_authority_id=material.previous_pair_authority_id,
            expected_previous_projection_version=expected_previous_projection_version,
            version_authority_id=version_authority_id,
            manifest_authority_id=manifest_authority_id,
            pair_authority_id=material.pair_authority_id,
            pair_domain_key=material.pair_domain_key,
            version_payload=canonical_json_bytes(publication.dataset_version),
            manifest_payload=canonical_json_bytes(publication.dataset_manifest),
            pair_payload=material.pair_payload,
            dataset_version_id=material.dataset_version_id,
            dataset_manifest_id=material.dataset_manifest_id,
            pair_fingerprint=material.pair_fingerprint,
            source_commit=material.source_commit,
            publication_scenario=material.publication_scenario,
            valid_until=material.valid_until,
            pair_event_id=material.pair_event_id,
            supersede_event_id=material.supersede_event_id,
            correlation_reference=material.correlation_reference,
            evidence_reference=material.eligibility_reference,
        )
        result = self._authorities.replace_dataset_pair(command)
        if (
            result.previous_pair_authority_id != previous_pair_authority_id
            or result.pair.authority_id != material.pair_authority_id
            or result.pair.payload_fingerprint != material.pair_payload_fingerprint
            or result.pair_fingerprint != publication.pair_fingerprint
            or result.version.authority_id != version_authority_id
            or result.manifest.authority_id != manifest_authority_id
        ):
            raise _error(
                "PRODUCTION_DATASET_PAIR_REPLACEMENT_MISMATCH",
                "PostgreSQL pair replacement differs from approved material.",
            )
        return result


__all__ = [
    "DatasetPublicationAuthorityBridge",
    "InternalProductionDatasetEligibility",
]
