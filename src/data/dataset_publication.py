"""Deterministic publication transaction for Common Dataset contract pairs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import AtomicArtifactDirectory
from .checksums import canonical_json_bytes, checksum_value
from .common_dataset_contracts import (
    CommonDatasetValidationError,
    validate_dataset_manifest,
    validate_dataset_publication_scenario,
    validate_dataset_version,
    verify_common_contract_runtime,
)
from .dataset_governance import (
    ApprovedDatasetVersion,
    DatasetGovernanceError,
    DatasetVersionIdentity,
)
from .errors import DataPipelineError

_REQUIRED_METADATA = frozenset(
    {
        "created_at",
        "created_by",
        "producer",
        "manifest_format_version",
        "dataset_domain",
        "source",
        "license_status",
        "commercial_usage_status",
        "redistribution_allowed",
        "object_file_artifact_refs",
        "content_checksum_set_id",
        "split_id",
        "deletion_status",
    }
)
_OPTIONAL_METADATA = frozenset(
    {"supersedes", "correlation_id", "workspace_id", "job_id", "extensions"}
)
_VERSION_FILE = "dataset-version.json"
_MANIFEST_FILE = "dataset-manifest.json"
_FILES = frozenset({_VERSION_FILE, _MANIFEST_FILE})


class DatasetPublicationError(RuntimeError):
    """A publication input, validation, or persistence operation failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:dataset_publication")


@dataclass(frozen=True, init=False)
class DatasetPublicationMetadata:
    """Immutable snapshot of caller-supplied Manifest publication fields."""

    _canonical_payload: bytes = field(repr=False)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DatasetPublicationMetadata:
        if not isinstance(payload, Mapping):
            raise DatasetPublicationError("PUBLICATION_METADATA_INVALID", "input")
        keys = frozenset(payload)
        if not _REQUIRED_METADATA <= keys or not keys <= (
            _REQUIRED_METADATA | _OPTIONAL_METADATA
        ):
            raise DatasetPublicationError("PUBLICATION_METADATA_INVALID", "input")
        value = object.__new__(cls)
        object.__setattr__(
            value, "_canonical_payload", _canonicalize(payload, "metadata")
        )
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return _decode_object(self._canonical_payload, "metadata")


@dataclass(frozen=True, init=False)
class DatasetPublicationResult:
    """Immutable result of a newly committed or idempotently replayed pair."""

    identity: DatasetVersionIdentity
    storage_key: str
    pair_fingerprint: str
    published: bool
    _version_bytes: bytes = field(repr=False, compare=False)
    _manifest_bytes: bytes = field(repr=False, compare=False)

    @classmethod
    def _create(
        cls,
        version: Mapping[str, Any],
        manifest: Mapping[str, Any],
        *,
        storage_key: str,
        pair_fingerprint: str,
        published: bool,
    ) -> DatasetPublicationResult:
        value = object.__new__(cls)
        object.__setattr__(
            value,
            "identity",
            DatasetVersionIdentity(
                object_id=version["object_id"],
                dataset_id=version["dataset_id"],
                dataset_version=version["dataset_version"],
            ),
        )
        object.__setattr__(value, "storage_key", storage_key)
        object.__setattr__(value, "pair_fingerprint", pair_fingerprint)
        object.__setattr__(value, "published", published)
        object.__setattr__(value, "_version_bytes", canonical_json_bytes(version))
        object.__setattr__(value, "_manifest_bytes", canonical_json_bytes(manifest))
        return value

    @property
    def dataset_version(self) -> dict[str, Any]:
        return _decode_object(self._version_bytes, "result")

    @property
    def dataset_manifest(self) -> dict[str, Any]:
        return _decode_object(self._manifest_bytes, "result")


