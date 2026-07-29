"""Metadata-only Run 0002 preflight and non-executable approval draft validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Mapping

from src.data.processing.aihub_71748_manifest import (
    validate_aihub_71748_processing_manifest,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping


RUN_ID = "AIHUB-71748-SFT-PROCESSING-20260729-0002"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002"
IMMUTABLE_COMMIT = "af10abf3ef388f4efd8707489cebef2c22719751"
MANIFEST_PATH = "configs/data/aihub-71748-sft-processing-v1.yaml"
BACKEND_PATHS = ("src/data/processing", "scripts/datasets/process_aihub_71748_sft.py")
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
    components: tuple[str, ...]
    splits: tuple[str, ...]
    payload_reads: int = 0


@dataclass(frozen=True)
class GitFingerprints:
    immutable_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    backend_file_count: int


def _git(repository_root: Path, *arguments: str, text: bool = False) -> bytes | str:
    try:
        return subprocess.check_output(
            ["git", *arguments], cwd=repository_root, text=text,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH") from None


def compute_git_fingerprints(repository_root: str | Path) -> GitFingerprints:
    """Hash immutable Git blobs, never the mutable worktree or local Dataset."""

    root = Path(repository_root).resolve()
    commit = str(_git(root, "rev-parse", IMMUTABLE_COMMIT, text=True)).strip()
    if commit != IMMUTABLE_COMMIT:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
    manifest = bytes(_git(root, "show", f"{commit}:{MANIFEST_PATH}"))
    paths = str(
        _git(root, "ls-tree", "-r", "--name-only", commit, "--", *BACKEND_PATHS, text=True)
    ).splitlines()
    required = {MANIFEST_PATH, "scripts/datasets/process_aihub_71748_sft.py"}
    tree = set(str(_git(root, "ls-tree", "-r", "--name-only", commit, text=True)).splitlines())
    if not required <= tree or not paths:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
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


def validate_backend_worktree(repository_root: str | Path) -> None:
    root = Path(repository_root).resolve()
    result = subprocess.run(
        ["git", "diff", "--quiet", IMMUTABLE_COMMIT, "--", MANIFEST_PATH, *BACKEND_PATHS],
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
    modified = [path.stat().st_mtime for path in archives]
    render = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    return SourceMetadata(
        zip_files=len(archives),
        total_bytes=total_bytes,
        modified_min_utc=render(min(modified)),
        modified_max_utc=render(max(modified)),
        components=tuple(components),
        splits=splits,
    )


def validate_run_unused(
    mapping: ResolvedDatasetMapping,
    *,
    repository_root: str | Path,
) -> None:
    roots = (
        mapping.processed_root / RUN_ID,
        mapping.processed_root / f"{RUN_ID}.staging",
        mapping.processed_root / f"{RUN_ID}.failed",
        mapping.processed_root / "approvals" / f"{APPROVAL_ID}.json",
        mapping.processed_root / "runtime-evidence" / RUN_ID,
    )
    if any(path.exists() for path in roots):
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    root = Path(repository_root).resolve()
    for identifier, error in (
        (RUN_ID, "RUN_ID_ALREADY_USED"),
        (APPROVAL_ID, "APPROVAL_ID_ALREADY_USED"),
    ):
        result = subprocess.run(
            ["git", "grep", "-n", identifier, IMMUTABLE_COMMIT, "--", ":!tests"],
            cwd=root, capture_output=True, text=True,
        )
        if result.returncode == 0:
            raise ProcessingPreflightError(error)
        if result.returncode not in {0, 1}:
            raise ProcessingPreflightError(error)


def validate_output_contract(
    mapping: ResolvedDatasetMapping,
    *,
    minimum_free_bytes: int,
) -> dict[str, object]:
    run_root = mapping.processed_root / RUN_ID
    collisions = (run_root, run_root.with_name(run_root.name + ".staging"), run_root.with_name(run_root.name + ".failed"))
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


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")


def validate_approval_draft(
    draft: Mapping[str, object],
    *,
    fingerprints: GitFingerprints,
) -> str:
    _exact_keys(draft, {
        "approval_id", "processing_run_id", "dataset_id", "component",
        "immutable_git_commit", "manifest_version", "manifest_sha256",
        "backend_fingerprint", "backend_file_count", "approved_by", "approved_at",
        "maximum_runs", "retry_allowed", "resume_allowed", "overwrite_allowed",
        "extension_allowed", "runtime_budget", "memory_budget", "disk_budget",
        "record_budget", "output_budget", "processing_thresholds", "near_duplicate",
        "processing_allowed", "payload_read_allowed", "output_write_allowed",
        "tokenization_allowed", "training_allowed", "execution_allowed", "status",
    })
    fixed = {
        "approval_id": APPROVAL_ID,
        "processing_run_id": RUN_ID,
        "dataset_id": "AIHUB-71748",
        "component": "SFT",
        "immutable_git_commit": fingerprints.immutable_commit,
        "manifest_version": 1,
        "manifest_sha256": fingerprints.manifest_sha256,
        "backend_fingerprint": fingerprints.backend_fingerprint,
        "backend_file_count": fingerprints.backend_file_count,
        "approved_by": "user",
        "approved_at": None,
        "maximum_runs": 1,
        "retry_allowed": False,
        "resume_allowed": False,
        "overwrite_allowed": False,
        "extension_allowed": False,
        "processing_allowed": False,
        "payload_read_allowed": False,
        "output_write_allowed": False,
        "tokenization_allowed": False,
        "training_allowed": False,
        "execution_allowed": False,
        "status": "prepared_not_issued",
    }
    if any(draft.get(key) != value for key, value in fixed.items()):
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")
    expected_nested = {
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        "record_budget": {"expected_total": 11902, "maximum_total": 11902, "unexpected_extra_records": "blocked"},
        "output_budget": {"expected_files": 6, "maximum_files": 6, "maximum_bytes": 536_870_912, "allowed_files": list(ALLOWED_OUTPUTS)},
        "processing_thresholds": {"minimum_training_records": 10000, "minimum_validation_records": 1000, "maximum_total_exclusion_rate": 0.10},
        "near_duplicate": {"review_min": 0.90, "high_similarity_min": 0.97},
    }
    if any(draft.get(key) != value for key, value in expected_nested.items()):
        raise ProcessingPreflightError("APPROVAL_DRAFT_INVALID")
    canonical = json.dumps(dict(draft), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_manifest_document(manifest: Mapping[str, object]) -> None:
    result = validate_aihub_71748_processing_manifest(manifest)
    if result.execution_allowed or result.processing_allowed or result.training_allowed or result.tokenization_allowed:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
