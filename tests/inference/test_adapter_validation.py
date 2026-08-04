from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Callable

import pytest

import src.inference.adapter_validation as validation
from src.inference.adapter_manifest import AdapterManifest, load_adapter_manifest
from src.inference.adapter_validation import (
    AdapterValidationError,
    validate_adapter_artifacts,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
BASE_MODEL = "synthetic/not-for-runtime-base"
BASE_REVISION = "1" * 40


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def safetensors_bytes(header: object | None = None, data: bytes = b"abcdefgh") -> bytes:
    if header is None:
        header = {
            "base_model.layers.0.q_proj.lora_A.weight": {
                "dtype": "F32",
                "shape": [1],
                "data_offsets": [0, 4],
            },
            "base_model.layers.0.q_proj.lora_B.weight": {
                "dtype": "F32",
                "shape": [1],
                "data_offsets": [4, 8],
            },
        }
    encoded = json_bytes(header)
    encoded += b" " * (-len(encoded) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + data


Mutator = Callable[[dict[str, Any]], None]


def synthetic_manifest(
    root: Path,
    *,
    config_mutator: Mutator | None = None,
    metadata_mutator: Mutator | None = None,
    generation_mutator: Mutator | None = None,
    weights: bytes | None = None,
) -> AdapterManifest:
    """Create fake static artifacts that must never be used by a runtime."""
    artifacts = root / "synthetic-not-for-runtime"
    artifacts.mkdir(parents=True)
    config: dict[str, Any] = {
        "base_model_name_or_path": BASE_MODEL,
        "revision": BASE_REVISION,
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "target_modules": ["q_proj", "v_proj"],
        "bias": "none",
        "inference_mode": True,
    }
    if config_mutator:
        config_mutator(config)
    generation: dict[str, Any] = {
        "max_new_tokens": 256,
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 50,
        "repetition_penalty": 1.05,
        "do_sample": True,
        "eos_token_id": [151643, 151645],
        "pad_token_id": 151643,
    }
    if generation_mutator:
        generation_mutator(generation)
    config_payload = json_bytes(config)
    weights_payload = weights if weights is not None else safetensors_bytes()
    generation_payload = json_bytes(generation)
    training_payload = b"status: synthetic-not-for-runtime\n"
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "adapter_name": "synthetic-not-for-runtime",
        "adapter_version": "0.0.0-synthetic",
        "base_model": BASE_MODEL,
        "base_revision": BASE_REVISION,
        "tokenizer": {"name": BASE_MODEL, "sha256": HASH_A},
        "chat_template": {
            "source": "tokenizer_config.json#chat_template",
            "sha256": HASH_B,
        },
        "training_run": {"id": "SYNTHETIC-NOT-FOR-RUNTIME"},
        "evaluation_fingerprint": "c" * 64,
        "created_at": "2026-08-05T00:00:00Z",
        "training_method": "qlora",
        "dataset_fingerprint": "d" * 64,
        "source_commit": "e" * 40,
        "artifact_checksums": {
            "adapter_config": sha256(config_payload),
            "adapter_weights": sha256(weights_payload),
            "generation_config": sha256(generation_payload),
            "training_result": sha256(training_payload),
        },
        "synthetic_notice": "fake-not-for-runtime",
    }
    if metadata_mutator:
        metadata_mutator(metadata)
    metadata_payload = json_bytes(metadata)
    files = {
        "adapter_config.json": config_payload,
        "adapter_model.safetensors": weights_payload,
        "adapter-metadata.json": metadata_payload,
        "generation-config.json": generation_payload,
        "training-result.yaml": training_payload,
    }
    for name, payload in files.items():
        (artifacts / name).write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "adapter_name": "synthetic-not-for-runtime",
        "adapter_version": "0.0.0-synthetic",
        "base_model": BASE_MODEL,
        "base_revision": BASE_REVISION,
        "tokenizer": BASE_MODEL,
        "tokenizer_hash": HASH_A,
        "chat_template": {
            "source": "tokenizer_config.json#chat_template",
            "sha256": HASH_B,
        },
        "peft_version": "0.17.0.synthetic",
        "transformers_version": "4.57.6.synthetic",
        "torch_version": "2.7.1.synthetic",
        "generation_config": {
            "path": "generation-config.json",
            "sha256": sha256(generation_payload),
            "request_override_policy": "api_bounds_only",
        },
        "evaluation_fingerprint": "c" * 64,
        "training_run": {
            "id": "SYNTHETIC-NOT-FOR-RUNTIME",
            "result_path": "training-result.yaml",
            "result_sha256": sha256(training_payload),
        },
        "created_at": "2026-08-05T00:00:00Z",
        "adapter_config": {
            "path": "adapter_config.json",
            "sha256": sha256(config_payload),
        },
        "adapter_weights": {
            "path": "adapter_model.safetensors",
            "sha256": sha256(weights_payload),
        },
        "metadata": {
            "path": "adapter-metadata.json",
            "sha256": sha256(metadata_payload),
        },
    }
    path = artifacts / "adapter-manifest.json"
    path.write_bytes(json_bytes(manifest))
    return load_adapter_manifest(path)


