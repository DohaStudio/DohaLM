from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.inference.adapter_manifest import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    AdapterManifestError,
    load_adapter_manifest,
)


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "adapter_manifest"
    / "synthetic-not-for-runtime"
    / "adapter-manifest.json"
)


def fixture_value() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write_manifest(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "adapter-manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def assert_error(path: Path, code: str) -> AdapterManifestError:
    with pytest.raises(AdapterManifestError) as captured:
        load_adapter_manifest(path)
    assert captured.value.code == code
    assert str(captured.value) == code
    assert str(path.resolve()) not in captured.value.safe_message
    return captured.value


def test_loads_minimum_valid_synthetic_manifest() -> None:
    manifest = load_adapter_manifest(FIXTURE)

    assert manifest.schema_version == ADAPTER_MANIFEST_SCHEMA_VERSION
    assert manifest.adapter_name == "synthetic-not-for-runtime"
    assert manifest.adapter_config.path == "artifacts/adapter_config.json"
    assert manifest.generation_config.request_override_policy == "api_bounds_only"
    assert manifest.training_run.id == "SYNTHETIC-NOT-FOR-RUNTIME"


def test_loads_all_fields_and_resolves_relative_artifact_paths() -> None:
    manifest = load_adapter_manifest(FIXTURE)

    expected = (FIXTURE.parent / "artifacts/adapter_model.safetensors").resolve()
    assert manifest.resolve_artifact(manifest.adapter_weights) == expected
    assert manifest.generation_config_path == (
        FIXTURE.parent / "artifacts/generation-config.json"
    ).resolve()
    assert manifest.training_result_path == (
        FIXTURE.parent / "artifacts/training-result.yaml"
    ).resolve()
    assert manifest.manifest_path == FIXTURE.resolve()


def test_manifest_and_nested_models_are_immutable() -> None:
    manifest = load_adapter_manifest(FIXTURE)

    with pytest.raises(FrozenInstanceError):
        manifest.adapter_name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        manifest.adapter_config.path = "changed"  # type: ignore[misc]


def test_repr_does_not_expose_manifest_absolute_path() -> None:
    manifest = load_adapter_manifest(FIXTURE)

    assert str(FIXTURE.resolve()) not in repr(manifest)


def test_missing_file_and_directory_are_distinct_path_failures(tmp_path: Path) -> None:
    assert_error(tmp_path / "missing.json", "ADAPTER_MANIFEST_NOT_FOUND")
    assert_error(tmp_path, "ADAPTER_MANIFEST_PATH_INVALID")


def test_rejects_non_path_input() -> None:
    with pytest.raises(AdapterManifestError) as captured:
        load_adapter_manifest("adapter-manifest.json")  # type: ignore[arg-type]
    assert captured.value.code == "ADAPTER_MANIFEST_PATH_INVALID"


def test_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "adapter-manifest.json"
    path.write_bytes(b"\xff\xfe")
    assert_error(path, "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize("payload", ["{", "[]", '{"value": NaN}'])
def test_rejects_malformed_or_non_object_json(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "adapter-manifest.json"
    path.write_text(payload, encoding="utf-8")
    assert_error(path, "ADAPTER_MANIFEST_INVALID")


def test_rejects_duplicate_keys_at_any_depth(tmp_path: Path) -> None:
    payload = FIXTURE.read_text(encoding="utf-8").replace(
        '"path": "artifacts/adapter_config.json",',
        '"path": "first.json", "path": "second.json",',
    )
    path = tmp_path / "adapter-manifest.json"
    path.write_text(payload, encoding="utf-8")
    assert_error(path, "ADAPTER_MANIFEST_INVALID")


def test_rejects_missing_and_unknown_top_level_fields(tmp_path: Path) -> None:
    missing = fixture_value()
    del missing["metadata"]
    assert_error(write_manifest(tmp_path, missing), "ADAPTER_MANIFEST_INVALID")

    unknown = fixture_value()
    unknown["unexpected"] = True
    assert_error(write_manifest(tmp_path, unknown), "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize("version", [0, 2, -1])
def test_rejects_unsupported_schema_version(tmp_path: Path, version: int) -> None:
    value = fixture_value()
    value["schema_version"] = version
    assert_error(
        write_manifest(tmp_path, value),
        "ADAPTER_MANIFEST_UNSUPPORTED_VERSION",
    )


@pytest.mark.parametrize("version", [True, "1", 1.0])
def test_rejects_non_integer_schema_version(tmp_path: Path, version: object) -> None:
    value = fixture_value()
    value["schema_version"] = version
    assert_error(write_manifest(tmp_path, value), "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_name", ""),
        ("adapter_version", "   "),
        ("base_model", None),
        ("evaluation_fingerprint", ""),
    ],
)
def test_rejects_empty_or_wrong_scalar_values(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest = fixture_value()
    manifest[field] = value
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize(
    "value",
    [
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "sha256:" + "a" * 64,
        "g" * 64,
    ],
)
def test_rejects_noncanonical_sha256(tmp_path: Path, value: str) -> None:
    manifest = fixture_value()
    manifest["tokenizer_hash"] = value
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


def test_rejects_invalid_artifact_checksum(tmp_path: Path) -> None:
    manifest = fixture_value()
    adapter_config = manifest["adapter_config"]
    assert isinstance(adapter_config, dict)
    adapter_config["sha256"] = "not-a-hash"
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize(
    "artifact_path",
    [
        "C:/private/adapter.json",
        "C:\\private\\adapter.json",
        "/private/adapter.json",
        "../adapter.json",
        "..\\adapter.json",
        "artifacts/../../adapter.json",
    ],
)
def test_rejects_absolute_and_traversing_artifact_paths(
    tmp_path: Path, artifact_path: str
) -> None:
    manifest = fixture_value()
    adapter_config = manifest["adapter_config"]
    assert isinstance(adapter_config, dict)
    adapter_config["path"] = artifact_path
    assert_error(
        write_manifest(tmp_path, manifest),
        "ADAPTER_MANIFEST_PATH_INVALID",
    )


def test_rejects_non_object_generation_config(tmp_path: Path) -> None:
    manifest = fixture_value()
    manifest["generation_config"] = "generation-config.json"
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


def test_rejects_empty_chat_template_and_training_run(tmp_path: Path) -> None:
    manifest = fixture_value()
    chat_template = manifest["chat_template"]
    assert isinstance(chat_template, dict)
    chat_template["source"] = ""
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")

    manifest = fixture_value()
    training_run = manifest["training_run"]
    assert isinstance(training_run, dict)
    training_run["id"] = ""
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


@pytest.mark.parametrize(
    "created_at",
    [
        "",
        "2026-08-05",
        "2026-08-05T00:00:00",
        "2026-08-05T00:00:00+09:00",
        "2026-02-30T00:00:00Z",
    ],
)
def test_rejects_invalid_created_at(tmp_path: Path, created_at: str) -> None:
    manifest = fixture_value()
    manifest["created_at"] = created_at
    assert_error(write_manifest(tmp_path, manifest), "ADAPTER_MANIFEST_INVALID")


def test_does_not_require_artifact_files_during_static_load() -> None:
    manifest = load_adapter_manifest(FIXTURE)

    assert not manifest.resolve_artifact(manifest.adapter_weights).exists()