def publish_dataset_version(
    approved: ApprovedDatasetVersion,
    *,
    metadata: DatasetPublicationMetadata,
    upstream_objects: Sequence[Mapping[str, Any]],
    evaluated_at: str,
    publication_root: Path,
) -> DatasetPublicationResult:
    """Build, validate, and atomically publish one frozen/issued pair."""

    verify_common_contract_runtime()
    approved_payload = _approved_payload(approved)
    metadata_payload = _metadata_payload(metadata)
    upstream = _snapshot_upstream(upstream_objects)

    frozen = dict(approved_payload)
    frozen.update(status="frozen", frozen=True, training_allowed=True)
    manifest = _build_manifest(frozen, metadata_payload)
    scenario = {
        "evaluated_at": evaluated_at,
        "objects": [*upstream, frozen, manifest],
    }
    _validate_pair(frozen, manifest, scenario)

    storage_key = checksum_value(
        {
            "dataset_id": frozen["dataset_id"],
            "dataset_version": frozen["dataset_version"],
            "object_id": frozen["object_id"],
        }
    ).removeprefix("sha256:")
    if len(storage_key) != 64 or any(c not in "0123456789abcdef" for c in storage_key):
        raise DatasetPublicationError("PUBLICATION_STORAGE_KEY_INVALID", "identity")
    pair_fingerprint = _pair_fingerprint(frozen, manifest)
    expected = {
        _VERSION_FILE: canonical_json_bytes(frozen),
        _MANIFEST_FILE: canonical_json_bytes(manifest),
    }
    final_path = Path(publication_root) / storage_key

    if final_path.exists():
        return _replay(
            final_path,
            expected,
            frozen,
            manifest,
            scenario,
            storage_key,
            pair_fingerprint,
        )

    transaction = AtomicArtifactDirectory(final_path)
    publish_failed_before_rename = False
    try:
        with transaction as staging:
            for name, payload in expected.items():
                _write_canonical_file(staging / name, payload)
            _verify_directory(staging, expected, frozen, manifest, scenario)
            try:
                transaction.publish()
            except DataPipelineError:
                publish_failed_before_rename = bool(
                    transaction.staging_path is not None
                    and transaction.staging_path.exists()
                )
                raise
    except DataPipelineError as exc:
        if final_path.exists() and (
            transaction.staging_path is None or publish_failed_before_rename
        ):
            return _replay(
                final_path,
                expected,
                frozen,
                manifest,
                scenario,
                storage_key,
                pair_fingerprint,
            )
        raise DatasetPublicationError("PUBLICATION_COMMIT_FAILED", "commit") from exc
    except OSError as exc:
        raise DatasetPublicationError("PUBLICATION_IO_FAILED", "persistence") from exc

    _verify_directory(final_path, expected, frozen, manifest, scenario)
    return DatasetPublicationResult._create(
        frozen,
        manifest,
        storage_key=storage_key,
        pair_fingerprint=pair_fingerprint,
        published=True,
    )