def assert_error(manifest: AdapterManifest, code: str) -> AdapterValidationError:
    with pytest.raises(AdapterValidationError) as captured:
        validate_adapter_artifacts(manifest)
    assert captured.value.code == code
    assert str(captured.value) == code
    assert str(manifest.manifest_root) not in captured.value.safe_message
    return captured.value


def test_validates_synthetic_artifacts_without_loading_tensors(tmp_path: Path) -> None:
    result = validate_adapter_artifacts(synthetic_manifest(tmp_path))

    assert result.manifest.adapter_name == "synthetic-not-for-runtime"
    assert result.adapter_config.peft_type == "LORA"
    assert result.weights.tensor_count == 2
    assert result.metadata.training_method == "qlora"
    assert result.generation_config.max_new_tokens == 256
    assert all(not Path(item.relative_path).is_absolute() for item in result.artifacts)
    assert str(tmp_path.resolve()) not in repr(result)


def test_fingerprint_is_deterministic_and_excludes_time(tmp_path: Path) -> None:
    manifest = synthetic_manifest(tmp_path)
    first = validate_adapter_artifacts(manifest)
    second = validate_adapter_artifacts(manifest)

    assert first.validation_fingerprint == second.validation_fingerprint
    assert first.validation_fingerprint.startswith("sha256:")
    assert len(first.validation_fingerprint) == 71


def test_result_and_nested_summaries_are_immutable(tmp_path: Path) -> None:
    result = validate_adapter_artifacts(synthetic_manifest(tmp_path))
    with pytest.raises(FrozenInstanceError):
        result.validation_fingerprint = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.adapter_config.rank = 1  # type: ignore[misc]


def test_allows_additional_peft_and_metadata_fields(tmp_path: Path) -> None:
    manifest = synthetic_manifest(
        tmp_path,
        config_mutator=lambda value: value.update({"use_dora": False}),
        metadata_mutator=lambda value: value.update({"future_extension": {"v": 1}}),
    )
    assert validate_adapter_artifacts(manifest).adapter_config.rank == 16


@pytest.mark.parametrize("condition", ["missing", "directory"])
def test_rejects_missing_file_and_directory(tmp_path: Path, condition: str) -> None:
    manifest = synthetic_manifest(tmp_path)
    path = manifest.manifest_root / manifest.adapter_config.path
    path.unlink()
    if condition == "directory":
        path.mkdir()
    assert_error(
        manifest,
        "ADAPTER_ARTIFACT_NOT_FOUND"
        if condition == "missing"
        else "ADAPTER_ARTIFACT_INVALID",
    )


def test_rejects_symlink_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = synthetic_manifest(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path.name == "adapter_config.json" or original(path),
    )
    assert_error(manifest, "ADAPTER_ARTIFACT_INVALID")


def test_rejects_checksum_mismatch(tmp_path: Path) -> None:
    manifest = synthetic_manifest(tmp_path)
    (manifest.manifest_root / manifest.adapter_config.path).write_bytes(b"changed")
    assert_error(manifest, "ADAPTER_ARTIFACT_CHECKSUM_MISMATCH")


