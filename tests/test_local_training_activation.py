from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.training.errors import TrainingError
from src.training.local_activation import (
    POSTGRES_IMAGE,
    LocalDockerConfiguration,
    LocalRoleCredentials,
    LocalSingleUserActivationConfiguration,
    LocalDatasetMappingConfiguration,
    execute_local_training,
    inspect_local_training_readiness,
    load_local_activation_configuration,
    load_local_role_credentials,
)
from src.training.postgres_training_adapters import (
    _PostgresTrainingConnectionSettings,
)
from src.training.production_composition import (
    _PostgresTrainingCompositionConfiguration,
)


def _configuration(**changes: object) -> LocalSingleUserActivationConfiguration:
    values: dict[str, object] = {
        "profile": "local_single_user",
        "provider": "postgresql",
        "host": "127.0.0.1",
        "database": "dohalm_training_local",
        "credential_directory_environment_variable": "DOHALM_LOCAL_CREDENTIAL_DIRECTORY",
        "run_package_environment_variable": "DOHALM_LOCAL_RUN_PACKAGE",
        "output_root_environment_variable": "DOHALM_LOCAL_OUTPUT_ROOT",
        "application_name": "dohalm-local-activation",
        "process_boundary_id": "process:local-single-user",
        "decision_authority_id": "55555555-5555-4555-8555-555555555555",
        "prerequisite_policy_reference": "policy:local-prerequisite-v1",
        "decision_policy_reference": "policy:local-decision-v1",
        "activation_authority_reference": "activation:local-single-user-v1",
        "activation_evidence_reference": "evidence:local-single-user-v1",
        "connect_timeout_seconds": 5,
        "statement_timeout_ms": 15_000,
        "transaction_timeout_ms": 30_000,
        "docker": LocalDockerConfiguration(
            container_name="dohalm-local-postgres",
            network_name="dohalm-local-network",
            volume_name="dohalm-local-volume",
            correlation_id="local-single-user-v1",
        ),
        "dataset": LocalDatasetMappingConfiguration(
            root_environment_variable="DOHALM_LOCAL_DATASET_ROOT",
            manifest_relative_path="manifest.json",
            expected_manifest_sha256="sha256:" + "0" * 64,
            train_split_relative_path="train",
            evaluation_split_relative_path="evaluation",
            tokenizer_reference_relative_path="tokenizer.json",
            training_config_reference_relative_path="training-config.yaml",
        ),
    }
    values.update(changes)
    return LocalSingleUserActivationConfiguration(**values)


def _credential_directory(tmp_path: Path) -> tuple[Path, LocalRoleCredentials]:
    directory = tmp_path / "credentials"
    directory.mkdir()
    values = {
        "migration_owner": "migration-owner-synthetic-password",
        "producer": "producer-synthetic-password",
        "resolver": "resolver-synthetic-password",
        "journal": "journal-synthetic-password",
    }
    for role, value in values.items():
        (directory / f"{role}.password").write_text(value, encoding="utf-8")
    return directory, LocalRoleCredentials(**values)


@pytest.fixture
def external_credential_root() -> object:
    with tempfile.TemporaryDirectory(prefix="dohalm-local-credentials-") as root:
        yield Path(root)


def _dataset(
    tmp_path: Path, configuration: LocalSingleUserActivationConfiguration
) -> Path:
    root = tmp_path / "dataset"
    root.mkdir()
    manifest = root / "manifest.json"
    manifest.write_text('{"synthetic":true}\n', encoding="utf-8")
    (root / "train").mkdir()
    (root / "evaluation").mkdir()
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "training-config.yaml").write_text("synthetic: true\n", encoding="utf-8")
    checksum = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    object.__setattr__(configuration.dataset, "expected_manifest_sha256", checksum)
    return root


def test_default_provider_stays_disabled_and_local_profile_is_explicit() -> None:
    disabled = _PostgresTrainingCompositionConfiguration()
    assert disabled.provider == "disabled"
    with pytest.raises(TrainingError, match="LOCAL_TRAINING_CONFIGURATION_INVALID"):
        _configuration(profile="isolated_test")


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "localhost", "192.168.0.4", "db.example"]
)
def test_local_profile_accepts_ipv4_loopback_only(host: str) -> None:
    with pytest.raises(TrainingError, match="LOCAL_TRAINING_CONFIGURATION_INVALID"):
        _configuration(host=host)


def test_c2_and_c3_accept_local_loopback_without_weakening_production_tls(
    tmp_path: Path,
) -> None:
    settings = _PostgresTrainingConnectionSettings(
        environment="local_single_user",
        host="127.0.0.1",
        port=5432,
        database="dohalm_training_local",
        user="dohalm_training_resolver",
        password="synthetic-resolver",
        role="dohalm_training_resolver",
        application_name="dohalm-local-resolver",
        sslmode="disable",
    )
    assert "synthetic" not in repr(settings)
    ca = tmp_path / "root.crt"
    ca.write_text("synthetic", encoding="utf-8")
    production = _PostgresTrainingConnectionSettings(
        environment="production",
        host="db.internal.invalid",
        port=5432,
        database="dohalm_training",
        user="dohalm_training_resolver",
        password="synthetic-resolver",
        role="dohalm_training_resolver",
        application_name="dohalm-production-resolver",
        sslmode="verify-full",
        sslrootcert=ca.resolve(),
    )
    assert "db.internal.invalid" not in repr(production)
    with pytest.raises(TrainingError, match="TRAINING_DATABASE_CONFIGURATION_INVALID"):
        _PostgresTrainingConnectionSettings(
            environment="production",
            host="127.0.0.1",
            port=5432,
            database="dohalm_training",
            user="dohalm_training_resolver",
            password="synthetic-resolver",
            role="dohalm_training_resolver",
            application_name="dohalm-production-resolver",
            sslmode="disable",
        )


