"""Issue one AIHUB-71748 SFT Approval without creating an execution request."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Mapping

import yaml

from src.data.aihub_71748_approval_refresh import (
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
    build_refresh_approval_draft,
    canonical_approval_refresh_evidence_path,
    deserialize_approval_refresh_evidence,
    fingerprints_for_refresh,
    validate_approval_refresh_evidence,
    validate_governance_refresh_checkout,
)
from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    ProcessingPreflightError,
    canonical_preflight_evidence_path,
    deserialize_preflight_evidence,
    preflight_evidence_fingerprint,
    validate_approval_draft,
    validate_preflight_evidence,
)
from src.data.processing.aihub_71748_mapping import (
    DatasetMappingError,
    ResolvedDatasetMapping,
    resolve_dataset_mapping,
)
from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_fingerprint,
    issue_approval,
    load_approval,
    new_approval,
    validate_approval,
)
from src.data.processing.run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RunContractError,
)


MINIMUM_REMAINING_VALIDITY = timedelta(minutes=10)
CANONICAL_MANIFEST = Path("configs/data/aihub-71748-sft-processing-v1.yaml")


class ApprovalIssueError(RuntimeError):
    """Fail-closed issuance error that never exposes a local absolute path."""


def _yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ApprovalIssueError("APPROVAL_ISSUE_MAPPING_INVALID") from None
    if not isinstance(value, dict):
        raise ApprovalIssueError("APPROVAL_ISSUE_MAPPING_INVALID")
    return value


def _json(path: Path, *, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ApprovalIssueError(code) from None
    if not isinstance(value, dict):
        raise ApprovalIssueError(code)
    return value


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise ApprovalIssueError("APPROVAL_ISSUE_GIT_LINEAGE_MISMATCH")
    return result.stdout.strip()


def _validate_git_state(
    repository: Path, *, execution_source_commit: str, governance_record_commit: str,
) -> None:
    branch = _git(repository, "branch", "--show-current")
    head = _git(repository, "rev-parse", "HEAD")
    origin = _git(repository, "rev-parse", "origin/develop")
    if (
        branch != "develop"
        or _git(repository, "status", "--porcelain")
        or head != origin
        or head != execution_source_commit
        or head != governance_record_commit
        or _git(repository, "rev-list", "--left-right", "--count", "develop...origin/develop")
        != "0\t0"
    ):
        raise ApprovalIssueError("APPROVAL_ISSUE_GIT_LINEAGE_MISMATCH")
    validate_governance_refresh_checkout(
        repository,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
    )


def _remaining(expires_at: str, now: datetime) -> timedelta:
    try:
        expires = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        raise ApprovalIssueError("APPROVAL_EVIDENCE_INSUFFICIENT_VALIDITY_WINDOW") from None
    if expires.tzinfo is None or expires.utcoffset() is None:
        raise ApprovalIssueError("APPROVAL_EVIDENCE_INSUFFICIENT_VALIDITY_WINDOW")
    return expires - now


def _load_initial(
    path: Path,
    *,
    expected_fingerprint: str,
    run_id: str,
    approval_id: str,
    execution_source_commit: str,
    governance_record_commit: str,
    manifest_sha256: str,
    backend_fingerprint: str,
    now: datetime,
) -> tuple[PreflightEvidence, Mapping[str, object]]:
    document = _json(path, code="PREFLIGHT_EVIDENCE_REQUIRED")
    fields = set(PreflightEvidence.__dataclass_fields__)
    expected = fields | {
        "fingerprint", "approval_draft", "approval_draft_fingerprint",
        "status", "approval_issued", "approval_consumed", "execution_allowed",
    }
    if set(document) != expected:
        raise ApprovalIssueError("PREFLIGHT_EVIDENCE_REQUIRED")
    evidence = deserialize_preflight_evidence({name: document[name] for name in fields})
    validate_preflight_evidence(
        evidence,
        expected_fingerprint=expected_fingerprint,
        expected_run_id=run_id,
        expected_approval_id=approval_id,
        expected_execution_source_commit=execution_source_commit,
        expected_governance_record_commit=governance_record_commit,
        expected_manifest_sha256=manifest_sha256,
        expected_backend_fingerprint=backend_fingerprint,
        now=now,
        synthetic=run_id.startswith("SYNTHETIC-"),
    )
    if (
        document.get("fingerprint") != expected_fingerprint
        or preflight_evidence_fingerprint(evidence) != expected_fingerprint
        or document.get("status") != "preflight_passed"
        or document.get("approval_issued") is not False
        or document.get("approval_consumed") is not False
        or document.get("execution_allowed") is not False
        or not isinstance(document.get("approval_draft"), Mapping)
    ):
        raise ApprovalIssueError("PREFLIGHT_EVIDENCE_REQUIRED")
    draft_fingerprint = validate_approval_draft(
        document["approval_draft"],  # type: ignore[arg-type]
        evidence=evidence,
        evidence_fingerprint=expected_fingerprint,
        expected_run_id=run_id,
        expected_approval_id=approval_id,
        synthetic=run_id.startswith("SYNTHETIC-"),
    )
    if document.get("approval_draft_fingerprint") != draft_fingerprint:
        raise ApprovalIssueError("APPROVAL_DRAFT_INVALID")
    return evidence, document


def _load_refresh(
    path: Path,
    *,
    expected_fingerprint: str,
    expected_initial_fingerprint: str,
    run_id: str,
    approval_id: str,
    execution_source_commit: str,
    governance_record_commit: str,
    manifest_sha256: str,
    backend_fingerprint: str,
    now: datetime,
) -> tuple[ApprovalRefreshEvidence, Mapping[str, object]]:
    document = _json(path, code="APPROVAL_REFRESH_EVIDENCE_INVALID")
    fields = set(ApprovalRefreshEvidence.__dataclass_fields__)
    expected = fields | {
        "fingerprint", "approval_draft", "status", "approval_issued",
        "approval_consumed", "runtime_request_created", "payload_reads",
        "processing_calls", "output_writes", "execution_allowed",
    }
    if set(document) != expected:
        raise ApprovalIssueError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    evidence = deserialize_approval_refresh_evidence(
        {name: document[name] for name in fields}
    )
    validate_approval_refresh_evidence(
        evidence,
        expected_fingerprint=expected_fingerprint,
        expected_run_id=run_id,
        expected_approval_id=approval_id,
        expected_execution_source_commit=execution_source_commit,
        expected_governance_record_commit=governance_record_commit,
        expected_manifest_sha256=manifest_sha256,
        expected_backend_fingerprint=backend_fingerprint,
        expected_previous_preflight_fingerprint=expected_initial_fingerprint,
        now=now,
    )
    expected_draft = build_refresh_approval_draft(
        evidence, evidence_fingerprint=expected_fingerprint,
    )
    if (
        document.get("fingerprint") != expected_fingerprint
        or approval_refresh_evidence_fingerprint(evidence) != expected_fingerprint
        or document.get("approval_draft") != expected_draft
        or document.get("status") != "approval_refresh_validated"
        or document.get("approval_issued") is not False
        or document.get("approval_consumed") is not False
        or document.get("runtime_request_created") is not False
        or document.get("execution_allowed") is not False
    ):
        raise ApprovalIssueError("APPROVAL_REFRESH_EVIDENCE_INVALID")
    return evidence, document


def _validate_runtime_absence(
    mapping: ResolvedDatasetMapping, *, run_id: str, approval_id: str,
) -> Path:
    target = mapping.processed_root / "approvals" / f"{approval_id}.json"
    collisions = (
        target,
        target.with_name(target.name + ".tmp"),
        mapping.processed_root / "runtime-evidence" / approval_id,
        mapping.processed_root / run_id,
        mapping.processed_root / f"{run_id}.staging",
        mapping.processed_root / f"{run_id}.failed",
        mapping.processed_root / "quarantine" / run_id,
    )
    if any(path.exists() for path in collisions):
        raise ApprovalIssueError("APPROVAL_ISSUE_ARTIFACT_COLLISION")
    return target


def issue_from_evidence(
    *,
    repository: Path,
    mapping: ResolvedDatasetMapping,
    run_id: str,
    approval_id: str,
    execution_source_commit: str,
    governance_record_commit: str,
    initial_fingerprint: str,
    refresh_fingerprint: str,
    approved_by: str,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None or not approved_by.strip():
        raise ApprovalIssueError("APPROVAL_ISSUE_INPUT_INVALID")
    _validate_git_state(
        repository,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
    )
    manifest_sha256, backend_fingerprint = fingerprints_for_refresh(
        repository, execution_source_commit, governance_record_commit,
    )
    initial_path = canonical_preflight_evidence_path(mapping.processed_root, run_id)
    refresh_path = canonical_approval_refresh_evidence_path(mapping.processed_root, run_id)
    initial, initial_document = _load_initial(
        initial_path,
        expected_fingerprint=initial_fingerprint,
        run_id=run_id,
        approval_id=approval_id,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=manifest_sha256,
        backend_fingerprint=backend_fingerprint,
        now=current,
    )
    refresh, refresh_document = _load_refresh(
        refresh_path,
        expected_fingerprint=refresh_fingerprint,
        expected_initial_fingerprint=initial_fingerprint,
        run_id=run_id,
        approval_id=approval_id,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=manifest_sha256,
        backend_fingerprint=backend_fingerprint,
        now=current,
    )
    if (
        initial.source_snapshot != refresh.source_snapshot
        or _remaining(initial.expires_at, current) < MINIMUM_REMAINING_VALIDITY
        or _remaining(refresh.expires_at, current) < MINIMUM_REMAINING_VALIDITY
    ):
        raise ApprovalIssueError("APPROVAL_EVIDENCE_INSUFFICIENT_VALIDITY_WINDOW")
    if refresh_document.get("approval_draft") != build_refresh_approval_draft(
        refresh, evidence_fingerprint=refresh_fingerprint,
    ) or initial_document.get("fingerprint") != initial_fingerprint:
        raise ApprovalIssueError("APPROVAL_DRAFT_INVALID")
    target = _validate_runtime_absence(mapping, run_id=run_id, approval_id=approval_id)
    contract = ProcessingRunContract(
        run_id=run_id,
        approval_id=approval_id,
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=False,
        synthetic=run_id.startswith("SYNTHETIC-"),
    )
    timestamp = current.isoformat()
    prepared = new_approval(
        contract,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=manifest_sha256,
        backend_fingerprint=backend_fingerprint,
        preflight_evidence_fingerprint=refresh_fingerprint,
        approved_by=approved_by,
        approved_at=timestamp,
    )
    counters = ExecutionCounters()
    issued = issue_approval(
        target, prepared, issued_at=timestamp, contract=contract, counters=counters,
    )
    reloaded = load_approval(target)
    validate_approval(reloaded, contract)
    if reloaded != issued or reloaded.status != "issued" or reloaded.consumed or reloaded.execution_allowed:
        raise ApprovalIssueError("APPROVAL_ISSUE_RELOAD_VALIDATION_FAILED")
    file_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "status": "issued",
        "run_id": run_id,
        "approval_id": approval_id,
        "artifact": f"configured_processed_root/approvals/{approval_id}.json",
        "file_sha256": file_sha256,
        "stable_fingerprint": approval_fingerprint(reloaded),
        "issued_at": reloaded.issued_at,
        "initial_evidence_fingerprint": initial_fingerprint,
        "refresh_evidence_fingerprint": refresh_fingerprint,
        "execution_source_commit": execution_source_commit,
        "governance_record_commit": governance_record_commit,
        "manifest_sha256": manifest_sha256,
        "backend_fingerprint": backend_fingerprint,
        "issued": True,
        "consumed": False,
        "execution_allowed": False,
        "counters": counters.snapshot(),
        "runtime_request_created": False,
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--manifest", type=Path, default=CANONICAL_MANIFEST)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--execution-source-commit", required=True)
    parser.add_argument("--governance-record-commit", required=True)
    parser.add_argument("--initial-evidence-fingerprint", required=True)
    parser.add_argument("--refresh-evidence-fingerprint", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-issue-only", action="store_true", required=True)
    return parser


def issue_command(arguments: argparse.Namespace) -> dict[str, object]:
    repository = Path.cwd().resolve()
    if arguments.manifest.resolve() != (repository / CANONICAL_MANIFEST).resolve():
        raise ApprovalIssueError("APPROVAL_ISSUE_MANIFEST_PATH_INVALID")
    mapping = resolve_dataset_mapping(
        repository_root=repository,
        local_config=_yaml(arguments.mapping),
    )
    return issue_from_evidence(
        repository=repository,
        mapping=mapping,
        run_id=arguments.run_id,
        approval_id=arguments.approval_id,
        execution_source_commit=arguments.execution_source_commit,
        governance_record_commit=arguments.governance_record_commit,
        initial_fingerprint=arguments.initial_evidence_fingerprint,
        refresh_fingerprint=arguments.refresh_evidence_fingerprint,
        approved_by=arguments.approved_by,
    )


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = issue_command(arguments)
    except (
        ApprovalIssueError,
        DatasetMappingError,
        ProcessingApprovalError,
        ProcessingPreflightError,
        RunContractError,
        RuntimeError,
    ) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc), "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
