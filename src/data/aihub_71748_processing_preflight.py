"""Dynamic immutable identity and canonical metadata-only preflight evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


RUN_ID = "AIHUB-71748-SFT-PROCESSING-20260729-0003"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0003"
MANIFEST_PATH = "configs/data/aihub-71748-sft-processing-v1.yaml"
BACKEND_PATHS = (
    "src/data/processing/aihub_71748_reader.py",
    "src/data/processing/aihub_71748_processor.py",
    "src/data/processing/output_writer.py",
    "src/data/processing/run_contract.py",
    "src/data/processing/approval.py",
    "src/data/processing/runtime_monitor.py",
    "src/data/processing/post_validation.py",
    "scripts/datasets/process_aihub_71748_sft.py",
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
class PreflightEvidence:
    run_id: str
    approval_id: str
    immutable_git_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    mapping_identity: str
    source_zip_count: int
    source_total_bytes: int
    output_root_state: str
    staging_root_state: str
    quarantine_state: str
    free_disk_bytes: int
    runtime_budget: Mapping[str, object]
    memory_budget: Mapping[str, object]
    disk_budget: Mapping[str, object]
    record_budget: Mapping[str, object]
    output_budget: Mapping[str, object]
    generated_at: str


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
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", "develop", commit], cwd=root)
    if ancestry.returncode != 0:
        raise ProcessingPreflightError("SOURCE_COMMIT_NOT_REACHABLE")
    return commit


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
    modified = [path.stat().st_mtime for path in archives]
    def render(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
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
    run_id: str = RUN_ID,
    approval_id: str = APPROVAL_ID,
    immutable_commit: str | None = None,
) -> None:
    roots = (
        mapping.processed_root / run_id,
        mapping.processed_root / f"{run_id}.staging",
        mapping.processed_root / f"{run_id}.failed",
        mapping.processed_root / "approvals" / f"{approval_id}.json",
        mapping.processed_root / "runtime-evidence" / run_id,
    )
    if any(path.exists() for path in roots):
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    root = Path(repository_root).resolve()
    for identifier, error in (
        (run_id, "RUN_ID_ALREADY_USED"),
        (approval_id, "APPROVAL_ID_ALREADY_USED"),
    ):
        result = subprocess.run(
            ["git", "grep", "-n", identifier, immutable_commit or "HEAD", "--", ":!tests"],
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
    run_id: str = RUN_ID,
) -> dict[str, object]:
    run_root = mapping.processed_root / run_id
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


def validate_preflight_evidence(
    evidence: PreflightEvidence,
    *,
    expected_fingerprint: str,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=1),
) -> None:
    if preflight_evidence_fingerprint(evidence) != expected_fingerprint:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH")
    generated = datetime.fromisoformat(evidence.generated_at)
    current = now or datetime.now(timezone.utc)
    if generated > current or current - generated > maximum_age:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_STALE")
    if any(state != "absent" for state in (
        evidence.output_root_state, evidence.staging_root_state, evidence.quarantine_state,
    )):
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    if evidence.run_id != RUN_ID or evidence.approval_id != APPROVAL_ID:
        raise ProcessingPreflightError("RUN_ID_ALREADY_USED")
    if not evidence.mapping_identity or len(evidence.immutable_git_commit) != 40:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    expected_budgets = {
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        "record_budget": {"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        "output_budget": {"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
    }
    if any(dict(getattr(evidence, name)) != value for name, value in expected_budgets.items()):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_REQUIRED")
    if evidence.free_disk_bytes < 4_294_967_296:
        raise ProcessingPreflightError("DISK_BUDGET_INSUFFICIENT")
    if evidence.source_zip_count != EXPECTED_ZIP_FILES or evidence.source_total_bytes != EXPECTED_TOTAL_BYTES:
        raise ProcessingPreflightError("SOURCE_PACKAGE_DRIFT")


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
