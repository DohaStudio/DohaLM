from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.data.checksums import canonical_json_bytes, sha256_bytes
from src.data.dataset_publication import (
    DatasetPublicationError,
    DatasetPublicationResult,
)
from src.training.dataset_publication_authority_bridge import (
    DatasetPublicationAuthorityBridge,
    InternalProductionDatasetEligibility,
)
from src.training.errors import TrainingError
from src.training.postgres_production_authority_provisioning import (
    PostgresProductionAuthorityProvisioning,
)
from src.training.production_authority_provisioning import (
    AuthorityProvisioningIdentity,
    ConfigAuthorityProvisionCommand,
    DatasetAuthorityRegistrationResult,
    PrincipalProvisionCommand,
    ProductionAuthorityProvisioningPackage,
)
from src.training.production_intent_authority import (
    TrainingIntentSubmitterAuthorityRecord,
)


NOW = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
SOURCE = "a" * 40


def _principal(reference: str = "issuer:operator") -> PrincipalProvisionCommand:
    return PrincipalProvisionCommand(
        authority_id=str(uuid4()),
        domain_key=reference,
        payload=canonical_json_bytes({"principal": reference}),
        source_commit=SOURCE,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=1),
        principal_reference=reference,
        event_id=str(uuid4()),
        correlation_reference="correlation:provisioning-test",
        evidence_reference="evidence:provisioning-test",
    )


def _identity(authority_id: str | None = None) -> AuthorityProvisioningIdentity:
    return AuthorityProvisioningIdentity(
        authority_id=authority_id or str(uuid4()),
        domain_key="authority:test",
        payload_fingerprint="sha256:" + "1" * 64,
        state="current",
        projection_version=1,
    )


class _Cursor:
    def __init__(self, row: tuple[object, ...], names: tuple[str, ...]) -> None:
        self._row = row
        self.description = tuple(SimpleNamespace(name=name) for name in names)

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...]):
        self.calls.append((sql, parameters))
        return _Cursor(
            (
                parameters[0],
                parameters[1],
                parameters[3],
                "current",
                1,
            ),
            (
                "authority_id",
                "domain_key",
                "payload_sha256",
                "authority_state",
                "projection_version",
            ),
        )


class _Factory:
    role = "dohalm_training_authority_producer"

    def __init__(self) -> None:
        self.connection = _Connection()

    @contextmanager
    def transaction(self, *, isolation: str, read_only: bool):
        assert isolation == "READ COMMITTED"
        assert read_only is False
        yield self.connection


def test_postgres_adapter_uses_only_restricted_family_function() -> None:
    factory = _Factory()
    adapter = PostgresProductionAuthorityProvisioning(factory)
    command = _principal()
    result = adapter.provision_issuer(command)
    assert result.authority_id == command.authority_id
    sql, parameters = factory.connection.calls[0]
    assert "provision_training_issuer" in sql
    assert "INSERT" not in sql.upper()
    assert parameters[2] == command.payload
    assert parameters[3] == sha256_bytes(command.payload)
    source = Path(
        "src/training/postgres_production_authority_provisioning.py"
    ).read_text(encoding="utf-8")
    assert "INSERT INTO" not in source.upper()
    assert "UPDATE " not in source.upper()
    assert "DELETE FROM" not in source.upper()


def test_principal_and_package_reject_role_collision() -> None:
    with pytest.raises(TrainingError, match="PRODUCTION_AUTHORITY_INPUT_INVALID"):
        _principal("")
    shared = str(uuid4())
    submitter = TrainingIntentSubmitterAuthorityRecord(
        authority_id=shared,
        domain_key="submitter:test",
        state="current",
        state_effective_at=NOW,
        created_at=NOW,
        valid_from=NOW,
        valid_until=None,
        projection_version=1,
    )
    dataset = DatasetAuthorityRegistrationResult(
        version=_identity(),
        manifest=_identity(),
        pair=_identity(),
        dataset_version_id="dataset-version-test",
        dataset_manifest_id="dataset-manifest-test",
        pair_fingerprint="sha256:" + "2" * 64,
    )
    with pytest.raises(TrainingError, match="PRODUCTION_AUTHORITY_ROLE_COLLISION"):
        ProductionAuthorityProvisioningPackage(
            submitter=submitter,
            issuer=_identity(shared),
            approver=_identity(),
            dataset=dataset,
            config=_identity(),
            readiness=_identity(),
        )