def test_json_configuration_rejects_duplicate_keys_and_redacts(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"profile":"local_single_user","profile":"disabled"}', encoding="utf-8"
    )
    with pytest.raises(TrainingError, match="LOCAL_TRAINING_CONFIGURATION_INVALID"):
        load_local_activation_configuration(duplicate)
    assert "127.0.0.1" not in repr(_configuration())


def test_credentials_are_role_separated_outside_repository(
    external_credential_root: Path,
) -> None:
    directory, credentials = _credential_directory(external_credential_root)
    loaded, source = load_local_role_credentials(
        _configuration(), {"DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(directory)}
    )
    assert loaded == credentials
    assert source == directory.resolve()
    assert "password" not in repr(loaded)


def test_missing_dataset_mapping_returns_not_configured_without_db_or_training(
    external_credential_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, _ = _credential_directory(external_credential_root)
    monkeypatch.setattr(
        "src.training.local_activation._compose_postgres_training_host",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("DB composition must not start")
        ),
    )
    result = inspect_local_training_readiness(
        _configuration(),
        environment={"DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(directory)},
        torch_module=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    assert result["status"] == "NOT_CONFIGURED"
    assert result["training_backend_invocation_count"] == 0
    assert result["journal_mutation_count"] == 0
    assert result["dataset_authority_available"] is False
    assert result["technical_readiness"] is False


def test_missing_run_package_returns_not_approved_and_always_shuts_down(
    tmp_path: Path,
    external_credential_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    directory, _ = _credential_directory(external_credential_root)
    dataset = _dataset(tmp_path, configuration)
    output = external_credential_root / "output"

    class Root:
        shutdown_count = 0

        def preflight(self) -> object:
            return SimpleNamespace(role_separation=True)

        def startup(self, _decision: object) -> object:
            return object()

        def shutdown(self) -> None:
            self.shutdown_count += 1

    root = Root()
    monkeypatch.setattr(
        "src.training.local_activation._compose_postgres_training_host", lambda *_: root
    )
    result = inspect_local_training_readiness(
        configuration,
        environment={
            "DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(directory),
            "DOHALM_LOCAL_DATASET_ROOT": str(dataset),
            "DOHALM_LOCAL_OUTPUT_ROOT": str(output),
        },
        port_resolver=lambda _: 55432,
        torch_module=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    assert result["status"] == "NOT_APPROVED"
    assert result["database"]["host"] == "127.0.0.1"
    assert result["training_backend_invocation_count"] == 0
    assert result["journal_mutation_count"] == 0
    assert result["decision_available"] is False
    assert root.shutdown_count == 1


def test_execute_without_exact_run_package_fails_before_db(
    external_credential_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, _ = _credential_directory(external_credential_root)
    monkeypatch.setattr(
        "src.training.local_activation._resolve_container_port",
        lambda *_: (_ for _ in ()).throw(AssertionError("DB must not be reached")),
    )
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_REQUIRED"):
        execute_local_training(
            _configuration(),
            environment={"DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(directory)},
        )


def test_gpu_probe_reports_metadata_without_loading_training_backend(
    external_credential_root: Path,
) -> None:
    directory, _ = _credential_directory(external_credential_root)
    fake_cuda = SimpleNamespace(
        is_available=lambda: True,
        get_device_properties=lambda _index: SimpleNamespace(
            name="NVIDIA GeForce RTX 3070", major=8
        ),
        mem_get_info=lambda _index: (4_000_000_000, 8_000_000_000),
    )
    result = inspect_local_training_readiness(
        _configuration(),
        environment={"DOHALM_LOCAL_CREDENTIAL_DIRECTORY": str(directory)},
        torch_module=SimpleNamespace(cuda=fake_cuda),
    )
    assert result["gpu"] == {
        "available": True,
        "name": "NVIDIA GeForce RTX 3070",
        "total_vram_bytes": 8_000_000_000,
        "free_vram_bytes": 4_000_000_000,
        "fp16_supported": True,
    }
    assert result["training_backend_invocation_count"] == 0


def test_exact_postgres_image_contract_is_reused() -> None:
    assert POSTGRES_IMAGE == (
        "postgres:16.15-alpine@"
        "sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571"
    )


def test_example_configuration_is_parseable() -> None:
    configuration = load_local_activation_configuration(
        Path("configs/local-training-activation.example.json")
    )
    assert configuration.profile == "local_single_user"
    assert configuration.host == "127.0.0.1"


def test_local_examples_contain_no_real_paths_or_credentials() -> None:
    values = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "configs/local-training-activation.example.json",
            "configs/local-training-run-package.example.json",
        )
    )
    assert "C:\\Users" not in values
    assert "POSTGRES_PASSWORD" not in values
    assert "replace-with-approved" in values
