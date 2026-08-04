"""Fail-closed, local-only loader for one validated PEFT adapter runtime."""

from __future__ import annotations

import gc
import hashlib
import importlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from src.inference.adapter_manifest import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    AdapterManifest,
)
from src.inference.adapter_validation import (
    AdapterValidationResult,
    GenerationConfigSummary,
    ManifestIdentity,
    ValidatedArtifactIdentity,
    validate_adapter_artifacts,
)
from src.inference.model_loader import (
    BASE_QWEN_EOS_TOKEN_ID,
    BASE_QWEN_MODEL_ID,
    BASE_QWEN_PAD_TOKEN_ID,
    BASE_QWEN_REVISION,
)


_MAX_BASE_CONFIG_BYTES = 1024 * 1024
_MINIMUM_FREE_VRAM_MIB = 5500
_APPROVED_GPU = "NVIDIA GeForce RTX 3060 Ti"
_TOKENIZER_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
_BASE_REQUIRED_FILES = (*_TOKENIZER_FILES, "model.safetensors")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}(?:[A-Za-z0-9.+_-]*)\Z")
_CHAT_TEMPLATE_SOURCE = "tokenizer_config.json#chat_template"

_ERROR_MESSAGES = {
    "ADAPTER_VALIDATION_RESULT_INCOMPATIBLE": (
        "The adapter validation result is incompatible."
    ),
    "ADAPTER_RUNTIME_DEPENDENCY_MISSING": (
        "A required adapter runtime dependency is not available."
    ),
    "ADAPTER_RUNTIME_VERSION_INCOMPATIBLE": (
        "The adapter runtime dependency versions are incompatible."
    ),
    "ADAPTER_BASE_SNAPSHOT_NOT_FOUND": "The local Base snapshot is not available.",
    "ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE": ("The local Base snapshot is incompatible."),
    "ADAPTER_TOKENIZER_INCOMPATIBLE": "The local tokenizer is incompatible.",
    "ADAPTER_CHAT_TEMPLATE_INCOMPATIBLE": (
        "The tokenizer chat template is incompatible."
    ),
    "ADAPTER_LOAD_FAILED": "The adapter runtime could not be loaded.",
    "ADAPTER_POST_LOAD_VALIDATION_FAILED": (
        "The loaded adapter runtime failed validation."
    ),
    "ADAPTER_UNLOAD_FAILED": "The adapter runtime could not be unloaded cleanly.",
}


