"""Metadata-only preflight evidence generator requiring an explicit immutable commit."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import yaml

from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    ProcessingPreflightError,
    build_approval_draft,
    compute_git_fingerprints,
    discover_source_metadata,
    preflight_evidence_fingerprint,
    probe_output_parent,
    validate_backend_worktree,
    validate_immutable_commit,
    validate_immutable_lineage,
    validate_manifest_document,
    validate_output_contract,
    validate_approval_draft,
    validate_preflight_evidence,
    validate_resource_providers,
    validate_run_unused,
    validate_explicit_identity,
)
from src.data.processing.aihub_71748_mapping import resolve_dataset_mapping


def _yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ProcessingPreflightError("PREFLIGHT_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise ProcessingPreflightError("PREFLIGHT_CONFIG_INVALID")
    return value


def run_preflight(
    *,
    repository_root: Path,
    local_mapping_path: Path,
    manifest_path: Path,
    immutable_commit: str,
    governance_record_commit: str,
    run_id: str,
    approval_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    validate_explicit_identity(run_id, approval_id)
    commit = validate_immutable_commit(repository_root, immutable_commit)
    lineage = validate_immutable_lineage(
        repository_root,
        execution_source_commit=commit,
        governance_record_commit=governance_record_commit,
    )
    fingerprints = compute_git_fingerprints(repository_root, commit)
    validate_backend_worktree(repository_root, commit)
    mapping = resolve_dataset_mapping(
        repository_root=repository_root,
        local_config=_yaml(local_mapping_path),
    )
    source = discover_source_metadata(mapping.source_root)
    validate_run_unused(
        mapping, repository_root=repository_root, run_id=run_id,
        approval_id=approval_id, immutable_commit=commit,
    )
    validate_manifest_document(_yaml(manifest_path))
    output = validate_output_contract(mapping, minimum_free_bytes=4_294_967_296, run_id=run_id)
    parent_probe_passed = probe_output_parent(mapping)
    resources = validate_resource_providers()
    generated_at = now or datetime.now(timezone.utc)
    zero_calls = {
        "approval_issue_calls": 0, "approval_consume_calls": 0,
        "runtime_request_creations": 0, "runtime_execution_gate_activations": 0,
        "processing_engine_calls": 0, "payload_sessions": 0, "zip_entry_opens": 0,
        "archive_member_enumerations": 0, "json_parser_calls": 0,
        "record_parser_calls": 0, "join_calls": 0, "policy_dispatch_calls": 0,
        "output_writer_calls": 0, "checksum_calls": 0, "atomic_finalization_calls": 0,
    }
    evidence = PreflightEvidence(
        schema_version=2,
        run_id=run_id,
        approval_id=approval_id,
        execution_source_commit=commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=fingerprints.manifest_sha256,
        backend_fingerprint=fingerprints.backend_fingerprint,
        lineage={
            "result_code": lineage.result_code,
            "direct_ancestry": lineage.direct_ancestry,
            "squash_merge_mode": lineage.squash_merge_mode,
            "execution_surface_file_count": lineage.execution_surface_file_count,
            "execution_surface_paths_equal": lineage.execution_surface_paths_equal,
            "execution_surface_blobs_equal": lineage.execution_surface_blobs_equal,
            "manifest_fingerprint_equal": lineage.manifest_fingerprint_equal,
            "backend_fingerprint_equal": lineage.backend_fingerprint_equal,
            "governance_reachable_from_origin_develop": lineage.governance_reachable_from_origin_develop,
            "valid": lineage.valid,
        },
        mapping_identity={
            "dataset_id": "AIHUB-71748", "component": "SFT", "root_type": "external",
            "repository_internal": False, "read_only": True,
        },
        source_snapshot={
            "zip_count": source.zip_files, "total_bytes": source.total_bytes,
            "filename_aggregate": source.filename_aggregate,
            "modified_time_aggregate": source.modified_time_aggregate,
        },
        registry_state={
            "run_id_unused": True, "approval_id_unused": True,
            "retired_run_count": 7, "conflicting_evidence_count": 0,
        },
        output_state={
            "final_exists": False, "staging_exists": False,
            "failed_exists": False, "quarantine_exists": False,
            "parent_probe_passed": parent_probe_passed,
            "parent_probe_residue_count": 0,
        },
        resource_state={"free_disk_bytes": int(output["free_bytes"]), **resources},
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        zero_call_state=zero_calls,
        generated_at=generated_at.isoformat(),
        expires_at=(generated_at + timedelta(hours=1)).isoformat(),
    )
    fingerprint = preflight_evidence_fingerprint(evidence)
    validate_preflight_evidence(
        evidence, expected_fingerprint=fingerprint,
        expected_run_id=run_id, expected_approval_id=approval_id,
        expected_execution_source_commit=commit,
        expected_governance_record_commit=governance_record_commit,
        expected_manifest_sha256=fingerprints.manifest_sha256,
        expected_backend_fingerprint=fingerprints.backend_fingerprint,
        now=generated_at,
    )
    approval_draft = build_approval_draft(evidence, evidence_fingerprint=fingerprint)
    approval_draft_fingerprint = validate_approval_draft(
        approval_draft, evidence=evidence, evidence_fingerprint=fingerprint,
        expected_run_id=run_id, expected_approval_id=approval_id,
    )
    return {
        **asdict(evidence),
        "lineage_validation": asdict(lineage),
        "fingerprint": fingerprint,
        "approval_draft": approval_draft,
        "approval_draft_fingerprint": approval_draft_fingerprint,
        "zero_call_state": zero_calls,
        "status": "preflight_passed",
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "approval_issued": False,
        "approval_consumed": False,
        "execution_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/data/aihub-71748-sft-processing-v1.yaml"))
    parser.add_argument(
        "--execution-source-commit", "--immutable-commit",
        dest="execution_source_commit", required=True,
    )
    parser.add_argument("--governance-record-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--preflight-only", action="store_true", required=True)
    parser.add_argument("--output-evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run_preflight(
            repository_root=Path.cwd(), local_mapping_path=arguments.mapping,
            manifest_path=arguments.manifest,
            immutable_commit=arguments.execution_source_commit,
            governance_record_commit=arguments.governance_record_commit,
            run_id=arguments.run_id, approval_id=arguments.approval_id,
        )
        if arguments.output_evidence is not None:
            arguments.output_evidence.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    except (ProcessingPreflightError, RuntimeError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc), "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