class _DatasetPort:
    def __init__(self) -> None:
        self.command = None
        self.commands = []

    def register_dataset_publication(self, command):
        self.command = command
        self.commands.append(command)
        return DatasetAuthorityRegistrationResult(
            version=AuthorityProvisioningIdentity(
                command.version_authority_id,
                command.version_domain_key,
                sha256_bytes(command.version_payload),
                "current",
                1,
            ),
            manifest=AuthorityProvisioningIdentity(
                command.manifest_authority_id,
                command.manifest_domain_key,
                sha256_bytes(command.manifest_payload),
                "current",
                1,
            ),
            pair=AuthorityProvisioningIdentity(
                command.pair_authority_id,
                command.pair_domain_key,
                sha256_bytes(command.pair_payload),
                "current",
                1,
            ),
            dataset_version_id=command.dataset_version_id,
            dataset_manifest_id=command.dataset_manifest_id,
            pair_fingerprint=command.pair_fingerprint,
        )


def _publication() -> DatasetPublicationResult:
    version = {
        "object_id": "dataset-version-test",
        "dataset_id": "dataset-test",
        "dataset_version": "v1",
        "status": "frozen",
        "training_allowed": True,
    }
    manifest = {
        "object_id": "dataset-manifest-test",
        "manifest_status": "issued",
        "training_allowed": True,
    }
    return DatasetPublicationResult._create(
        version,
        manifest,
        storage_key="a" * 64,
        pair_fingerprint="sha256:" + "3" * 64,
        published=True,
    )


def test_dataset_bridge_registers_exact_filesystem_result_without_republication() -> (
    None
):
    port = _DatasetPort()
    bridge = DatasetPublicationAuthorityBridge(port)
    values = dict(
        eligibility=InternalProductionDatasetEligibility(
            reference="eligibility:candidate-a",
            source_lineage_reference="lineage:candidate-a",
            internal_training_allowed=True,
            commercial_usage_allowed=False,
            redistribution_allowed=False,
        ),
        source_commit=SOURCE,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=1),
        correlation_reference="correlation:Dataset-bridge",
    )
    result = bridge.register(_publication(), **values)
    replay = bridge.register(_publication(), **values)
    assert result.pair_fingerprint == "sha256:" + "3" * 64
    assert replay == result
    assert port.commands[0] == port.commands[1]
    assert port.command.version_payload == canonical_json_bytes(
        _publication().dataset_version
    )
    assert port.command.manifest_payload == canonical_json_bytes(
        _publication().dataset_manifest
    )


def test_dataset_bridge_rejects_commercial_or_unfrozen_material() -> None:
    with pytest.raises(
        DatasetPublicationError, match="PRODUCTION_DATASET_ELIGIBILITY_INVALID"
    ):
        InternalProductionDatasetEligibility(
            reference="eligibility:test",
            source_lineage_reference="lineage:test",
            internal_training_allowed=True,
            commercial_usage_allowed=True,
            redistribution_allowed=False,
        )


def test_config_command_fingerprint_is_exact_canonical_bytes() -> None:
    payload = canonical_json_bytes({"execution_scope": "production_internal"})
    command = ConfigAuthorityProvisionCommand(
        authority_id=str(uuid4()),
        domain_key="config:production-test",
        canonical_payload=payload,
        source_commit=SOURCE,
        valid_from=NOW,
        valid_until=None,
        event_id=str(uuid4()),
        correlation_reference="correlation:config-test",
        evidence_reference="evidence:config-test",
    )
    assert command.payload_fingerprint == sha256_bytes(payload)
