"""Strict, local-only schema loader for DohaLM adapter manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


ADAPTER_MANIFEST_FILENAME = "adapter-manifest.json"
ADAPTER_MANIFEST_SCHEMA_VERSION = 1
MAX_ADAPTER_MANIFEST_BYTES = 1024 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_name",
        "adapter_version",
        "base_model",
        "base_revision",
        "tokenizer",
        "tokenizer_hash",
        "chat_template",
        "peft_version",
        "transformers_version",
        "torch_version",
        "generation_config",
        "evaluation_fingerprint",
        "training_run",
        "created_at",
        "adapter_config",
        "adapter_weights",
        "metadata",
    }
)

_ERROR_MESSAGES = {
    "ADAPTER_MANIFEST_NOT_FOUND": "The adapter manifest is not available.",
    "ADAPTER_MANIFEST_INVALID": "The adapter manifest is invalid.",
    "ADAPTER_MANIFEST_UNSUPPORTED_VERSION": (
        "The adapter manifest schema version is not supported."
    ),
    "ADAPTER_MANIFEST_PATH_INVALID": "The adapter manifest contains an invalid path.",
}


class AdapterManifestError(RuntimeError):
    """Fail-closed manifest error without local path or payload disclosure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = _ERROR_MESSAGES[code]


@dataclass(frozen=True)
class ArtifactReference:
    path: str
    sha256: str


@dataclass(frozen=True)
class ChatTemplateReference:
    source: str
    sha256: str


@dataclass(frozen=True)
class GenerationConfigReference:
    path: str
    sha256: str
    request_override_policy: str


@dataclass(frozen=True)
class TrainingRunReference:
    id: str
    result_path: str
    result_sha256: str


@dataclass(frozen=True)
class AdapterManifest:
    schema_version: int
    adapter_name: str
    adapter_version: str
    base_model: str
    base_revision: str
    tokenizer: str
    tokenizer_hash: str
    chat_template: ChatTemplateReference
    peft_version: str
    transformers_version: str
    torch_version: str
    generation_config: GenerationConfigReference
    evaluation_fingerprint: str
    training_run: TrainingRunReference
    created_at: str
    adapter_config: ArtifactReference
    adapter_weights: ArtifactReference
    metadata: ArtifactReference
    manifest_path: Path = field(repr=False, compare=False)

    @property
    def manifest_root(self) -> Path:
        return self.manifest_path.parent

    def resolve_artifact(self, reference: ArtifactReference) -> Path:
        """Return a validated absolute artifact path rooted at the manifest."""
        if not isinstance(reference, ArtifactReference):
            raise TypeError("reference must be an ArtifactReference")
        return _resolve_relative_path(self.manifest_root, reference.path)

    @property
    def generation_config_path(self) -> Path:
        return _resolve_relative_path(self.manifest_root, self.generation_config.path)

    @property
    def training_result_path(self) -> Path:
        return _resolve_relative_path(self.manifest_root, self.training_run.result_path)


def _invalid() -> AdapterManifestError:
    return AdapterManifestError("ADAPTER_MANIFEST_INVALID")


