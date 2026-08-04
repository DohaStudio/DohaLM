"""Static, local-only validation for manifest-selected adapter artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import struct
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from src.inference.adapter_manifest import AdapterManifest


MAX_ADAPTER_CONFIG_BYTES = 1024 * 1024
MAX_ADAPTER_METADATA_BYTES = 1024 * 1024
MAX_GENERATION_CONFIG_BYTES = 1024 * 1024
MAX_TRAINING_RESULT_BYTES = 4 * 1024 * 1024
MAX_ADAPTER_WEIGHTS_BYTES = 8 * 1024 * 1024 * 1024
MAX_SAFETENSORS_HEADER_BYTES = 16 * 1024 * 1024
ADAPTER_METADATA_SCHEMA_VERSION = 1

_ERROR_MESSAGES = {
    "ADAPTER_ARTIFACT_NOT_FOUND": "A required adapter artifact is not available.",
    "ADAPTER_ARTIFACT_INVALID": "A required adapter artifact is invalid.",
    "ADAPTER_ARTIFACT_CHECKSUM_MISMATCH": "An adapter artifact checksum does not match.",
    "ADAPTER_CONFIG_INCOMPATIBLE": "The adapter configuration is incompatible.",
    "ADAPTER_WEIGHTS_INVALID": "The adapter weights are invalid.",
    "ADAPTER_METADATA_INCOMPATIBLE": "The adapter metadata is incompatible.",
    "ADAPTER_GENERATION_CONFIG_INVALID": "The adapter generation configuration is invalid.",
}


class AdapterValidationError(RuntimeError):
    """Fail-closed artifact error with a stable, non-sensitive contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = _ERROR_MESSAGES[code]


@dataclass(frozen=True)
class ManifestIdentity:
    schema_version: int
    adapter_name: str
    adapter_version: str
    base_model: str
    base_revision: str
    tokenizer: str
    tokenizer_hash: str
    chat_template_source: str
    chat_template_sha256: str
    peft_version: str
    transformers_version: str
    torch_version: str
    evaluation_fingerprint: str
    training_run_id: str
    created_at: str


@dataclass(frozen=True)
class ValidatedArtifactIdentity:
    name: str
    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class AdapterConfigSummary:
    peft_type: str
    task_type: str
    rank: int
    lora_alpha: float
    lora_dropout: float
    target_modules: tuple[str, ...]
    bias: str
    inference_mode: bool


@dataclass(frozen=True)
class AdapterWeightsSummary:
    tensor_count: int
    header_bytes: int
    data_bytes: int
    dtypes: tuple[str, ...]


@dataclass(frozen=True)
class AdapterMetadataSummary:
    schema_version: int
    training_method: str
    dataset_fingerprint: str
    source_commit: str


@dataclass(frozen=True)
class GenerationConfigSummary:
    max_new_tokens: int
    temperature: float
    top_p: float
    top_k: int
    repetition_penalty: float
    do_sample: bool
    eos_token_ids: tuple[int, ...]
    pad_token_id: int | None
    request_override_policy: str


@dataclass(frozen=True)
class AdapterValidationResult:
    manifest: ManifestIdentity
    artifacts: tuple[ValidatedArtifactIdentity, ...]
    adapter_config: AdapterConfigSummary
    weights: AdapterWeightsSummary
    metadata: AdapterMetadataSummary
    generation_config: GenerationConfigSummary
    validation_fingerprint: str
    warnings: tuple[str, ...]
    validated_at: str


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int


def _error(code: str) -> AdapterValidationError:
    return AdapterValidationError(code)


def _path_identity(path: Path) -> _FileIdentity:
    value = path.stat(follow_symlinks=False)
    return _FileIdentity(
        device=value.st_dev,
        inode=value.st_ino,
        size=value.st_size,
        modified_ns=value.st_mtime_ns,
    )


