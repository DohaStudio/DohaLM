"""Bridge a verified Product Dataset publication into PostgreSQL authorities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from src.data.checksums import canonical_json_bytes, sha256_bytes
from src.data.dataset_publication import DatasetPublicationResult

from .errors import TrainingError
from .production_authority_provisioning import (
    DatasetAuthorityRegistrationCommand,
    DatasetAuthorityRegistrationResult,
    ProductionAuthorityProvisioningPort,
)


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


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
            raise _error(
                "PRODUCTION_DATASET_ELIGIBILITY_INVALID",
                "Internal non-commercial Dataset eligibility is required.",
            )


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
        version = publication.dataset_version
        manifest = publication.dataset_manifest
        if (
            version.get("training_allowed") is not True
            or manifest.get("training_allowed") is not True
            or version.get("status") != "frozen"
            or manifest.get("manifest_status") != "issued"
        ):
            raise _error(
                "PRODUCTION_DATASET_ELIGIBILITY_INVALID",
                "Only a frozen Training-allowed publication can be registered.",
            )
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
            return str(
                uuid5(NAMESPACE_URL, f"dohalm:production-authority:{kind}:{key}")
            )

        command = DatasetAuthorityRegistrationCommand(
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
        result = self._authorities.register_dataset_publication(command)
        if (
            result.dataset_version_id != version["object_id"]
            or result.dataset_manifest_id != manifest["object_id"]
            or result.pair_fingerprint != publication.pair_fingerprint
            or result.version.payload_fingerprint != sha256_bytes(version_payload)
            or result.manifest.payload_fingerprint != sha256_bytes(manifest_payload)
            or result.pair.payload_fingerprint != sha256_bytes(pair_payload)
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
