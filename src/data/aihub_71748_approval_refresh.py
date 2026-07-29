"""Fail-closed live validation for an already reserved AIHUB-71748 run.

This module is governance-only.  It neither opens Dataset payloads nor issues
or consumes an Approval.  Initial preflight remains in
``aihub_71748_processing_preflight`` and keeps its unused-identity contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Mapping, Protocol

from .aihub_71748_processing_preflight import (
    LineageValidation,
    PreflightEvidence,
    ProcessingPreflightError,
    build_approval_draft,
    compute_git_fingerprints,
    deserialize_preflight_evidence,
    preflight_evidence_fingerprint,
    validate_approval_draft,
    validate_explicit_identity,
    validate_immutable_lineage,
)
from .processing.aihub_71748_mapping import ResolvedDatasetMapping


VALIDATION_PHASE = "approval_refresh"
ACTIVE_RUN_STATUS = "preflight_passed"


@dataclass(frozen=True)
class ActiveRunRegistryState:
    run_id: str
    approval_id: str
    run_status: str
    previous_preflight_evidence_fingerprint: str
    approval_id_unused: bool
    approval_artifact_exists: bool
    approval_issue_calls: int
    approval_consume_calls: int
    runtime_request_exists: bool
    processing_started: bool
    payload_reads: int
    processing_calls: int
    output_writes: int
    conflicting_evidence_count: int


class ActiveRunRegistry(Protocol):
    """Minimal canonical registry boundary used by live refresh validation."""

    def read_active_run(self, run_id: str, approval_id: str) -> ActiveRunRegistryState:
        ...


@dataclass(frozen=True)
class ApprovalRefreshEvidence:
    schema_version: int
    validation_phase: str
    run_id: str
    approval_id: str
    previous_preflight_evidence_fingerprint: str
    execution_source_commit: str
    governance_record_commit: str
    manifest_sha256: str
    backend_fingerprint: str
    lineage: Mapping[str, object]
    mapping_identity: Mapping[str, object]
    source_snapshot: Mapping[str, object]
    registry_state: Mapping[str, object]
    runtime_state: Mapping[str, object]
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


def approval_refresh_evidence_fingerprint(evidence: ApprovalRefreshEvidence) -> str:
    return hashlib.sha256(serialize_approval_refresh_evidence(evidence).encode("utf-8")).hexdigest()


def serialize_approval_refresh_evidence(evidence: ApprovalRefreshEvidence) -> str:
    return json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deserialize_approval_refresh_evidence(value: Mapping[str, object]) -> ApprovalRefreshEvidence:
    if set(value) != set(ApprovalRefreshEvidence.__dataclass_fields__):
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_UNKNOWN_FIELD")
    if value.get("schema_version") != 1:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_SCHEMA_INVALID")
    try:
        return ApprovalRefreshEvidence(**value)  # type: ignore[arg-type]
    except TypeError:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID") from None


def validate_governance_refresh_checkout(
    repository_root: str | Path,
    *,
    execution_source_commit: str,
    governance_record_commit: str,
) -> LineageValidation:
    """Validate the current governance checkout separately from execution source."""

    root = Path(repository_root).resolve()
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        raise ProcessingPreflightError("GOVERNANCE_COMMIT_NOT_FOUND") from None
    if head != governance_record_commit:
        raise ProcessingPreflightError("GOVERNANCE_CHECKOUT_MISMATCH")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    if status.returncode != 0 or status.stdout.strip():
        raise ProcessingPreflightError("WORKTREE_NOT_CLEAN")
    return validate_immutable_lineage(
        root,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
    )


def validate_previous_preflight_evidence(
    value: Mapping[str, object],
    *,
    expected_fingerprint: str,
    run_id: str,
    approval_id: str,
    execution_source_commit: str,
) -> PreflightEvidence:
    """Verify immutable identity and checksum without treating old freshness as live."""

    fields = set(PreflightEvidence.__dataclass_fields__)
    evidence = deserialize_preflight_evidence({key: value[key] for key in fields if key in value})
    if value.get("status") != ACTIVE_RUN_STATUS:
        raise ProcessingPreflightError("ACTIVE_RUN_STATUS_INVALID")
    if evidence.run_id != run_id or evidence.approval_id != approval_id:
        raise ProcessingPreflightError("ACTIVE_RUN_REGISTRY_MISMATCH")
    if evidence.execution_source_commit != execution_source_commit:
        raise ProcessingPreflightError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
    actual = preflight_evidence_fingerprint(evidence)
    if actual != expected_fingerprint or value.get("fingerprint") != expected_fingerprint:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH")
    try:
        generated = datetime.fromisoformat(evidence.generated_at)
        expires = datetime.fromisoformat(evidence.expires_at)
    except (TypeError, ValueError):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_STALE") from None
    if (
        generated.tzinfo is None or generated.utcoffset() is None
        or expires.tzinfo is None or expires.utcoffset() is None
        or expires != generated + timedelta(hours=1)
    ):
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_STALE")
    # The historical evidence may naturally be expired; the purpose of this
    # phase is to create a fresh live evidence record without rewriting it.
    return evidence


def validate_active_run_for_approval_refresh(
    mapping: ResolvedDatasetMapping,
    *,
    run_id: str,
    approval_id: str,
    expected_preflight_fingerprint: str,
    expected_run_status: str,
    registry: ActiveRunRegistry,
) -> ActiveRunRegistryState:
    validate_explicit_identity(run_id, approval_id, allow_synthetic=run_id.startswith("SYNTHETIC-"))
    try:
        state = registry.read_active_run(run_id, approval_id)
    except (KeyError, LookupError):
        raise ProcessingPreflightError("ACTIVE_RUN_REGISTRY_NOT_FOUND") from None
    if state.run_id != run_id or state.approval_id != approval_id:
        raise ProcessingPreflightError("ACTIVE_RUN_REGISTRY_MISMATCH")
    if expected_run_status != ACTIVE_RUN_STATUS or state.run_status != ACTIVE_RUN_STATUS:
        raise ProcessingPreflightError("ACTIVE_RUN_STATUS_INVALID")
    if state.previous_preflight_evidence_fingerprint != expected_preflight_fingerprint:
        raise ProcessingPreflightError("PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH")
    if not state.approval_id_unused or state.approval_artifact_exists:
        raise ProcessingPreflightError("APPROVAL_ID_ALREADY_USED")
    if state.approval_issue_calls:
        raise ProcessingPreflightError("APPROVAL_ALREADY_ISSUED")
    if state.approval_consume_calls:
        raise ProcessingPreflightError("APPROVAL_ALREADY_CONSUMED")
    if state.runtime_request_exists:
        raise ProcessingPreflightError("RUNTIME_REQUEST_ALREADY_EXISTS")
    if state.processing_started or state.processing_calls or state.payload_reads or state.output_writes:
        raise ProcessingPreflightError("PROCESSING_ALREADY_STARTED")
    if state.conflicting_evidence_count:
        raise ProcessingPreflightError("PREFLIGHT_REGISTRY_STATE_MISMATCH")
    collisions = (
        mapping.processed_root / run_id,
        mapping.processed_root / f"{run_id}.staging",
        mapping.processed_root / f"{run_id}.failed",
        mapping.processed_root / "quarantine" / run_id,
    )
    if any(path.exists() for path in collisions):
        raise ProcessingPreflightError("RUN_OUTPUT_ALREADY_EXISTS")
    return state


def validate_approval_refresh_evidence(
    evidence: ApprovalRefreshEvidence,
    *,
    expected_fingerprint: str,
    expected_run_id: str,
    expected_approval_id: str,
    expected_execution_source_commit: str,
    expected_governance_record_commit: str,
    expected_manifest_sha256: str,
    expected_backend_fingerprint: str,
    expected_previous_preflight_fingerprint: str,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(hours=1),
) -> None:
    validate_explicit_identity(
        expected_run_id, expected_approval_id, allow_synthetic=expected_run_id.startswith("SYNTHETIC-"),
    )
    if evidence.schema_version != 1 or evidence.validation_phase != VALIDATION_PHASE:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_SCHEMA_INVALID")
    expected_identity = (
        expected_run_id, expected_approval_id, expected_execution_source_commit,
        expected_governance_record_commit, expected_manifest_sha256,
        expected_backend_fingerprint, expected_previous_preflight_fingerprint,
    )
    actual_identity = (
        evidence.run_id, evidence.approval_id, evidence.execution_source_commit,
        evidence.governance_record_commit, evidence.manifest_sha256,
        evidence.backend_fingerprint, evidence.previous_preflight_evidence_fingerprint,
    )
    if actual_identity != expected_identity:
        raise ProcessingPreflightError("APPROVAL_REFRESH_IDENTITY_MISMATCH")
    if approval_refresh_evidence_fingerprint(evidence) != expected_fingerprint:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_FINGERPRINT_MISMATCH")
    try:
        generated = datetime.fromisoformat(evidence.generated_at)
        expires = datetime.fromisoformat(evidence.expires_at)
    except (TypeError, ValueError):
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID") from None
    current = now or datetime.now(timezone.utc)
    if any(value.tzinfo is None or value.utcoffset() is None for value in (generated, expires)):
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    if expires != generated + maximum_age or generated > current or current > expires:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_STALE")
    if dict(evidence.registry_state) != {
        "run_status": ACTIVE_RUN_STATUS, "run_id_unused": False,
        "approval_id_unused": True, "conflicting_evidence_count": 0,
    }:
        raise ProcessingPreflightError("PREFLIGHT_REGISTRY_STATE_MISMATCH")
    if dict(evidence.runtime_state) != {
        "approval_artifact_exists": False, "approval_issue_calls": 0,
        "approval_consume_calls": 0, "runtime_request_exists": False,
        "processing_started": False, "payload_reads": 0,
        "processing_calls": 0, "output_writes": 0,
    }:
        raise ProcessingPreflightError("APPROVAL_REFRESH_RUNTIME_STATE_INVALID")
    if dict(evidence.output_state) != {
        "final_exists": False, "staging_exists": False, "failed_exists": False,
        "quarantine_exists": False, "parent_probe_passed": True,
        "parent_probe_residue_count": 0,
    }:
        raise ProcessingPreflightError("RUN_OUTPUT_ALREADY_EXISTS")
    lineage_fields = {
        "result_code", "direct_ancestry", "squash_merge_mode",
        "execution_surface_file_count", "execution_surface_paths_equal",
        "execution_surface_blobs_equal", "manifest_fingerprint_equal",
        "backend_fingerprint_equal", "governance_reachable_from_origin_develop", "valid",
    }
    if set(evidence.lineage) != lineage_fields or not evidence.lineage.get("valid") or not evidence.lineage.get("execution_surface_blobs_equal"):
        raise ProcessingPreflightError("EXECUTION_SOURCE_TREE_DRIFT")
    if dict(evidence.mapping_identity) != {
        "dataset_id": "AIHUB-71748", "component": "SFT", "root_type": "external",
        "repository_internal": False, "read_only": True,
    }:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    if set(evidence.source_snapshot) != {
        "zip_count", "total_bytes", "filename_aggregate", "modified_time_aggregate",
    }:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    if set(evidence.resource_state) != {
        "free_disk_bytes", "memory_provider_available", "runtime_provider_available", "current_rss_bytes",
    }:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    expected_budgets = {
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        "record_budget": {"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        "output_budget": {"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
    }
    if any(dict(getattr(evidence, key)) != value for key, value in expected_budgets.items()):
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    zero_fields = {
        "approval_issue_calls", "approval_consume_calls", "runtime_request_creations",
        "runtime_execution_gate_activations", "processing_engine_calls", "payload_sessions",
        "zip_entry_opens", "archive_member_enumerations", "json_parser_calls",
        "record_parser_calls", "join_calls", "policy_dispatch_calls", "output_writer_calls",
        "checksum_calls", "atomic_finalization_calls",
    }
    if set(evidence.zero_call_state) != zero_fields or any(
        value != 0 or isinstance(value, bool) for value in evidence.zero_call_state.values()
    ):
        raise ProcessingPreflightError("PREFLIGHT_ZERO_CALL_STATE_INVALID")


def build_refresh_approval_draft(
    evidence: ApprovalRefreshEvidence, *, evidence_fingerprint: str,
) -> dict[str, object]:
    draft = build_approval_draft(evidence, evidence_fingerprint=evidence_fingerprint)  # type: ignore[arg-type]
    validate_approval_draft(
        draft, evidence=evidence, evidence_fingerprint=evidence_fingerprint,  # type: ignore[arg-type]
        expected_run_id=evidence.run_id, expected_approval_id=evidence.approval_id,
        synthetic=evidence.run_id.startswith("SYNTHETIC-"),
    )
    return draft


def fingerprints_for_refresh(
    repository_root: str | Path, execution_source_commit: str, governance_record_commit: str,
) -> tuple[str, str]:
    execution = compute_git_fingerprints(repository_root, execution_source_commit)
    governance = compute_git_fingerprints(repository_root, governance_record_commit)
    if execution.manifest_sha256 != governance.manifest_sha256:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
    if execution.backend_fingerprint != governance.backend_fingerprint:
        raise ProcessingPreflightError("BACKEND_FINGERPRINT_MISMATCH")
    return execution.manifest_sha256, execution.backend_fingerprint