def _stream_identity(stream: BinaryIO) -> _FileIdentity:
    value = os.fstat(stream.fileno())
    return _FileIdentity(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _artifact_path(manifest: AdapterManifest, relative_path: str) -> Path:
    root = manifest.manifest_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise _error("ADAPTER_ARTIFACT_INVALID") from None
    return candidate


def _read_and_hash(
    manifest: AdapterManifest,
    *,
    name: str,
    relative_path: str,
    expected_sha256: str,
    maximum_bytes: int,
    keep_payload: bool,
    capture_bytes: int | None = None,
) -> tuple[ValidatedArtifactIdentity, bytes | None]:
    path = _artifact_path(manifest, relative_path)
    try:
        if path.is_symlink():
            raise _error("ADAPTER_ARTIFACT_INVALID")
        if not path.exists():
            raise _error("ADAPTER_ARTIFACT_NOT_FOUND")
        before = _path_identity(path)
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise _error("ADAPTER_ARTIFACT_INVALID")
        if before.size > maximum_bytes:
            raise _error("ADAPTER_ARTIFACT_INVALID")
        digest = hashlib.sha256()
        payload = bytearray() if keep_payload or capture_bytes is not None else None
        with path.open("rb") as stream:
            opened = _stream_identity(stream)
            if opened != before or not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise _error("ADAPTER_ARTIFACT_INVALID")
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > maximum_bytes:
                    raise _error("ADAPTER_ARTIFACT_INVALID")
                digest.update(chunk)
                if payload is not None:
                    if capture_bytes is None:
                        payload.extend(chunk)
                    elif len(payload) < capture_bytes:
                        payload.extend(chunk[: capture_bytes - len(payload)])
        after = _path_identity(path)
        if before != opened or opened != after or total != before.size:
            raise _error("ADAPTER_ARTIFACT_INVALID")
    except AdapterValidationError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _error("ADAPTER_ARTIFACT_INVALID") from None
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise _error("ADAPTER_ARTIFACT_CHECKSUM_MISMATCH")
    identity = ValidatedArtifactIdentity(name, relative_path, actual, total)
    return identity, bytes(payload) if payload is not None else None


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _json_object(payload: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _error(code) from None
    if type(value) is not dict:
        raise _error(code)
    return value


def _text(value: object, code: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise _error(code)
    return value


def _sha256(value: object, code: str) -> str:
    text = _text(value, code)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise _error(code)
    return text


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise _error(code)
    return value


def _finite_number(value: object, code: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise _error(code)
    return float(value)


def _validate_adapter_config(
    value: dict[str, Any], manifest: AdapterManifest
) -> AdapterConfigSummary:
    code = "ADAPTER_CONFIG_INCOMPATIBLE"
    if _text(value.get("base_model_name_or_path"), code) != manifest.base_model:
        raise _error(code)
    revision = value.get("revision")
    if revision is not None and _text(revision, code) != manifest.base_revision:
        raise _error(code)
    peft_type = _text(value.get("peft_type"), code).upper()
    if peft_type != "LORA":
        raise _error(code)
    task_type = _text(value.get("task_type"), code).upper()
    if task_type != "CAUSAL_LM":
        raise _error(code)
    rank = _positive_int(value.get("r"), code)
    alpha = _finite_number(value.get("lora_alpha"), code)
    dropout = _finite_number(value.get("lora_dropout"), code)
    if alpha <= 0 or not 0 <= dropout <= 1:
        raise _error(code)
    targets = value.get("target_modules")
    if type(targets) is not list or not targets:
        raise _error(code)
    normalized_targets = tuple(_text(target, code) for target in targets)
    if len(set(normalized_targets)) != len(normalized_targets):
        raise _error(code)
    bias = _text(value.get("bias"), code).lower()
    if bias not in {"none", "all", "lora_only"}:
        raise _error(code)
    if value.get("inference_mode") is not True:
        raise _error(code)
    return AdapterConfigSummary(
        peft_type, task_type, rank, alpha, dropout, normalized_targets, bias, True
    )


def _validate_safetensors(
    payload: bytes, size: int, relative_path: str
) -> AdapterWeightsSummary:
    code = "ADAPTER_WEIGHTS_INVALID"
    if PurePosixPath(relative_path).suffix != ".safetensors" or size < 10:
        raise _error(code)
    try:
        length_payload = payload[:8]
        if len(length_payload) != 8:
            raise _error(code)
        header_length = struct.unpack("<Q", length_payload)[0]
        if (
            header_length < 2
            or header_length % 8 != 0
            or header_length > MAX_SAFETENSORS_HEADER_BYTES
            or header_length > size - 8
        ):
            raise _error(code)
        header_payload = payload[8 : 8 + header_length]
        if len(header_payload) != header_length or not header_payload.startswith(b"{"):
            raise _error(code)
    except AdapterValidationError:
        raise
    except (OverflowError, struct.error):
        raise _error(code) from None
    header = _json_object(header_payload, code)
    tensors = [(name, item) for name, item in header.items() if name != "__metadata__"]
    if not tensors:
        raise _error(code)
    data_bytes = size - 8 - header_length
    ranges: list[tuple[int, int]] = []
    dtypes: set[str] = set()
    for name, item in tensors:
        if type(name) is not str or not name or type(item) is not dict:
            raise _error(code)
        dtype = _text(item.get("dtype"), code)
        shape = item.get("shape")
        offsets = item.get("data_offsets")
        if (
            type(shape) is not list
            or any(type(dimension) is not int or dimension < 0 for dimension in shape)
            or type(offsets) is not list
            or len(offsets) != 2
            or any(type(offset) is not int or offset < 0 for offset in offsets)
        ):
            raise _error(code)
        start, end = offsets
        if start > end or end > data_bytes:
            raise _error(code)
        ranges.append((start, end))
        dtypes.add(dtype)
    if len(set(ranges)) != len(ranges):
        raise _error(code)
    previous_end = 0
    for start, end in sorted(ranges):
        if start != previous_end:
            raise _error(code)
        previous_end = end
    if previous_end != data_bytes:
        raise _error(code)
    return AdapterWeightsSummary(
        len(tensors), header_length, data_bytes, tuple(sorted(dtypes))
    )


def _validate_metadata(
    value: dict[str, Any], manifest: AdapterManifest
) -> AdapterMetadataSummary:
    code = "ADAPTER_METADATA_INCOMPATIBLE"
    if value.get("schema_version") != ADAPTER_METADATA_SCHEMA_VERSION:
        raise _error(code)
    expected = {
        "adapter_name": manifest.adapter_name,
        "adapter_version": manifest.adapter_version,
        "base_model": manifest.base_model,
        "base_revision": manifest.base_revision,
        "evaluation_fingerprint": manifest.evaluation_fingerprint,
        "created_at": manifest.created_at,
    }
    if any(
        value.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise _error(code)
    tokenizer = value.get("tokenizer")
    template = value.get("chat_template")
    training = value.get("training_run")
    if (
        type(tokenizer) is not dict
        or tokenizer.get("name") != manifest.tokenizer
        or tokenizer.get("sha256") != manifest.tokenizer_hash
        or type(template) is not dict
        or template.get("source") != manifest.chat_template.source
        or template.get("sha256") != manifest.chat_template.sha256
        or type(training) is not dict
        or training.get("id") != manifest.training_run.id
    ):
        raise _error(code)
    method = _text(value.get("training_method"), code).lower()
    if method != "qlora":
        raise _error(code)
    dataset_fingerprint = _sha256(value.get("dataset_fingerprint"), code)
    source_commit = _text(value.get("source_commit"), code)
    if len(source_commit) not in {40, 64} or any(
        c not in "0123456789abcdef" for c in source_commit
    ):
        raise _error(code)
    checksums = value.get("artifact_checksums")
    expected_checksums = {
        "adapter_config": manifest.adapter_config.sha256,
        "adapter_weights": manifest.adapter_weights.sha256,
        "generation_config": manifest.generation_config.sha256,
        "training_result": manifest.training_run.result_sha256,
    }
    if type(checksums) is not dict or any(
        checksums.get(key) != checksum for key, checksum in expected_checksums.items()
    ):
        raise _error(code)
    return AdapterMetadataSummary(
        ADAPTER_METADATA_SCHEMA_VERSION, method, dataset_fingerprint, source_commit
    )


def _token_ids(value: object, code: str) -> tuple[int, ...]:
    candidates = value if type(value) is list else [value]
    if not candidates or any(type(item) is not int or item < 0 for item in candidates):
        raise _error(code)
    result = tuple(candidates)
    if len(set(result)) != len(result):
        raise _error(code)
    return result


def _validate_generation_config(
    value: dict[str, Any], manifest: AdapterManifest
) -> GenerationConfigSummary:
    code = "ADAPTER_GENERATION_CONFIG_INVALID"
    allowed = {
        "max_new_tokens",
        "temperature",
        "top_p",
        "top_k",
        "repetition_penalty",
        "do_sample",
        "eos_token_id",
        "pad_token_id",
    }
    if set(value) != allowed:
        raise _error(code)
    maximum = _positive_int(value["max_new_tokens"], code)
    temperature = _finite_number(value["temperature"], code)
    top_p = _finite_number(value["top_p"], code)
    top_k = value["top_k"]
    penalty = _finite_number(value["repetition_penalty"], code)
    if (
        maximum > 1024
        or not 0 <= temperature <= 2
        or not 0 < top_p <= 1
        or type(top_k) is not int
        or not 0 <= top_k <= 1000
        or not 0.5 <= penalty <= 2
        or type(value["do_sample"]) is not bool
    ):
        raise _error(code)
    eos_ids = _token_ids(value["eos_token_id"], code)
    pad = value["pad_token_id"]
    if pad is not None and (type(pad) is not int or pad < 0):
        raise _error(code)
    return GenerationConfigSummary(
        maximum,
        temperature,
        top_p,
        top_k,
        penalty,
        value["do_sample"],
        eos_ids,
        pad,
        manifest.generation_config.request_override_policy,
    )


def _canonical_fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_adapter_artifacts(manifest: AdapterManifest) -> AdapterValidationResult:
    """Validate local artifacts without importing PEFT or loading any tensor."""
    if not isinstance(manifest, AdapterManifest):
        raise _error("ADAPTER_ARTIFACT_INVALID")
    config_identity, config_payload = _read_and_hash(
        manifest,
        name="adapter_config",
        relative_path=manifest.adapter_config.path,
        expected_sha256=manifest.adapter_config.sha256,
        maximum_bytes=MAX_ADAPTER_CONFIG_BYTES,
        keep_payload=True,
    )
    if PurePosixPath(manifest.adapter_weights.path).suffix != ".safetensors":
        raise _error("ADAPTER_WEIGHTS_INVALID")
    weights_identity, weights_payload = _read_and_hash(
        manifest,
        name="adapter_weights",
        relative_path=manifest.adapter_weights.path,
        expected_sha256=manifest.adapter_weights.sha256,
        maximum_bytes=MAX_ADAPTER_WEIGHTS_BYTES,
        keep_payload=False,
        capture_bytes=MAX_SAFETENSORS_HEADER_BYTES + 8,
    )
    metadata_identity, metadata_payload = _read_and_hash(
        manifest,
        name="metadata",
        relative_path=manifest.metadata.path,
        expected_sha256=manifest.metadata.sha256,
        maximum_bytes=MAX_ADAPTER_METADATA_BYTES,
        keep_payload=True,
    )
    generation_identity, generation_payload = _read_and_hash(
        manifest,
        name="generation_config",
        relative_path=manifest.generation_config.path,
        expected_sha256=manifest.generation_config.sha256,
        maximum_bytes=MAX_GENERATION_CONFIG_BYTES,
        keep_payload=True,
    )
    training_identity, _ = _read_and_hash(
        manifest,
        name="training_result",
        relative_path=manifest.training_run.result_path,
        expected_sha256=manifest.training_run.result_sha256,
        maximum_bytes=MAX_TRAINING_RESULT_BYTES,
        keep_payload=False,
    )
    assert config_payload is not None and metadata_payload is not None
    assert weights_payload is not None
    assert generation_payload is not None
    config_summary = _validate_adapter_config(
        _json_object(config_payload, "ADAPTER_CONFIG_INCOMPATIBLE"), manifest
    )
    weights_summary = _validate_safetensors(
        weights_payload, weights_identity.size_bytes, weights_identity.relative_path
    )
    metadata_summary = _validate_metadata(
        _json_object(metadata_payload, "ADAPTER_METADATA_INCOMPATIBLE"), manifest
    )
    generation_summary = _validate_generation_config(
        _json_object(generation_payload, "ADAPTER_GENERATION_CONFIG_INVALID"), manifest
    )
    identity = ManifestIdentity(
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
    artifacts = tuple(
        sorted(
            (
                config_identity,
                weights_identity,
                metadata_identity,
                generation_identity,
                training_identity,
            ),
            key=lambda item: item.name,
        )
    )
    normalized = {
        "manifest": asdict(identity),
        "artifacts": [asdict(item) for item in artifacts],
        "adapter_config": asdict(config_summary),
        "weights": asdict(weights_summary),
        "metadata": asdict(metadata_summary),
        "generation_config": asdict(generation_summary),
    }
    return AdapterValidationResult(
        identity,
        artifacts,
        config_summary,
        weights_summary,
        metadata_summary,
        generation_summary,
        _canonical_fingerprint(normalized),
        (),
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
