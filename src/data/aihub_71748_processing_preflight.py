"""Dynamic immutable identity and canonical metadata-only preflight evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Mapping

from src.data.processing.aihub_71748_manifest import (
    validate_aihub_71748_processing_manifest,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping
from src.data.processing.run_contract import RETIRED_APPROVAL_IDS, RETIRED_RUN_IDS
from src.data.processing.runtime_monitor import RuntimeBudget, RuntimeMonitor


RUN_ID = "AIHUB-71748-SFT-PROCESSING-20260730-0006"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0006"
MANIFEST_PATH = "configs/data/aihub-71748-sft-processing-v1.yaml"
BACKEND_PATHS = (
    "src/data/aihub_71748_processing_preflight.py",
    "src/data/processing/aihub_71748_reader.py",
    "src/data/processing/aihub_71748_processor.py",
    "src/data/processing/output_writer.py",
    "src/data/processing/run_contract.py",
    "src/data/processing/approval.py",
    "src/data/processing/runtime_monitor.py",
    "src/data/processing/post_validation.py",
    "scripts/datasets/process_aihub_71748_sft.py",
)
_RUN_ID_PATTERN = re.compile(r"^AIHUB-71748-SFT-PROCESSING-(\d{8})-(\d{4})$")
_APPROVAL_ID_PATTERN = re.compile(
    r"^AIHUB-71748-SFT-PROCESSING-APPROVAL-(\d{8})-(\d{4})$"
)
EXPECTED_ZIP_FILES = 55
EXPECTED_TOTAL_BYTES = 17_256_335_769
ALLOWED_OUTPUTS = (
    "train.jsonl",
    "validation.jsonl",
    "manifest.yaml",
    "statistics.json",
    "checksums.sha256",
    "processing-result.yaml",
)


class ProcessingPreflightError(RuntimeError):
    """Fail-closed preflight error containing no local path or payload."""


@dataclass(frozen=True)
class SourceMetadata:
    zip_files: int
    total_bytes: int
    modified_min_utc: str
    modified_max_utc: str
    filename_aggregate: str
    modified_time_aggregate: str
    components: tuple[str, ...]
    splits: tuple[str, ...]
    payload_reads: int = 0


@dataclass(frozen=True)
class GitFingerprints:
    immutable_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    backend_file_count: int


@dataclass(frozen=True)
class LineageValidation:
    execution_source_commit: str
    governance_record_commit: str
    execution_source_exists: bool
    governance_commit_exists: bool
    governance_reachable_from_origin_develop: bool
    direct_ancestry: bool
    squash_merge_mode: bool
    execution_surface_file_count: int
    execution_surface_paths_equal: bool
    execution_surface_blobs_equal: bool
    manifest_fingerprint_equal: bool
    backend_fingerprint_equal: bool
    valid: bool
    result_code: str


@dataclass(frozen=True)
class PreflightEvidence:
    schema_version: int
    run_id: str
    approval_id: str
    execution_source_commit: str
    governance_record_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    lineage: Mapping[str, object]
    mapping_identity: Mapping[str, object]
    source_snapshot: Mapping[str, object]
    registry_state: Mapping[str, object]
    output_state: Mapping[str, object]
    resource_state: Mapping[str, object]
    runtime_budget: Mapping[str, object]
    memory_budget: Mapping[str, object]
    disk_budget: Mapping[str, object]
    record_budget: Mapping[str, object]
    output_budget: Mapping[str, object]
    zero_call_state: Mapping[str, object]
    generated_at: str
    expires_at: str

    @property
    def immutable_git_commit(self) -> str:
        """Deprecated read-only alias for legacy callers."""

        return self.execution_source_commit


def validate_explicit_identity(
    run_id: str | None,
    approval_id: str | None,
    *,
    allow_synthetic: bool = False,
) -> None:
    """Validate caller-supplied identity without consulting reuse registries."""

    if not run_id:
        raise ProcessingPreflightError("RUN_ID_REQUIRED")
    if not approval_id:
        raise ProcessingPreflightError("APPROVAL_ID_REQUIRED")
    if allow_synthetic and run_id.startswith("SYNTHETIC-") and approval_id.startswith("SYNTHETIC-"):
        return
    run_match = _RUN_ID_PATTERN.fullmatch(run_id)
    if run_match is None:
        raise ProcessingPreflightError("RUN_ID_FORMAT_INVALID")
    approval_match = _APPROVAL_ID_PATTERN.fullmatch(approval_id)
    if approval_match is None:
        raise ProcessingPreflightError("APPROVAL_ID_FORMAT_INVALID")
    if run_match.groups() != approval_match.groups():
        raise ProcessingPreflightError("RUN_APPROVAL_SEQUENCE_MISMATCH")


def _git(repository_root: Path, *arguments: str, text: bool = False) -> bytes | str:
    try:
        return subprocess.check_output(
            ["git", *arguments], cwd=repository_root, text=text,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH") from None


def validate_immutable_commit(repository_root: str | Path, expected_commit: str | None) -> str:
    if not expected_commit:
        raise ProcessingPreflightError("IMMUTABLE_COMMIT_REQUIRED")
    root = Path(repository_root).resolve()
    try:
        commit = str(_git(root, "rev-parse", "--verify", f"{expected_commit}^{{commit}}", text=True)).strip()
        head = str(_git(root, "rev-parse", "HEAD", text=True)).strip()
    except ProcessingPreflightError:
        raise ProcessingPreflightError("SOURCE_COMMIT_NOT_REACHABLE") from None
    if commit != expected_commit or head != expected_commit:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    if status.returncode != 0 or status.stdout.strip():
        raise ProcessingPreflightError("WORKTREE_NOT_CLEAN")
    return commit


def validate_immutable_lineage(
    repository_root: str | Path,
    *,
    execution_source_commit: str | None,
    governance_record_commit: str | None,
    governance_ref: str = "origin/develop",
) -> LineageValidation:
    """Validate direct or squash-merge lineage through an explicit fixed surface."""

    root = Path(repository_root).resolve()
    if not execution_source_commit:
        raise ProcessingPreflightError("EXECUTION_SOURCE_COMMIT_NOT_FOUND")
    if not governance_record_commit:
        raise ProcessingPreflightError("PREFLIGHT_GOVERNANCE_COMMIT_REQUIRED")

    def commit(value: str, error: str) -> str:
        try:
            resolved = str(_git(root, "rev-parse", "--verify", f"{value}^{{commit}}", text=True)).strip()
        except ProcessingPreflightError:
            raise ProcessingPreflightError(error) from None
        if resolved != value:
            raise ProcessingPreflightError(error)
        return resolved

    execution = commit(execution_source_commit, "EXECUTION_SOURCE_COMMIT_NOT_FOUND")
    governance = commit(governance_record_commit, "GOVERNANCE_COMMIT_NOT_FOUND")
    reachable = subprocess.run(
        ["git", "merge-base", "--is-ancestor", governance, governance_ref], cwd=root,
    ).returncode == 0
    if not reachable:
        raise ProcessingPreflightError("GOVERNANCE_COMMIT_NOT_REACHABLE")
    direct = subprocess.run(
        ["git", "merge-base", "--is-ancestor", execution, governance], cwd=root,
    ).returncode == 0
    required = (MANIFEST_PATH, *BACKEND_PATHS)
    trees = []
    for revision in (execution, governance):
        tree = set(str(_git(root, "ls-tree", "-r", "--name-only", revision, text=True)).splitlines())
        trees.append(tree)
        if not set(required) <= tree:
            raise ProcessingPreflightError("EXECUTION_SURFACE_FILE_MISSING")
    blobs_equal = all(
        _git(root, "rev-parse", f"{execution}:{path}", text=True)
        == _git(root, "rev-parse", f"{governance}:{path}", text=True)
        for path in required
    )
    execution_fingerprints = compute_git_fingerprints(root, execution)
    governance_fingerprints = compute_git_fingerprints(root, governance)
    manifest_equal = execution_fingerprints.manifest_sha256 == governance_fingerprints.manifest_sha256
    backend_equal = execution_fingerprints.backend_fingerprint == governance_fingerprints.backend_fingerprint
    if not manifest_equal:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
    if not backend_equal:
        raise ProcessingPreflightError("BACKEND_FINGERPRINT_MISMATCH")
    if not blobs_equal:
        raise ProcessingPreflightError("EXECUTION_SOURCE_TREE_DRIFT")
    return LineageValidation(
        execution_source_commit=execution,
        governance_record_commit=governance,
        execution_source_exists=True,
        governance_commit_exists=True,
        governance_reachable_from_origin_develop=True,
        direct_ancestry=direct,
        squash_merge_mode=not direct,
        execution_surface_file_count=len(required),
        execution_surface_paths_equal=trees[0].intersection(required) == set(required)
        and trees[1].intersection(required) == set(required),
        execution_surface_blobs_equal=True,
        manifest_fingerprint_equal=True,
        backend_fingerprint_equal=True,
        valid=True,
        result_code="DIRECT_ANCESTRY_VALID" if direct else "SQUASH_MERGE_EXECUTION_SURFACE_EQUIVALENT",
    )


def compute_git_fingerprints(
    repository_root: str | Path,
    immutable_commit: str | None,
) -> GitFingerprints:
    """Hash immutable Git blobs, never the mutable worktree or local Dataset."""

    root = Path(repository_root).resolve()
    if not immutable_commit:
        raise ProcessingPreflightError("IMMUTABLE_COMMIT_REQUIRED")
    commit = str(_git(root, "rev-parse", "--verify", f"{immutable_commit}^{{commit}}", text=True)).strip()
    if commit != immutable_commit:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
    manifest = bytes(_git(root, "show", f"{commit}:{MANIFEST_PATH}"))
    paths = list(BACKEND_PATHS)
    tree = set(str(_git(root, "ls-tree", "-r", "--name-only", commit, text=True)).splitlines())
    if MANIFEST_PATH not in tree:
        raise ProcessingPreflightError("MANIFEST_NOT_FOUND")
    if not set(BACKEND_PATHS) <= tree or not paths:
        raise ProcessingPreflightError("BACKEND_FILE_MISSING")
    aggregate = hashlib.sha256()
    for path in sorted(paths):
        content = bytes(_git(root, "show", f"{commit}:{path}"))
        aggregate.update(path.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        aggregate.update(b"\n")
    return GitFingerprints(
        immutable_commit=commit,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        backend_fingerprint=aggregate.hexdigest(),
        backend_file_count=len(paths),
    )


def validate_backend_worktree(repository_root: str | Path, immutable_commit: str | None) -> None:
    if not immutable_commit:
        raise ProcessingPreflightError("IMMUTABLE_COMMIT_REQUIRED")
    root = Path(repository_root).resolve()
    result = subprocess.run(
        ["git", "diff", "--quiet", immutable_commit, "--", MANIFEST_PATH, *BACKEND_PATHS],
        cwd=root,
    )
    if result.returncode != 0:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")


def discover_source_metadata(source_root: str | Path) -> SourceMetadata:
    """Inspect names and stat metadata only; no archive or JSON APIs are used."""

    root = Path(source_root)
    if not root.is_dir():
        raise ProcessingPreflightError("DATASET_ROOT_NOT_FOUND")
    archives = sorted(root.rglob("*.zip"), key=lambda path: path.as_posix().casefold())
    total_bytes = sum(path.stat().st_size for path in archives)
    if len(archives) != EXPECTED_ZIP_FILES or total_bytes != EXPECTED_TOTAL_BYTES:
        raise ProcessingPreflightError("SOURCE_PACKAGE_DRIFT")
    names = [path.name.casefold() for path in archives]
    components: list[str] = []
    if any(name.startswith(("ts_02.", "vs_02.")) for name in names):
        components.append("SFTdata")
    if any(name.startswith("tl_02.") or name == "vl.zip" for name in names):
        components.append("SFTlabel")
    if tuple(components) != ("SFTdata", "SFTlabel"):
        raise ProcessingPreflightError("SOURCE_COMPONENT_MISSING")
    path_parts = {part.casefold() for path in archives for part in path.parts}
    splits = tuple(name for name in ("Training", "Validation") if name.casefold() in path_parts)
    if splits != ("Training", "Validation"):
        raise ProcessingPreflightError("SOURCE_SPLIT_MISSING")
    logical_names = [path.relative_to(root).as_posix() for path in archives]
    stats = [path.stat() for path in archives]
    modified = [item.st_mtime for item in stats]
    def render(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    filename_payload = "".join(f"{name}\n" for name in logical_names).encode("utf-8")
    mtime_payload = "".join(
        f"{name}\0{render(item.st_mtime)}\n"
        for name, item in zip(logical_names, stats, strict=True)
    ).encode("utf-8")
    return SourceMetadata(
        zip_files=len(archives),
        total_bytes=total_bytes,
        modified_min_utc=render(min(modified)),
        modified_max_utc=render(max(modified)),
        filename_aggregate=hashlib.sha256(filename_payload).hexdigest(),
        modified_time_aggregate=hashlib.sha256(mtime_payload).hexdigest(),
        components=tuple(components),
        splits=splits,
    )


def validate_run_unused(
    mapping: ResolvedDatasetMapping,
    *,
    repository_root: str | Path,
    run_id: str,
    approval_id: str,
    immutable_commit: str | None = None,
) -> None:
    validate_explicit_identity(run_id, approval_id)
    if run_id in RETIRED_RUN_IDS:
        raise ProcessingPreflightError("RUN_ID_RETIRED")
    if approval_id in RETIRED_APPROVAL_IDS:
        raise ProcessingPreflightError("APPROVAL_RETIRED")
    run_roots = (
        mapping.processed_root / run_id,
        mapping.processed_root / f"{run_id}.staging",
        mapping.processed_root / f"{run_id}.failed",
        mapping.processed_root / "quarantine" / run_id,
    )
    if any(path.exists() for path in run_roots):
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    evidence_root = mapping.processed_root / "runtime-evidence" / run_id
    try:
        if evidence_root.exists() and (
            not evidence_root.is_dir() or any(evidence_root.iterdir())
        ):
            raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    except OSError:
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED") from None
    approval_roots = (
        mapping.processed_root / "approvals" / f"{approval_id}.json",
        mapping.processed_root / "runtime-evidence" / approval_id,
    )
    if any(path.exists() for path in approval_roots):
        raise ProcessingPreflightError("APPROVAL_ID_ALREADY_USED")
    # Documentation, source constants, fixtures, and examples are declarations,
    # not runtime-use evidence. Only canonical registries and runtime artifacts
    # above can consume an identity.


def validate_output_contract(
    mapping: ResolvedDatasetMapping,
    *,
    minimum_free_bytes: int,
    run_id: str,
) -> dict[str, object]:
    run_root = mapping.processed_root / run_id
    staging_root = run_root.with_name(run_root.name + ".staging")
    quarantine_root = mapping.processed_root / "quarantine" / run_id
    collisions = (run_root, staging_root, run_root.with_name(run_root.name + ".failed"), quarantine_root)
    if any(path.exists() for path in collisions):
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    parent = mapping.processed_root
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    free = shutil.disk_usage(parent).free
    if free < minimum_free_bytes:
        raise ProcessingPreflightError("DISK_BUDGET_INSUFFICIENT")
    return {
        "run_root_exists": False,
        "staging_root_exists": False,
        "quarantine_root_exists": False,
        "same_filesystem": True,
        "free_bytes": free,
    }


def probe_output_parent(mapping: ResolvedDatasetMapping) -> bool:
    """Write, fsync, and remove one private probe outside raw and run roots."""

    parent = mapping.processed_root
    parent.mkdir(parents=True, exist_ok=True)
    if parent == mapping.source_root or parent.is_relative_to(mapping.source_root):
        raise ProcessingPreflightError("OUTPUT_PROBE_FAILED")
    descriptor = -1
    probe_name: str | None = None
    try:
        descriptor, probe_name = tempfile.mkstemp(prefix=".dohalm-preflight-", dir=parent)
        os.write(descriptor, b"probe")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        Path(probe_name).unlink()
        if Path(probe_name).exists():
            raise ProcessingPreflightError("OUTPUT_PROBE_RESIDUE_PRESENT")
    except ProcessingPreflightError:
        raise
    except OSError:
        raise ProcessingPreflightError("OUTPUT_PROBE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if probe_name and Path(probe_name).exists():
            try:
                Path(probe_name).unlink()
            except OSError:
                raise ProcessingPreflightError("OUTPUT_PROBE_RESIDUE_PRESENT") from None
    return True


def validate_resource_providers() -> dict[str, object]:
    started = time.monotonic()
    monitor = RuntimeMonitor(RuntimeBudget())
    monitor.check("preflight")
    if time.monotonic() < started:
        raise ProcessingPreflightError("RUNTIME_PROVIDER_UNAVAILABLE")
    return {
        "memory_provider_available": True,
        "runtime_provider_available": True,
        "current_rss_bytes": monitor.current_rss_bytes,
    }


def preflight_evidence_fingerprint(evidence: PreflightEvidence) -> str:
    try:
        generated = datetime.fromisoformat(evidence.generated_at)
    except ValueError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED") from None
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    payload = {
        key: value for key, value in evidence.__dict__.items()
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def serialize_preflight_evidence(evidence: PreflightEvidence) -> str:
    return json.dumps(evidence.__dict__, sort_keys=True, separators=(",", ":"))


PREFLIGHT_EVIDENCE_FILENAME = "preflight-evidence.json"
_NO_REPLACE_UNSUPPORTED_ERRNOS = frozenset({
    errno.EXDEV,
    errno.EINVAL,
    errno.ENOSYS,
    getattr(errno, "ENOTSUP", errno.ENOSYS),
    getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
})


def canonical_preflight_evidence_path(processed_root: str | Path, run_id: str) -> Path:
    """Return the sole canonical location for an Initial Preflight artifact."""

    return Path(processed_root) / "runtime-evidence" / run_id / PREFLIGHT_EVIDENCE_FILENAME


def _preflight_document_evidence(value: Mapping[str, object]) -> PreflightEvidence:
    fields = set(PreflightEvidence.__dataclass_fields__)
    if not fields <= set(value):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    return deserialize_preflight_evidence({name: value[name] for name in fields})


def _canonical_preflight_document_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_ATOMIC_WRITE_FAILED") from None


def _validate_preflight_document(
    value: Mapping[str, object], *, expected_fingerprint: str,
) -> PreflightEvidence:
    evidence = _preflight_document_evidence(value)
    if (
        value.get("fingerprint") != expected_fingerprint
        or preflight_evidence_fingerprint(evidence) != expected_fingerprint
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH")
    validate_preflight_evidence(
        evidence,
        expected_fingerprint=expected_fingerprint,
        expected_run_id=evidence.run_id,
        expected_approval_id=evidence.approval_id,
        expected_execution_source_commit=evidence.execution_source_commit,
        expected_governance_record_commit=evidence.governance_record_commit,
        expected_manifest_sha256=evidence.manifest_sha256,
        expected_backend_fingerprint=evidence.backend_fingerprint,
    )
    if (
        value.get("status") != "preflight_passed"
        or value.get("approval_issued") is not False
        or value.get("approval_consumed") is not False
        or value.get("execution_allowed") is not False
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    draft = value.get("approval_draft")
    if not isinstance(draft, Mapping):
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")
    draft_fingerprint = validate_approval_draft(
        draft,
        evidence=evidence,
        evidence_fingerprint=expected_fingerprint,
        expected_run_id=evidence.run_id,
        expected_approval_id=evidence.approval_id,
    )
    if value.get("approval_draft_fingerprint") != draft_fingerprint:
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")
    return evidence


def _sync_preflight_parent_directory(path: Path) -> None:
    """Sync directory metadata where Python exposes a durable directory handle."""

    if os.name == "nt":
        return
    descriptor = -1
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_DIRECTORY_SYNC_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_preflight_no_replace(temporary: Path, final: Path) -> None:
    if os.name not in {"nt", "posix"}:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_NO_REPLACE_UNSUPPORTED")
    try:
        os.link(temporary, final)
    except FileExistsError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_ALREADY_EXISTS") from None
    except OSError as exc:
        if (
            exc.errno in _NO_REPLACE_UNSUPPORTED_ERRNOS
            or getattr(exc, "winerror", None) in {1, 50}
        ):
            raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_NO_REPLACE_UNSUPPORTED") from None
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_ATOMIC_WRITE_FAILED") from None


def write_preflight_evidence_file(
    path: str | Path,
    evidence_document: Mapping[str, object],
    *,
    expected_fingerprint: str,
) -> Path:
    """Durably publish one canonical Preflight result without replacement."""

    target = Path(path)
    evidence = _validate_preflight_document(
        evidence_document, expected_fingerprint=expected_fingerprint,
    )
    if (
        target.name != PREFLIGHT_EVIDENCE_FILENAME
        or target.parent.name != evidence.run_id
        or target.parent.parent.name != "runtime-evidence"
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_PATH_INVALID")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_PARENT_CREATE_FAILED") from None
    temporary = target.with_name(target.name + ".tmp")
    if target.exists():
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_ALREADY_EXISTS")
    payload = _canonical_preflight_document_bytes(evidence_document)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    descriptor = -1
    published = False
    temporary_created = False
    try:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            temporary_created = True
        except FileExistsError:
            raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_TEMPORARY_COLLISION") from None
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            if stream.write(payload) != len(payload):
                raise OSError("short write")
            stream.flush()
            os.fsync(stream.fileno())
        _publish_preflight_no_replace(temporary, target)
        published = True
        try:
            temporary.unlink()
        except OSError:
            raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_INCOMPLETE") from None
        _sync_preflight_parent_directory(target)
        try:
            stored = target.read_bytes()
            decoded = json.loads(stored.decode("utf-8"))
            if (
                stored != payload
                or hashlib.sha256(stored).hexdigest() != payload_sha256
                or not isinstance(decoded, dict)
            ):
                raise ValueError("persisted bytes differ")
            _validate_preflight_document(decoded, expected_fingerprint=expected_fingerprint)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, ProcessingPreflightError):
            raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_INCOMPLETE") from None
    except ProcessingPreflightError:
        raise
    except (OSError, ValueError):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_ATOMIC_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published and temporary_created and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_INCOMPLETE") from None
    return target


def deserialize_preflight_evidence(value: Mapping[str, object]) -> PreflightEvidence:
    if value.get("schema_version") == 1:
        raise ProcessingPreflightError("LEGACY_PREFLIGHT_EVIDENCE_NOT_EXECUTABLE")
    expected = set(PreflightEvidence.__dataclass_fields__)
    if set(value) != expected:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    try:
        return PreflightEvidence(**value)  # type: ignore[arg-type]
    except TypeError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED") from None


def validate_preflight_evidence(
    evidence: PreflightEvidence,
    *,
    expected_fingerprint: str,
    expected_run_id: str,
    expected_approval_id: str,
    expected_execution_source_commit: str,
    expected_governance_record_commit: str,
    expected_manifest_sha256: str,
    expected_backend_fingerprint: str,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=1),
    expected_source_zip_count: int = EXPECTED_ZIP_FILES,
    expected_source_total_bytes: int = EXPECTED_TOTAL_BYTES,
    expected_record_budget: Mapping[str, object] | None = None,
    synthetic: bool = False,
) -> None:
    validate_explicit_identity(expected_run_id, expected_approval_id, allow_synthetic=synthetic)
    if evidence.run_id != expected_run_id:
        raise ProcessingPreflightError("PREFLIGHT_RUN_ID_MISMATCH")
    if evidence.approval_id != expected_approval_id:
        raise ProcessingPreflightError("PREFLIGHT_APPROVAL_ID_MISMATCH")
    if not evidence.governance_record_commit:
        raise ProcessingPreflightError("PREFLIGHT_GOVERNANCE_COMMIT_REQUIRED")
    if evidence.execution_source_commit != expected_execution_source_commit:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
    if evidence.governance_record_commit != expected_governance_record_commit:
        raise ProcessingPreflightError("PREFLIGHT_GOVERNANCE_COMMIT_REQUIRED")
    if evidence.manifest_sha256 != expected_manifest_sha256:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
    if evidence.backend_fingerprint != expected_backend_fingerprint:
        raise ProcessingPreflightError("BACKEND_FINGERPRINT_MISMATCH")
    if preflight_evidence_fingerprint(evidence) != expected_fingerprint:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH")
    try:
        generated = datetime.fromisoformat(evidence.generated_at)
        expires = datetime.fromisoformat(evidence.expires_at)
    except ValueError:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED") from None
    if (
        generated.tzinfo is None or generated.utcoffset() is None
        or expires.tzinfo is None or expires.utcoffset() is None
        or expires <= generated
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    current = now or datetime.now(timezone.utc)
    if expires != generated + maximum_age or generated > current or current > expires:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_STALE")
    if evidence.schema_version != 2:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    expected_output = {
        "final_exists": False,
        "staging_exists": False,
        "failed_exists": False,
        "quarantine_exists": False,
        "parent_probe_passed": True,
        "parent_probe_residue_count": 0,
    }
    if dict(evidence.output_state) != expected_output:
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    expected_registry = {
        "run_id_unused": True,
        "approval_id_unused": True,
        "retired_run_count": 7,
        "conflicting_evidence_count": 0,
    }
    if dict(evidence.registry_state) != expected_registry:
        raise ProcessingPreflightError("PREFLIGHT_REGISTRY_STATE_MISMATCH")
    expected_lineage = {
        "result_code", "direct_ancestry", "squash_merge_mode",
        "execution_surface_file_count", "execution_surface_paths_equal",
        "execution_surface_blobs_equal", "manifest_fingerprint_equal",
        "backend_fingerprint_equal", "governance_reachable_from_origin_develop", "valid",
    }
    if set(evidence.lineage) != expected_lineage or any(
        not isinstance(evidence.lineage[name], bool)
        for name in expected_lineage - {"result_code", "execution_surface_file_count"}
    ) or evidence.lineage.get("valid") is not True:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    if dict(evidence.mapping_identity) != {
        "dataset_id": "AIHUB-71748", "component": "SFT", "root_type": "external",
        "repository_internal": False, "read_only": True,
    } or len(evidence.execution_source_commit) != 40 or len(evidence.governance_record_commit) != 40:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    expected_budgets = {
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        "record_budget": expected_record_budget or {"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        "output_budget": {"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
    }
    if any(dict(getattr(evidence, name)) != value for name, value in expected_budgets.items()):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    integer_fields = (
        (evidence.source_snapshot, ("zip_count", "total_bytes")),
        (evidence.registry_state, ("retired_run_count", "conflicting_evidence_count")),
        (evidence.output_state, ("parent_probe_residue_count",)),
        (evidence.resource_state, ("free_disk_bytes", "current_rss_bytes")),
        (evidence.runtime_budget, ("soft_limit_seconds", "hard_limit_seconds")),
        (evidence.memory_budget, ("soft_limit_mib", "hard_limit_mib")),
        (evidence.disk_budget, ("minimum_free_bytes", "staging_multiplier")),
        (evidence.record_budget, ("expected_training", "expected_validation", "expected_total", "maximum_total")),
        (evidence.output_budget, ("expected_files", "maximum_files", "maximum_total_bytes")),
    )
    if any(
        isinstance(mapping.get(name), bool)
        or not isinstance(mapping.get(name), int)
        or int(mapping[name]) < 0
        for mapping, names in integer_fields
        for name in names
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    if not isinstance(evidence.resource_state.get("free_disk_bytes"), int) or int(evidence.resource_state["free_disk_bytes"]) < 4_294_967_296:
        raise ProcessingPreflightError("DISK_BUDGET_INSUFFICIENT")
    if (
        evidence.source_snapshot.get("zip_count") != expected_source_zip_count
        or evidence.source_snapshot.get("total_bytes") != expected_source_total_bytes
    ):
        raise ProcessingPreflightError("SOURCE_PACKAGE_DRIFT")
    zero_fields = {
        "approval_issue_calls", "approval_consume_calls", "runtime_request_creations",
        "runtime_execution_gate_activations", "processing_engine_calls", "payload_sessions",
        "zip_entry_opens", "archive_member_enumerations", "json_parser_calls",
        "record_parser_calls", "join_calls", "policy_dispatch_calls", "output_writer_calls",
        "checksum_calls", "atomic_finalization_calls",
    }
    if set(evidence.zero_call_state) != zero_fields or any(
        isinstance(value, bool) or value != 0 for value in evidence.zero_call_state.values()
    ):
        raise ProcessingPreflightError("PREFLIGHT_ZERO_CALL_STATE_INVALID")
    encoded = serialize_preflight_evidence(evidence)
    if re.search(r"[A-Za-z]:\\\\|(?:^|[\"'])/(?!/)", encoded):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")


def build_approval_draft(
    evidence: PreflightEvidence,
    *,
    evidence_fingerprint: str,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "approval_id": evidence.approval_id,
        "processing_run_id": evidence.run_id,
        "dataset_id": "AIHUB-71748",
        "component": "SFT",
        "execution_source_commit": evidence.execution_source_commit,
        "governance_record_commit": evidence.governance_record_commit,
        "manifest_version": 1,
        "manifest_sha256": evidence.manifest_sha256,
        "backend_fingerprint": evidence.backend_fingerprint,
        "preflight_evidence_fingerprint": evidence_fingerprint,
        "approved_by": None,
        "approved_at": None,
        "issued_at": None,
        "consumed_at": None,
        "completed_at": None,
        "failed_at": None,
        "maximum_runs": 1,
        "maximum_processing_calls": 1,
        "maximum_payload_open_sessions": 1,
        "retry_allowed": False,
        "resume_allowed": False,
        "overwrite_allowed": False,
        "extension_allowed": False,
        "run_id_reuse_allowed": False,
        "approval_id_reuse_allowed": False,
        "runtime_budget": dict(evidence.runtime_budget),
        "memory_budget": dict(evidence.memory_budget),
        "disk_budget": dict(evidence.disk_budget),
        "record_budget": dict(evidence.record_budget),
        "output_budget": dict(evidence.output_budget),
        "processing_allowed": False,
        "payload_read_allowed": False,
        "output_write_allowed": False,
        "tokenization_allowed": False,
        "sft_backend_allowed": False,
        "training_allowed": False,
        "execution_allowed": False,
        "status": "prepared_not_issued",
        "consumed": False,
    }


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")


def validate_approval_draft(
    draft: Mapping[str, object],
    *,
    evidence: PreflightEvidence,
    evidence_fingerprint: str,
    expected_run_id: str,
    expected_approval_id: str,
    synthetic: bool = False,
) -> str:
    validate_explicit_identity(expected_run_id, expected_approval_id, allow_synthetic=synthetic)
    if draft.get("processing_run_id") != expected_run_id:
        raise ProcessingPreflightError("APPROVAL_DRAFT_RUN_ID_MISMATCH")
    if draft.get("approval_id") != expected_approval_id:
        raise ProcessingPreflightError("APPROVAL_DRAFT_APPROVAL_ID_MISMATCH")
    _exact_keys(draft, {
        "approval_id", "processing_run_id", "dataset_id", "component",
        "schema_version", "execution_source_commit", "governance_record_commit", "manifest_version", "manifest_sha256",
        "backend_fingerprint", "preflight_evidence_fingerprint", "approved_by", "approved_at",
        "issued_at", "consumed_at", "completed_at", "failed_at", "maximum_runs",
        "maximum_processing_calls", "maximum_payload_open_sessions", "retry_allowed",
        "resume_allowed", "overwrite_allowed", "extension_allowed", "run_id_reuse_allowed",
        "approval_id_reuse_allowed", "runtime_budget", "memory_budget", "disk_budget",
        "record_budget", "output_budget",
        "processing_allowed", "payload_read_allowed", "output_write_allowed",
        "tokenization_allowed", "sft_backend_allowed", "training_allowed",
        "execution_allowed", "status", "consumed",
    })
    expected = build_approval_draft(evidence, evidence_fingerprint=evidence_fingerprint)
    if dict(draft) != expected:
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")
    canonical = json.dumps(dict(draft), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_manifest_document(manifest: Mapping[str, object]) -> None:
    result = validate_aihub_71748_processing_manifest(manifest)
    if result.execution_allowed or result.processing_allowed or result.training_allowed or result.tokenization_allowed:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
