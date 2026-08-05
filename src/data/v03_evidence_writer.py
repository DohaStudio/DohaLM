"""Atomic no-replace publication for V03 evidence artifacts."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path

from .v03_evidence import (
    ARTIFACT_FILENAMES,
    V03EvidenceArtifact,
    V03EvidenceError,
    load_v03_evidence,
    serialize_v03_evidence,
)


@dataclass(frozen=True)
class EvidenceWriteResult:
    artifact_type: str
    destination_name: str
    artifact_checksum: str
    output_fingerprint: str
    bytes_written: int


def _raise(code: str) -> None:
    raise V03EvidenceError(code)


def _sync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        _raise("V03_EVIDENCE_WRITE_INCOMPLETE")


def _publish_no_replace(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError:
        _raise("V03_EVIDENCE_ALREADY_EXISTS")
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            _raise("V03_EVIDENCE_ALREADY_EXISTS")
        if exc.errno in {errno.EXDEV, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            _raise("V03_EVIDENCE_NO_REPLACE_UNSUPPORTED")
        _raise("V03_EVIDENCE_ATOMIC_WRITE_FAILED")


def _validate_destination(destination: Path, artifact: V03EvidenceArtifact) -> Path:
    if not isinstance(destination, Path) or not isinstance(
        artifact, V03EvidenceArtifact
    ):
        _raise("V03_EVIDENCE_PATH_INVALID")
    expected_name = ARTIFACT_FILENAMES.get(artifact.artifact_type)
    if expected_name is None or destination.name != expected_name:
        _raise("V03_EVIDENCE_PATH_INVALID")
    parent = destination.parent
    try:
        if parent.is_symlink() or not parent.is_dir():
            _raise("V03_EVIDENCE_PATH_INVALID")
        if destination.is_symlink():
            _raise("V03_EVIDENCE_PATH_INVALID")
        resolved_parent = parent.resolve(strict=True)
        if destination.resolve(strict=False).parent != resolved_parent:
            _raise("V03_EVIDENCE_PATH_INVALID")
    except V03EvidenceError:
        raise
    except (OSError, RuntimeError, ValueError):
        _raise("V03_EVIDENCE_PATH_INVALID")
    return parent


def write_v03_evidence(
    *,
    destination: Path,
    artifact: V03EvidenceArtifact,
) -> EvidenceWriteResult:
    """Publish canonical evidence exactly once using a same-directory hard link."""
    parent = _validate_destination(destination, artifact)
    temporary = destination.with_name(destination.name + ".tmp")
    if destination.exists():
        _raise("V03_EVIDENCE_ALREADY_EXISTS")
    if temporary.exists() or temporary.is_symlink():
        _raise("V03_EVIDENCE_TEMPORARY_COLLISION")
    payload = serialize_v03_evidence(artifact)
    temporary_owned = False
    published = False
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            temporary_owned = True
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                written = handle.write(payload)
                if written != len(payload):
                    _raise("V03_EVIDENCE_ATOMIC_WRITE_FAILED")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            _raise("V03_EVIDENCE_TEMPORARY_COLLISION")
        except V03EvidenceError:
            raise
        except OSError:
            _raise("V03_EVIDENCE_ATOMIC_WRITE_FAILED")

        _publish_no_replace(temporary, destination)
        published = True
        try:
            temporary.unlink()
            temporary_owned = False
        except OSError:
            _raise("V03_EVIDENCE_WRITE_INCOMPLETE")
        _sync_parent_directory(parent)
        loaded = load_v03_evidence(destination)
        if loaded != artifact or destination.read_bytes() != payload:
            _raise("V03_EVIDENCE_WRITE_INCOMPLETE")
        return EvidenceWriteResult(
            artifact_type=artifact.artifact_type,
            destination_name=destination.name,
            artifact_checksum=artifact.artifact_checksum,
            output_fingerprint=artifact.output_fingerprint,
            bytes_written=len(payload),
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_owned:
            try:
                temporary.unlink()
            except OSError:
                if not published:
                    _raise("V03_EVIDENCE_WRITE_INCOMPLETE")