class AdapterLoaderError(RuntimeError):
    """Sanitized loader failure suitable for later Provider mapping."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = _ERROR_MESSAGES[code]


@dataclass(frozen=True)
class RuntimeDependencyVersions:
    peft: str
    transformers: str
    torch: str


@dataclass(frozen=True)
class AdapterRuntimeIdentity:
    adapter_name: str
    adapter_version: str
    base_model: str
    base_revision: str
    validation_fingerprint: str
    generation_config: GenerationConfigSummary
    device: str
    dtype: str
    dependencies: RuntimeDependencyVersions


@dataclass
class AdapterRuntimeHandle:
    """Internal mutable resource owner with immutable, safe identity metadata."""

    identity: AdapterRuntimeIdentity
    loaded_at: str
    model: Any = field(repr=False)
    tokenizer: Any = field(repr=False)
    torch: Any = field(repr=False)
    _unloaded: bool = field(default=False, init=False, repr=False)

    @property
    def unloaded(self) -> bool:
        return self._unloaded


@dataclass(frozen=True)
class RuntimeDependencies:
    torch: ModuleType | Any
    transformers: ModuleType | Any
    peft: ModuleType | Any
    auto_tokenizer: Any
    auto_model: Any
    peft_model: Any


ArtifactValidator = Callable[[AdapterManifest], AdapterValidationResult]


def _error(code: str) -> AdapterLoaderError:
    return AdapterLoaderError(code)


def _manifest_identity(manifest: AdapterManifest) -> ManifestIdentity:
    return ManifestIdentity(
        manifest.schema_version,
        manifest.adapter_name,
        manifest.adapter_version,
        manifest.base_model,
        manifest.base_revision,
        manifest.tokenizer,
        manifest.tokenizer_hash,
        manifest.chat_template.source,
        manifest.chat_template.sha256,
        manifest.peft_version,
        manifest.transformers_version,
        manifest.torch_version,
        manifest.evaluation_fingerprint,
        manifest.training_run.id,
        manifest.created_at,
    )


def _expected_artifacts(manifest: AdapterManifest) -> dict[str, tuple[str, str]]:
    return {
        "adapter_config": (
            manifest.adapter_config.path,
            manifest.adapter_config.sha256,
        ),
        "adapter_weights": (
            manifest.adapter_weights.path,
            manifest.adapter_weights.sha256,
        ),
        "metadata": (manifest.metadata.path, manifest.metadata.sha256),
        "generation_config": (
            manifest.generation_config.path,
            manifest.generation_config.sha256,
        ),
        "training_result": (
            manifest.training_run.result_path,
            manifest.training_run.result_sha256,
        ),
    }


def _artifact_map(
    artifacts: tuple[ValidatedArtifactIdentity, ...],
) -> dict[str, ValidatedArtifactIdentity]:
    result = {artifact.name: artifact for artifact in artifacts}
    if len(result) != len(artifacts):
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")
    return result


def _validate_preflight_inputs(
    manifest: AdapterManifest,
    supplied: AdapterValidationResult,
    *,
    adapter_root: Path,
    validator: ArtifactValidator,
) -> AdapterValidationResult:
    if (
        not isinstance(manifest, AdapterManifest)
        or not isinstance(supplied, AdapterValidationResult)
        or manifest.schema_version != ADAPTER_MANIFEST_SCHEMA_VERSION
        or supplied.manifest != _manifest_identity(manifest)
        or supplied.warnings
    ):
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")
    try:
        if (
            not isinstance(adapter_root, Path)
            or adapter_root.is_symlink()
            or adapter_root.resolve(strict=True)
            != manifest.manifest_root.resolve(strict=True)
        ):
            raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")
    except AdapterLoaderError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE") from None

    expected = _expected_artifacts(manifest)
    supplied_artifacts = _artifact_map(supplied.artifacts)
    if set(supplied_artifacts) != set(expected):
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")
    for name, (relative_path, checksum) in expected.items():
        artifact = supplied_artifacts[name]
        if artifact.relative_path != relative_path or artifact.sha256 != checksum:
            raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")

    try:
        current = validator(manifest)
    except Exception:
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE") from None
    if (
        current.manifest != supplied.manifest
        or current.artifacts != supplied.artifacts
        or current.adapter_config != supplied.adapter_config
        or current.weights != supplied.weights
        or current.metadata != supplied.metadata
        or current.generation_config != supplied.generation_config
        or current.warnings != supplied.warnings
        or current.validation_fingerprint != supplied.validation_fingerprint
    ):
        raise _error("ADAPTER_VALIDATION_RESULT_INCOMPATIBLE")
    return current


def _load_dependencies() -> RuntimeDependencies:
    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        peft = importlib.import_module("peft")
        auto_tokenizer = getattr(transformers, "AutoTokenizer")
        auto_model = getattr(transformers, "AutoModelForCausalLM")
        peft_model = getattr(peft, "PeftModel")
    except Exception:
        raise _error("ADAPTER_RUNTIME_DEPENDENCY_MISSING") from None
    return RuntimeDependencies(
        torch, transformers, peft, auto_tokenizer, auto_model, peft_model
    )


def _dependency_version(module: Any) -> str:
    value = getattr(module, "__version__", None)
    if type(value) is not str or _VERSION.fullmatch(value) is None:
        raise _error("ADAPTER_RUNTIME_VERSION_INCOMPATIBLE")
    return value


def _validate_dependency_versions(
    manifest: AdapterManifest, dependencies: RuntimeDependencies
) -> RuntimeDependencyVersions:
    versions = RuntimeDependencyVersions(
        peft=_dependency_version(dependencies.peft),
        transformers=_dependency_version(dependencies.transformers),
        torch=_dependency_version(dependencies.torch),
    )
    if (
        versions.peft != manifest.peft_version
        or versions.transformers != manifest.transformers_version
        or versions.torch != manifest.torch_version
    ):
        raise _error("ADAPTER_RUNTIME_VERSION_INCOMPATIBLE")
    return versions


def _validate_cuda_runtime(torch_module: Any) -> None:
    try:
        cuda = torch_module.cuda
        if not cuda.is_available():
            raise _error("ADAPTER_LOAD_FAILED")
        free_bytes, _total_bytes = cuda.mem_get_info(0)
        if (
            cuda.get_device_name(0) != _APPROVED_GPU
            or free_bytes < _MINIMUM_FREE_VRAM_MIB * 1024 * 1024
        ):
            raise _error("ADAPTER_LOAD_FAILED")
    except AdapterLoaderError:
        raise
    except Exception:
        raise _error("ADAPTER_LOAD_FAILED") from None


def _strict_json(path: Path, code: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("non-finite number")

    try:
        if path.stat().st_size > _MAX_BASE_CONFIG_BYTES:
            raise _error(code)
        value = json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except AdapterLoaderError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise _error(code) from None
    if type(value) is not dict:
        raise _error(code)
    return value


def _validate_base_snapshot(manifest: AdapterManifest, path: Path) -> Path:
    if not isinstance(path, Path):
        raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE")
    try:
        if not path.exists():
            raise _error("ADAPTER_BASE_SNAPSHOT_NOT_FOUND")
        if path.is_symlink() or not path.is_dir():
            raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE")
        snapshot = path.resolve(strict=True)
        if snapshot.name != manifest.base_revision:
            raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE")
        for name in _BASE_REQUIRED_FILES:
            candidate = snapshot / name
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or not stat.S_ISREG(candidate.stat(follow_symlinks=False).st_mode)
            ):
                raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE")
    except AdapterLoaderError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE") from None
    config = _strict_json(
        snapshot / "config.json", "ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE"
    )
    if (
        manifest.base_model != BASE_QWEN_MODEL_ID
        or manifest.base_revision != BASE_QWEN_REVISION
        or manifest.tokenizer != BASE_QWEN_MODEL_ID
        or config.get("_name_or_path") != manifest.base_model
        or config.get("model_type") != "qwen2"
    ):
        raise _error("ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE")
    return snapshot


def tokenizer_fingerprint(snapshot: Path) -> str:
    """Return the established Qwen tokenizer inventory fingerprint."""
    digest = hashlib.sha256()
    try:
        for name in _TOKENIZER_FILES:
            path = snapshot / name
            before = path.stat(follow_symlinks=False)
            checksum_digest = hashlib.sha256()
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                while chunk := stream.read(1024 * 1024):
                    checksum_digest.update(chunk)
            after = path.stat(follow_symlinks=False)
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            opened_identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if before_identity != opened_identity or opened_identity != after_identity:
                raise _error("ADAPTER_TOKENIZER_INCOMPATIBLE")
            checksum = checksum_digest.hexdigest()
            digest.update(f"{name}\0{checksum}\n".encode("ascii"))
    except OSError:
        raise _error("ADAPTER_TOKENIZER_INCOMPATIBLE") from None
    return digest.hexdigest()


def _validate_tokenizer(
    tokenizer: Any,
    manifest: AdapterManifest,
    validation: AdapterValidationResult,
    snapshot: Path,
) -> None:
    if tokenizer_fingerprint(snapshot) != manifest.tokenizer_hash:
        raise _error("ADAPTER_TOKENIZER_INCOMPATIBLE")
    if (
        getattr(tokenizer, "eos_token_id", None) != BASE_QWEN_EOS_TOKEN_ID
        or getattr(tokenizer, "pad_token_id", None) != BASE_QWEN_PAD_TOKEN_ID
        or BASE_QWEN_EOS_TOKEN_ID not in validation.generation_config.eos_token_ids
        or validation.generation_config.pad_token_id != BASE_QWEN_PAD_TOKEN_ID
    ):
        raise _error("ADAPTER_TOKENIZER_INCOMPATIBLE")
    template = getattr(tokenizer, "chat_template", None)
    if (
        manifest.chat_template.source != _CHAT_TEMPLATE_SOURCE
        or type(template) is not str
        or not template
        or hashlib.sha256(template.encode("utf-8")).hexdigest()
        != manifest.chat_template.sha256
    ):
        raise _error("ADAPTER_CHAT_TEMPLATE_INCOMPATIBLE")


def _active_adapters(model: Any) -> tuple[str, ...]:
    value = getattr(model, "active_adapters", None)
    if callable(value):
        value = value()
    if value is None:
        value = getattr(model, "active_adapter", None)
        if callable(value):
            value = value()
    if type(value) is str:
        return (value,)
    if isinstance(value, (list, tuple)) and all(type(item) is str for item in value):
        return tuple(value)
    return ()


def _post_load_validate(
    model: Any,
    tokenizer: Any,
    manifest: AdapterManifest,
    validation: AdapterValidationResult,
    *,
    snapshot: Path,
    device: str,
    dtype_name: str,
) -> None:
    if model is None or tokenizer is None or bool(getattr(model, "training", True)):
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")
    peft_config = getattr(model, "peft_config", None)
    if not isinstance(peft_config, Mapping) or set(peft_config) != {
        manifest.adapter_name
    }:
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")
    config = peft_config[manifest.adapter_name]
    config_revision = getattr(config, "revision", None)
    if (
        getattr(config, "base_model_name_or_path", None) != manifest.base_model
        or (config_revision is not None and config_revision != manifest.base_revision)
        or _active_adapters(model) != (manifest.adapter_name,)
    ):
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")

    named_parameters = list(model.named_parameters())
    adapter_parameters = [
        parameter for name, parameter in named_parameters if "lora_" in name.lower()
    ]
    if not adapter_parameters or any(
        bool(getattr(parameter, "requires_grad", True))
        for _, parameter in named_parameters
    ):
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")
    expected_device = device.split(":", maxsplit=1)[0]
    device_types = {
        str(getattr(getattr(parameter, "device", None), "type", ""))
        for _, parameter in named_parameters
    }
    dtype_values = {
        str(getattr(parameter, "dtype", "")) for _, parameter in named_parameters
    }
    if device_types != {expected_device} or not any(
        dtype_name in value for value in dtype_values
    ):
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")
    device_map = {str(value) for value in getattr(model, "hf_device_map", {}).values()}
    if any(value in {"cpu", "disk", "meta"} for value in device_map):
        raise _error("ADAPTER_POST_LOAD_VALIDATION_FAILED")
    _validate_tokenizer(tokenizer, manifest, validation, snapshot)


def _release_cuda(torch_module: Any) -> None:
    cuda = getattr(torch_module, "cuda", None)
    if cuda is None or not cuda.is_available():
        return
    synchronize = getattr(cuda, "synchronize", None)
    if synchronize is not None:
        synchronize(0)
    cuda.empty_cache()
    ipc_collect = getattr(cuda, "ipc_collect", None)
    if ipc_collect is not None:
        ipc_collect()


def _safe_partial_cleanup(model: Any, tokenizer: Any, torch_module: Any) -> None:
    del model, tokenizer
    try:
        gc.collect()
        if torch_module is not None:
            _release_cuda(torch_module)
    except Exception:
        return


def load_peft_adapter_runtime(
    *,
    manifest: AdapterManifest,
    validation: AdapterValidationResult,
    base_model_path: Path,
    adapter_root: Path,
    device: str = "cuda:0",
    dtype: str = "bfloat16",
    dependencies: RuntimeDependencies | None = None,
    artifact_validator: ArtifactValidator = validate_adapter_artifacts,
) -> AdapterRuntimeHandle:
    """Load one explicit Base snapshot and one validated PEFT adapter."""
    model = None
    tokenizer = None
    torch_module = None
    try:
        current = _validate_preflight_inputs(
            manifest,
            validation,
            adapter_root=adapter_root,
            validator=artifact_validator,
        )
        snapshot = _validate_base_snapshot(manifest, base_model_path)
        resolved_dependencies = dependencies or _load_dependencies()
        torch_module = resolved_dependencies.torch
        versions = _validate_dependency_versions(manifest, resolved_dependencies)
        if device != "cuda:0" or dtype != "bfloat16":
            raise _error("ADAPTER_LOAD_FAILED")
        _validate_cuda_runtime(torch_module)
        torch_dtype = getattr(torch_module, dtype, None)
        if torch_dtype is None:
            raise _error("ADAPTER_RUNTIME_DEPENDENCY_MISSING")

        common = {
            "local_files_only": True,
            "trust_remote_code": False,
            "revision": manifest.base_revision,
        }
        try:
            tokenizer = resolved_dependencies.auto_tokenizer.from_pretrained(
                snapshot, use_fast=True, **common
            )
        except Exception:
            raise _error("ADAPTER_TOKENIZER_INCOMPATIBLE") from None
        _validate_tokenizer(tokenizer, manifest, current, snapshot)

        try:
            model = resolved_dependencies.auto_model.from_pretrained(
                snapshot,
                **common,
                device_map={"": 0},
                dtype=torch_dtype,
                low_cpu_mem_usage=True,
                use_safetensors=True,
            )
            model.eval()
            model.config.use_cache = True
        except Exception:
            raise _error("ADAPTER_LOAD_FAILED") from None
        try:
            model = resolved_dependencies.peft_model.from_pretrained(
                model,
                adapter_root,
                adapter_name=manifest.adapter_name,
                is_trainable=False,
                local_files_only=True,
            )
        except Exception:
            raise _error("ADAPTER_LOAD_FAILED") from None
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        model.eval()
        if hasattr(model, "gradient_checkpointing_disable"):
            model.gradient_checkpointing_disable()
        model.config.use_cache = True
        _post_load_validate(
            model,
            tokenizer,
            manifest,
            current,
            snapshot=snapshot,
            device=device,
            dtype_name=dtype,
        )
        identity = AdapterRuntimeIdentity(
            manifest.adapter_name,
            manifest.adapter_version,
            manifest.base_model,
            manifest.base_revision,
            current.validation_fingerprint,
            current.generation_config,
            device,
            dtype,
            versions,
        )
        return AdapterRuntimeHandle(
            identity=identity,
            loaded_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            model=model,
            tokenizer=tokenizer,
            torch=torch_module,
        )
    except AdapterLoaderError:
        _safe_partial_cleanup(model, tokenizer, torch_module)
        raise
    except Exception:
        _safe_partial_cleanup(model, tokenizer, torch_module)
        raise _error("ADAPTER_LOAD_FAILED") from None


def unload_peft_adapter_runtime(handle: AdapterRuntimeHandle) -> bool:
    """Idempotently release one runtime handle without touching other models."""
    if not isinstance(handle, AdapterRuntimeHandle):
        raise _error("ADAPTER_UNLOAD_FAILED")
    if handle._unloaded:
        return False
    model = handle.model
    tokenizer = handle.tokenizer
    torch_module = handle.torch
    handle.model = None
    handle.tokenizer = None
    handle.torch = None
    handle._unloaded = True
    del model, tokenizer
    try:
        gc.collect()
        if torch_module is not None:
            _release_cuda(torch_module)
    except Exception:
        raise _error("ADAPTER_UNLOAD_FAILED") from None
    return True
