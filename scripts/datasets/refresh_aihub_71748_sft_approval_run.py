"""Metadata-only active-run refresh; never issues or consumes an Approval."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Mapping

import yaml

from src.data.aihub_71748_approval_refresh import (
    ACTIVE_RUN_STATUS,
    ActiveRunRegistry,
    ActiveRunRegistryState,
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
    build_refresh_approval_draft,
    fingerprints_for_refresh,
    validate_active_run_for_approval_refresh,
    validate_approval_refresh_evidence,
    validate_governance_refresh_checkout,
    validate_previous_preflight_evidence,
)
from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    ProcessingPreflightError,
    discover_source_metadata,
    probe_output_parent,
    validate_manifest_document,
    validate_output_contract,
    validate_resource_providers,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping, resolve_dataset_mapping


def _yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ProcessingPreflightError("PREFLIGHT_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise ProcessingPreflightError("PREFLIGHT_CONFIG_INVALID")
    return value


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ProcessingPreflightError("ACTIVE_RUN_REGISTRY_NOT_FOUND") from None
    if not isinstance(value, dict):
        raise ProcessingPreflightError("ACTIVE_RUN_REGISTRY_NOT_FOUND")
    return value


class CanonicalEvidenceRegistry(ActiveRunRegistry):
    """Strict adapter over the canonical preflight evidence and runtime roots."""

    def __init__(
        self,
        mapping: ResolvedDatasetMapping,
        evidence_path: Path,
        evidence_value: dict[str, object],
        fingerprint: str,
    ) -> None:
        self.mapping = mapping
        self.evidence_path = evidence_path.resolve()
        self.evidence_value = evidence_value
        self.fingerprint = fingerprint

    def read_active_run(self, run_id: str, approval_id: str) -> ActiveRunRegistryState:
        canonical = (
            self.mapping.processed_root / "runtime-evidence" / run_id / "preflight-evidence.json"
        ).resolve()
        if self.evidence_path != canonical or not canonical.is_file():
            raise KeyError(run_id)
        zero_calls = self.evidence_value.get("zero_call_state")
        required_outer = {"run_id", "approval_id", "status", "payload_reads", "processing_calls", "output_writes"}
        if not isinstance(zero_calls, dict) or not required_outer <= set(self.evidence_value):
            raise ProcessingPreflightError("PREFLIGHT_REGISTRY_STATE_MISMATCH")
        run_evidence_files = [path for path in canonical.parent.iterdir() if path.is_file()]
        approval_path = self.mapping.processed_root / "approvals" / f"{approval_id}.json"
        runtime_request_root = self.mapping.processed_root / "runtime-evidence" / approval_id
        return ActiveRunRegistryState(
            run_id=str(self.evidence_value.get("run_id", "")),
            approval_id=str(self.evidence_value.get("approval_id", "")),
            run_status=str(self.evidence_value.get("status", "")),
            previous_preflight_evidence_fingerprint=self.fingerprint,
            approval_id_unused=not approval_path.exists() and not runtime_request_root.exists(),
            approval_artifact_exists=approval_path.exists() or approval_path.with_suffix(".json.tmp").exists(),
            approval_issue_calls=int(zero_calls.get("approval_issue_calls", -1)),
            approval_consume_calls=int(zero_calls.get("approval_consume_calls", -1)),
            runtime_request_exists=runtime_request_root.exists(),
            processing_started=int(self.evidence_value.get("processing_calls", 0)) != 0,
            payload_reads=int(self.evidence_value.get("payload_reads", 0)),
            processing_calls=int(self.evidence_value.get("processing_calls", 0)),
            output_writes=int(self.evidence_value.get("output_writes", 0)),
            conflicting_evidence_count=sum(path != canonical for path in run_evidence_files),
        )


def _lineage_state(lineage: object) -> dict[str, object]:
    value = asdict(lineage)  # type: ignore[arg-type]
    return {
        key: value[key]
        for key in (
            "result_code", "direct_ancestry", "squash_merge_mode",
            "execution_surface_file_count", "execution_surface_paths_equal",
            "execution_surface_blobs_equal", "manifest_fingerprint_equal",
            "backend_fingerprint_equal", "governance_reachable_from_origin_develop", "valid",
        )
    }


def run_approval_refresh(
    *,
    repository_root: Path,
    local_mapping_path: Path,
    manifest_path: Path,
    execution_source_commit: str,
    governance_record_commit: str,
    run_id: str,
    approval_id: str,
    preflight_evidence_path: Path,
    preflight_evidence_fingerprint: str,
    now: datetime | None = None,
) -> dict[str, object]:
    lineage = validate_governance_refresh_checkout(
        repository_root, execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
    )
    manifest_sha256, backend_fingerprint = fingerprints_for_refresh(
        repository_root, execution_source_commit, governance_record_commit,
    )
    mapping = resolve_dataset_mapping(
        repository_root=repository_root, local_config=_yaml(local_mapping_path),
    )
    prior_value = _json(preflight_evidence_path)
    prior: PreflightEvidence = validate_previous_preflight_evidence(
        prior_value, expected_fingerprint=preflight_evidence_fingerprint,
        run_id=run_id, approval_id=approval_id,
        execution_source_commit=execution_source_commit,
    )
    if prior.manifest_sha256 != manifest_sha256:
        raise ProcessingPreflightError("MANIFEST_FINGERPRINT_MISMATCH")
    if prior.backend_fingerprint != backend_fingerprint:
        raise ProcessingPreflightError("BACKEND_FINGERPRINT_MISMATCH")
    registry = CanonicalEvidenceRegistry(
        mapping, preflight_evidence_path, prior_value, preflight_evidence_fingerprint,
    )
    state = validate_active_run_for_approval_refresh(
        mapping, run_id=run_id, approval_id=approval_id,
        expected_preflight_fingerprint=preflight_evidence_fingerprint,
        expected_run_status=ACTIVE_RUN_STATUS, registry=registry,
    )
    validate_manifest_document(_yaml(manifest_path))
    source = discover_source_metadata(mapping.source_root)
    source_snapshot = {
        "zip_count": source.zip_files, "total_bytes": source.total_bytes,
        "filename_aggregate": source.filename_aggregate,
        "modified_time_aggregate": source.modified_time_aggregate,
    }
    if source_snapshot != dict(prior.source_snapshot):
        raise ProcessingPreflightError("SOURCE_PACKAGE_DRIFT")
    output = validate_output_contract(mapping, minimum_free_bytes=4_294_967_296, run_id=run_id)
    parent_probe_passed = probe_output_parent(mapping)
    resources = validate_resource_providers()
    generated = now or datetime.now(timezone.utc)
    zero_calls = dict(prior.zero_call_state)
    evidence = ApprovalRefreshEvidence(
        schema_version=1, validation_phase="approval_refresh", run_id=run_id,
        approval_id=approval_id,
        previous_preflight_evidence_fingerprint=preflight_evidence_fingerprint,
        execution_source_commit=execution_source_commit,
        governance_record_commit=governance_record_commit,
        manifest_sha256=manifest_sha256, backend_fingerprint=backend_fingerprint,
        lineage=_lineage_state(lineage), mapping_identity=dict(prior.mapping_identity),
        source_snapshot=source_snapshot,
        registry_state={
            "run_status": state.run_status, "run_id_unused": False,
            "approval_id_unused": state.approval_id_unused,
            "conflicting_evidence_count": state.conflicting_evidence_count,
        },
        runtime_state={
            "approval_artifact_exists": state.approval_artifact_exists,
            "approval_issue_calls": state.approval_issue_calls,
            "approval_consume_calls": state.approval_consume_calls,
            "runtime_request_exists": state.runtime_request_exists,
            "processing_started": state.processing_started,
            "payload_reads": state.payload_reads, "processing_calls": state.processing_calls,
            "output_writes": state.output_writes,
        },
        output_state={
            "final_exists": False, "staging_exists": False, "failed_exists": False,
            "quarantine_exists": False, "parent_probe_passed": parent_probe_passed,
            "parent_probe_residue_count": 0,
        },
        resource_state={"free_disk_bytes": int(output["free_bytes"]), **resources},
        runtime_budget=dict(prior.runtime_budget), memory_budget=dict(prior.memory_budget),
        disk_budget=dict(prior.disk_budget), record_budget=dict(prior.record_budget),
        output_budget=dict(prior.output_budget), zero_call_state=zero_calls,
        generated_at=generated.isoformat(),
        expires_at=(generated + timedelta(hours=1)).isoformat(),
    )
    fingerprint = approval_refresh_evidence_fingerprint(evidence)
    validate_approval_refresh_evidence(
        evidence, expected_fingerprint=fingerprint, expected_run_id=run_id,
        expected_approval_id=approval_id,
        expected_execution_source_commit=execution_source_commit,
        expected_governance_record_commit=governance_record_commit,
        expected_manifest_sha256=manifest_sha256,
        expected_backend_fingerprint=backend_fingerprint,
        expected_previous_preflight_fingerprint=preflight_evidence_fingerprint,
        now=generated,
    )
    draft = build_refresh_approval_draft(evidence, evidence_fingerprint=fingerprint)
    return {
        **asdict(evidence), "fingerprint": fingerprint, "approval_draft": draft,
        "status": "approval_refresh_validated", "approval_issued": False,
        "approval_consumed": False, "runtime_request_created": False,
        "payload_reads": 0, "processing_calls": 0, "output_writes": 0,
        "execution_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/data/aihub-71748-sft-processing-v1.yaml"))
    parser.add_argument("--execution-source-commit", required=True)
    parser.add_argument("--governance-record-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--preflight-evidence-fingerprint", required=True)
    parser.add_argument("--approval-refresh-only", action="store_true", required=True)
    parser.add_argument("--output-evidence", type=Path)
    return parser


def _write_evidence(path: Path, value: Mapping[str, object]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError("short write")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_ALREADY_EXISTS") from None
    except OSError:
        raise ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_WRITE_FAILED") from None


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run_approval_refresh(
            repository_root=Path.cwd(), local_mapping_path=arguments.mapping,
            manifest_path=arguments.manifest,
            execution_source_commit=arguments.execution_source_commit,
            governance_record_commit=arguments.governance_record_commit,
            run_id=arguments.run_id, approval_id=arguments.approval_id,
            preflight_evidence_path=arguments.preflight_evidence,
            preflight_evidence_fingerprint=arguments.preflight_evidence_fingerprint,
        )
        if arguments.output_evidence is not None:
            _write_evidence(arguments.output_evidence, result)
    except (ProcessingPreflightError, RuntimeError) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc), "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