def _strict_object(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise _invalid()
    return value


def _non_empty_string(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise _invalid()
    return value


def _sha256(value: object) -> str:
    candidate = _non_empty_string(value)
    if _SHA256.fullmatch(candidate) is None:
        raise _invalid()
    return candidate


def _created_at(value: object) -> str:
    candidate = _non_empty_string(value)
    if _UTC_RFC3339.fullmatch(candidate) is None:
        raise _invalid()
    try:
        datetime.fromisoformat(candidate.removesuffix("Z") + "+00:00")
    except ValueError:
        raise _invalid() from None
    return candidate


def _resolve_relative_path(root: Path, value: object) -> Path:
    text = _non_empty_string(value)
    try:
        posix = PurePosixPath(text)
        windows = PureWindowsPath(text)
    except (OSError, ValueError):
        raise AdapterManifestError("ADAPTER_MANIFEST_PATH_INVALID") from None
    if (
        "\\" in text
        or not posix.parts
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
    ):
        raise AdapterManifestError("ADAPTER_MANIFEST_PATH_INVALID")
    relative = Path(*posix.parts)
    try:
        resolved_root = root.resolve(strict=False)
        resolved = (resolved_root / relative).resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        raise AdapterManifestError("ADAPTER_MANIFEST_PATH_INVALID") from None
    return resolved


def _artifact(value: object, root: Path) -> ArtifactReference:
    item = _strict_object(value, frozenset({"path", "sha256"}))
    path = _non_empty_string(item["path"])
    _resolve_relative_path(root, path)
    return ArtifactReference(path=path, sha256=_sha256(item["sha256"]))


def _chat_template(value: object) -> ChatTemplateReference:
    item = _strict_object(value, frozenset({"source", "sha256"}))
    return ChatTemplateReference(
        source=_non_empty_string(item["source"]),
        sha256=_sha256(item["sha256"]),
    )


def _generation_config(value: object, root: Path) -> GenerationConfigReference:
    item = _strict_object(
        value, frozenset({"path", "sha256", "request_override_policy"})
    )
    path = _non_empty_string(item["path"])
    _resolve_relative_path(root, path)
    policy = _non_empty_string(item["request_override_policy"])
    if policy != "api_bounds_only":
        raise _invalid()
    return GenerationConfigReference(
        path=path,
        sha256=_sha256(item["sha256"]),
        request_override_policy=policy,
    )


def _training_run(value: object, root: Path) -> TrainingRunReference:
    item = _strict_object(
        value, frozenset({"id", "result_path", "result_sha256"})
    )
    result_path = _non_empty_string(item["result_path"])
    _resolve_relative_path(root, result_path)
    return TrainingRunReference(
        id=_non_empty_string(item["id"]),
        result_path=result_path,
        result_sha256=_sha256(item["result_sha256"]),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _reject_non_standard_number(_value: str) -> None:
    raise _invalid()


def _parse_json(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_standard_number,
        )
    except AdapterManifestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _invalid() from None
    return _strict_object(value, _TOP_LEVEL_FIELDS)


def load_adapter_manifest(path: Path) -> AdapterManifest:
    """Load one explicitly named local manifest without artifact I/O."""
    if not isinstance(path, Path):
        raise AdapterManifestError("ADAPTER_MANIFEST_PATH_INVALID")
    try:
        if not path.exists():
            raise AdapterManifestError("ADAPTER_MANIFEST_NOT_FOUND")
        if path.is_symlink() or not path.is_file():
            raise AdapterManifestError("ADAPTER_MANIFEST_PATH_INVALID")
        if path.stat().st_size > MAX_ADAPTER_MANIFEST_BYTES:
            raise _invalid()
        payload = path.read_bytes()
        manifest_path = path.resolve(strict=True)
    except AdapterManifestError:
        raise
    except OSError:
        raise _invalid() from None

    value = _parse_json(payload)
    schema_version = value["schema_version"]
    if type(schema_version) is not int:
        raise _invalid()
    if schema_version != ADAPTER_MANIFEST_SCHEMA_VERSION:
        raise AdapterManifestError("ADAPTER_MANIFEST_UNSUPPORTED_VERSION")

    root = manifest_path.parent
    return AdapterManifest(
        schema_version=schema_version,
        adapter_name=_non_empty_string(value["adapter_name"]),
        adapter_version=_non_empty_string(value["adapter_version"]),
        base_model=_non_empty_string(value["base_model"]),
        base_revision=_non_empty_string(value["base_revision"]),
        tokenizer=_non_empty_string(value["tokenizer"]),
        tokenizer_hash=_sha256(value["tokenizer_hash"]),
        chat_template=_chat_template(value["chat_template"]),
        peft_version=_non_empty_string(value["peft_version"]),
        transformers_version=_non_empty_string(value["transformers_version"]),
        torch_version=_non_empty_string(value["torch_version"]),
        generation_config=_generation_config(value["generation_config"], root),
        evaluation_fingerprint=_sha256(value["evaluation_fingerprint"]),
        training_run=_training_run(value["training_run"], root),
        created_at=_created_at(value["created_at"]),
        adapter_config=_artifact(value["adapter_config"], root),
        adapter_weights=_artifact(value["adapter_weights"], root),
        metadata=_artifact(value["metadata"], root),
        manifest_path=manifest_path,
    )
