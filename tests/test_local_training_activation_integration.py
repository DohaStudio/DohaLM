from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from src.training.local_activation import (
    LocalDockerConfiguration,
    LocalSingleUserActivationConfiguration,
    LocalDatasetMappingConfiguration,
    LocalDurablePostgresBootstrapper,
    inspect_local_training_readiness,
    load_local_role_credentials,
)


LABEL = "com.dohastudio.local-training.activation"


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


@pytest.fixture
def external_credential_root() -> object:
    with tempfile.TemporaryDirectory(prefix="dohalm-local-integration-") as root:
        yield Path(root)


@pytest.mark.integration
def test_local_durable_bootstrap_readiness_and_explicit_cleanup(
    tmp_path: Path, external_credential_root: Path
) -> None:
    suffix = uuid.uuid4().hex[:12]
    correlation = f"activation-{suffix}"
    credential_directory = external_credential_root / "credentials"
    credential_directory.mkdir()
    credential_values = {
        "migration_owner": secrets.token_urlsafe(32),
        "producer": secrets.token_urlsafe(32),
        "resolver": secrets.token_urlsafe(32),
        "journal": secrets.token_urlsafe(32),
    }
    for role, value in credential_values.items():
        (credential_directory / f"{role}.password").write_text(value, encoding="utf-8")

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    manifest = dataset_root / "manifest.json"
    manifest.write_text('{"synthetic":true}\n', encoding="utf-8")
    (dataset_root / "train").mkdir()
    (dataset_root / "evaluation").mkdir()
    (dataset_root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (dataset_root / "training-config.yaml").write_text(
        "synthetic: true\n", encoding="utf-8"
    )
    manifest_checksum = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    output_root = external_credential_root / "output"
    configuration = LocalSingleUserActivationConfiguration(
        profile="local_single_user",
        provider="postgresql",
        host="127.0.0.1",
        database=f"dohalm_training_{suffix}",
        credential_directory_environment_variable="DOHALM_LOCAL_CREDENTIAL_DIRECTORY",
        run_package_environment_variable="DOHALM_LOCAL_RUN_PACKAGE",
        output_root_environment_variable="DOHALM_LOCAL_OUTPUT_ROOT",
        application_name="dohalm-local-integration",
        process_boundary_id=f"process:local-{suffix}",
        decision_authority_id=str(uuid.uuid4()),
        prerequisite_policy_reference="policy:local-prerequisite-v1",
        decision_policy_reference="policy:local-decision-v1",
        activation_authority_reference="activation:local-integration",
        activation_evidence_reference="evidence:local-integration",
        connect_timeout_seconds=5,
        statement_timeout_ms=15_000,
        transaction_timeout_ms=30_000,
        docker=LocalDockerConfiguration(
            container_name=f"dohalm-local-pg-{suffix}",
            network_name=f"dohalm-local-net-{suffix}",
            volume_name=f"dohalm-local-vol-{suffix}",
            correlation_id=correlation,
        ),
        dataset=LocalDatasetMappingConfiguration(
            root_environment_variable="DOHALM_LOCAL_DATASET_ROOT",
            manifest_relative_path="manifest.json",
            expected_manifest_sha256=manifest_checksum,
            train_split_relative_path="train",
            evaluation_split_relative_path="evaluation",
            tokenizer_reference_relative_path="tokenizer.json",
            training_config_reference_relative_path="training-config.yaml",
        ),
    )
    environment = {
        "DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(credential_directory),
        "DOHALM_LOCAL_DATASET_ROOT": str(dataset_root),
        "DOHALM_LOCAL_OUTPUT_ROOT": str(output_root),
    }
    credentials, directory = load_local_role_credentials(configuration, environment)
    bootstrapper = LocalDurablePostgresBootstrapper(
        configuration, credentials, directory
    )
    try:
        first = bootstrapper.bootstrap()
        second = bootstrapper.bootstrap()
        assert first.port == second.port
        assert first.migration_versions == (1, 2, 3)
        assert second.migration_versions == (1, 2, 3)
        assert first.binding_verified is True
        assert first.durable_volume_preserved is True

        inspect = json.loads(
            _docker("inspect", configuration.docker.container_name).stdout
        )[0]
        assert inspect["NetworkSettings"]["Ports"]["5432/tcp"] == [
            {"HostIp": "127.0.0.1", "HostPort": str(first.port)}
        ]
        assert inspect["Config"]["Labels"][LABEL] == configuration.docker.correlation_id

        import psycopg

        def counts() -> tuple[int, int]:
            with psycopg.connect(
                host="127.0.0.1",
                port=first.port,
                dbname=configuration.database,
                user="postgres",
                password=credentials.migration_owner,
                sslmode="disable",
            ) as owner:
                return owner.execute(
                    "SELECT "
                    "(SELECT count(*) FROM dohalm_training_v1.training_execution_journal), "
                    "(SELECT count(*) FROM dohalm_training_v1.training_execution_phase_event)"
                ).fetchone()

        before = counts()
        readiness = inspect_local_training_readiness(
            configuration,
            environment=environment,
            port_resolver=lambda _: first.port,
        )
        after = counts()
        assert readiness["status"] == "NOT_APPROVED"
        assert readiness["database"]["roles_reachable"] is True
        assert readiness["training_backend_invocation_count"] == 0
        assert readiness["journal_mutation_count"] == 0
        assert after == before

        with psycopg.connect(
            host="127.0.0.1",
            port=first.port,
            dbname=configuration.database,
            user="dohalm_training_resolver",
            password=credentials.resolver,
            sslmode="disable",
        ) as restricted:
            with pytest.raises(Exception) as denied:
                restricted.execute(
                    "SELECT count(*) FROM dohalm_training_v1.training_execution_journal"
                )
            assert denied.value.sqlstate == "42501"
            restricted.rollback()
    finally:
        bootstrapper.destroy(confirm_correlation_id=correlation)
        for arguments in (
            ("ps", "-aq"),
            ("volume", "ls", "-q"),
            ("network", "ls", "-q"),
        ):
            residue = _docker(*arguments, "--filter", f"label={LABEL}={correlation}")
            assert not residue.stdout.strip()