def _approved_payload(approved: ApprovedDatasetVersion) -> dict[str, Any]:
    if not isinstance(approved, ApprovedDatasetVersion):
        raise DatasetPublicationError("APPROVED_VERSION_INVALID", "input")
    try:
        payload = approved.payload
        validate_dataset_version(payload)
        identity = DatasetVersionIdentity(
            payload["object_id"], payload["dataset_id"], payload["dataset_version"]
        )
        fingerprint = checksum_value(payload)
        if (
            payload.get("status") != "approved"
            or payload.get("approved") is not True
            or payload.get("frozen") is not False
            or payload.get("training_allowed") is not False
            or identity != approved.identity
            or fingerprint != approved.fingerprint
        ):
            raise DatasetPublicationError("APPROVED_VERSION_INVALID", "input")
    except DatasetPublicationError:
        raise
    except (
        AttributeError,
        CommonDatasetValidationError,
        DatasetGovernanceError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetPublicationError("APPROVED_VERSION_INVALID", "input") from exc
    return payload


def _metadata_payload(metadata: DatasetPublicationMetadata) -> dict[str, Any]:
    if not isinstance(metadata, DatasetPublicationMetadata):
        raise DatasetPublicationError("PUBLICATION_METADATA_INVALID", "input")
    payload = metadata.payload
    if frozenset(payload) - (_REQUIRED_METADATA | _OPTIONAL_METADATA):
        raise DatasetPublicationError("PUBLICATION_METADATA_INVALID", "input")
    return payload


def _snapshot_upstream(
    upstream_objects: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(upstream_objects, (str, bytes)):
        raise DatasetPublicationError("UPSTREAM_OBJECTS_INVALID", "input")
    try:
        values = [
            _decode_object(_canonicalize(item, "upstream"), "upstream")
            for item in upstream_objects
        ]
    except TypeError as exc:
        raise DatasetPublicationError("UPSTREAM_OBJECTS_INVALID", "input") from exc
    return values


def _build_manifest(
    frozen: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = {
        "schema_name": "dataset_manifest",
        "schema_version": "1.0.0",
        "object_id": frozen["dataset_manifest_id"],
        "dataset_manifest_id": frozen["dataset_manifest_id"],
        "manifest_status": "issued",
        "source_dataset_version_id": frozen["object_id"],
        "source_dataset_version_checksum": frozen["content_fingerprint"],
        "dataset_id": frozen["dataset_id"],
        "dataset_version": frozen["dataset_version"],
        "training_allowed": True,
        "item_count": frozen["candidate_count"],
    }
    for key in _REQUIRED_METADATA | _OPTIONAL_METADATA:
        if key in metadata:
            manifest[key] = metadata[key]
    manifest["manifest_checksum"] = checksum_value(manifest)
    return manifest


def _validate_pair(
    version: Mapping[str, Any],
    manifest: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> None:
    try:
        validate_dataset_version(version)
        validate_dataset_manifest(manifest)
        _require_domain_identity(version, manifest)
        validate_dataset_publication_scenario(scenario)
    except CommonDatasetValidationError as exc:
        raise DatasetPublicationError(
            "PUBLICATION_CONTRACT_INVALID", "validation"
        ) from exc


def _require_domain_identity(
    version: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    pairs = (
        (version.get("dataset_manifest_id"), manifest.get("object_id")),
        (version.get("dataset_manifest_id"), manifest.get("dataset_manifest_id")),
        (version.get("object_id"), manifest.get("source_dataset_version_id")),
        (
            version.get("content_fingerprint"),
            manifest.get("source_dataset_version_checksum"),
        ),
        (version.get("dataset_id"), manifest.get("dataset_id")),
        (version.get("dataset_version"), manifest.get("dataset_version")),
        (version.get("candidate_count"), manifest.get("item_count")),
    )
    projection = dict(manifest)
    checksum = projection.pop("manifest_checksum", None)
    if any(left != right for left, right in pairs) or checksum != checksum_value(
        projection
    ):
        raise DatasetPublicationError("PUBLICATION_DOMAIN_INVALID", "validation")


def _pair_fingerprint(version: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    return checksum_value({"dataset_manifest": manifest, "dataset_version": version})


def _replay(
    final_path: Path,
    expected: Mapping[str, bytes],
    version: Mapping[str, Any],
    manifest: Mapping[str, Any],
    scenario: Mapping[str, Any],
    storage_key: str,
    pair_fingerprint: str,
) -> DatasetPublicationResult:
    _verify_directory(final_path, expected, version, manifest, scenario)
    return DatasetPublicationResult._create(
        version,
        manifest,
        storage_key=storage_key,
        pair_fingerprint=pair_fingerprint,
        published=False,
    )


def _verify_directory(
    path: Path,
    expected: Mapping[str, bytes],
    version: Mapping[str, Any],
    manifest: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> None:
    try:
        entries = tuple(path.iterdir())
        if {entry.name for entry in entries} != _FILES or any(
            not entry.is_file() for entry in entries
        ):
            raise DatasetPublicationError("PUBLICATION_CORRUPT", "verification")
        actual = {name: (path / name).read_bytes() for name in _FILES}
        decoded = {name: _strict_json(payload) for name, payload in actual.items()}
        if any(canonical_json_bytes(decoded[name]) != actual[name] for name in _FILES):
            raise DatasetPublicationError("PUBLICATION_CORRUPT", "verification")
        if actual != dict(expected):
            raise DatasetPublicationError("PUBLICATION_CONFLICT", "verification")
    except DatasetPublicationError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatasetPublicationError("PUBLICATION_CORRUPT", "verification") from exc
    _require_domain_identity(decoded[_VERSION_FILE], decoded[_MANIFEST_FILE])
    if _pair_fingerprint(
        decoded[_VERSION_FILE], decoded[_MANIFEST_FILE]
    ) != _pair_fingerprint(version, manifest):
        raise DatasetPublicationError("PUBLICATION_CONFLICT", "verification")
    persisted_scenario = dict(scenario)
    persisted_scenario["objects"] = [
        *list(scenario["objects"])[:-2],
        decoded[_VERSION_FILE],
        decoded[_MANIFEST_FILE],
    ]
    _validate_pair(decoded[_VERSION_FILE], decoded[_MANIFEST_FILE], persisted_scenario)


def _write_canonical_file(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DatasetPublicationError("PUBLICATION_WRITE_FAILED", "staging") from exc


def _strict_json(payload: bytes) -> dict[str, Any]:
    def pairs(value: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    value = json.loads(
        payload,
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
    )
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _canonicalize(payload: Mapping[str, Any], stage: str) -> bytes:
    try:
        return canonical_json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise DatasetPublicationError(
            "PUBLICATION_CANONICALIZATION_FAILED", stage
        ) from exc


def _decode_object(payload: bytes, stage: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise DatasetPublicationError("PUBLICATION_SNAPSHOT_INVALID", stage) from exc
    if not isinstance(value, dict):
        raise DatasetPublicationError("PUBLICATION_SNAPSHOT_INVALID", stage)
    return value


__all__ = [
    "DatasetPublicationError",
    "DatasetPublicationMetadata",
    "DatasetPublicationResult",
    "publish_dataset_version",
]
