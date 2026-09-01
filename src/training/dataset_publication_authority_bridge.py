"""Bridge a verified Product Dataset publication into PostgreSQL authorities."""

from __future__ import annotations

from datetime import datetime

from src.data.checksums import sha256_bytes
from src.data.dataset_publication import DatasetPublicationResult
from src.data.product_dataset_authority_registration import (
    InternalProductionDatasetEligibility,
    build_product_dataset_authority_registration,
)

from .errors import TrainingError
from .production_authority_provisioning import (
    DatasetAuthorityRegistrationCommand,
    DatasetAuthorityRegistrationResult,
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


__all__ = [
    "DatasetPublicationAuthorityBridge",
    "InternalProductionDatasetEligibility",
]