def test_rejects_oversized_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = synthetic_manifest(tmp_path)
    monkeypatch.setattr(validation, "MAX_ADAPTER_CONFIG_BYTES", 1)
    assert_error(manifest, "ADAPTER_ARTIFACT_INVALID")


def test_detects_file_mutation_during_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = synthetic_manifest(tmp_path)
    path = manifest.manifest_root / manifest.adapter_config.path
    original = validation._path_identity
    calls = 0

    def mutate_after_first_identity(candidate: Path) -> object:
        nonlocal calls
        identity = original(candidate)
        calls += 1
        if calls == 1:
            path.write_bytes(path.read_bytes() + b" ")
        return identity

    monkeypatch.setattr(validation, "_path_identity", mutate_after_first_identity)
    assert_error(manifest, "ADAPTER_ARTIFACT_INVALID")


def test_rejects_malformed_config_json(tmp_path: Path) -> None:
    manifest = synthetic_manifest(tmp_path)
    path = manifest.manifest_root / manifest.adapter_config.path
    path.write_bytes(b"{")
    manifest = replace(
        manifest, adapter_config=replace(manifest.adapter_config, sha256=sha256(b"{"))
    )
    assert_error(manifest, "ADAPTER_CONFIG_INCOMPATIBLE")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(base_model_name_or_path="different/base"),
        lambda value: value.update(revision="2" * 40),
        lambda value: value.update(peft_type="PREFIX_TUNING"),
        lambda value: value.update(r=0),
        lambda value: value.update(lora_alpha=float("inf")),
        lambda value: value.update(lora_dropout=2),
        lambda value: value.update(target_modules=[]),
        lambda value: value.update(inference_mode=False),
    ],
)
def test_rejects_incompatible_adapter_config(tmp_path: Path, mutator: Mutator) -> None:
    assert_error(
        synthetic_manifest(tmp_path, config_mutator=mutator),
        "ADAPTER_CONFIG_INCOMPATIBLE",
    )


@pytest.mark.parametrize(
    "weights",
    [
        b"not-safetensors",
        struct.pack("<Q", validation.MAX_SAFETENSORS_HEADER_BYTES + 1) + b"{}",
        safetensors_bytes(
            {"tensor": {"dtype": "F32", "shape": [1], "data_offsets": [0, 99]}}
        ),
        safetensors_bytes(
            {
                "a": {"dtype": "F32", "shape": [1], "data_offsets": [0, 6]},
                "b": {"dtype": "F32", "shape": [1], "data_offsets": [4, 8]},
            }
        ),
    ],
)
def test_rejects_invalid_safetensors(tmp_path: Path, weights: bytes) -> None:
    assert_error(
        synthetic_manifest(tmp_path, weights=weights), "ADAPTER_WEIGHTS_INVALID"
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(base_model="different/base"),
        lambda value: value.update(base_revision="2" * 40),
        lambda value: value["training_run"].update(id="different-run"),
        lambda value: value.update(evaluation_fingerprint="f" * 64),
        lambda value: value["tokenizer"].update(sha256="f" * 64),
        lambda value: value["chat_template"].update(sha256="f" * 64),
        lambda value: value["artifact_checksums"].update(adapter_weights="f" * 64),
    ],
)
def test_rejects_incompatible_metadata(tmp_path: Path, mutator: Mutator) -> None:
    assert_error(
        synthetic_manifest(tmp_path, metadata_mutator=mutator),
        "ADAPTER_METADATA_INCOMPATIBLE",
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(max_new_tokens=0),
        lambda value: value.update(max_new_tokens=1025),
        lambda value: value.update(temperature=float("nan")),
        lambda value: value.update(temperature=float("inf")),
        lambda value: value.update(top_p=0),
        lambda value: value.update(top_k=-1),
        lambda value: value.update(repetition_penalty=0.1),
        lambda value: value.update(do_sample="true"),
        lambda value: value.update(eos_token_id=[]),
        lambda value: value.update(pad_token_id=-1),
    ],
)
def test_rejects_invalid_generation_config(tmp_path: Path, mutator: Mutator) -> None:
    assert_error(
        synthetic_manifest(tmp_path, generation_mutator=mutator),
        "ADAPTER_GENERATION_CONFIG_INVALID",
    )
