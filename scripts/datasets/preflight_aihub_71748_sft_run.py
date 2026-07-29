"""Metadata-only preflight evidence generator requiring an explicit immutable commit."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import yaml

from src.data.aihub_71748_processing_preflight import (
    APPROVAL_ID,
    RUN_ID,
    PreflightEvidence,
    ProcessingPreflightError,
    compute_git_fingerprints,
    discover_source_metadata,
    preflight_evidence_fingerprint,
    validate_backend_worktree,
    validate_immutable_commit,
    validate_manifest_document,
    validate_output_contract,
    validate_run_unused,
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
    run_id: str,
    approval_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    commit = validate_immutable_commit(repository_root, immutable_commit)
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
    evidence = PreflightEvidence(
        run_id=run_id,
        approval_id=approval_id,
        immutable_git_commit=commit,
        manifest_sha256=fingerprints.manifest_sha256,
        backend_fingerprint=fingerprints.backend_fingerprint,
        mapping_identity="AIHUB-71748:SFT:external:read_only",
        source_zip_count=source.zip_files,
        source_total_bytes=source.total_bytes,
        output_root_state="absent",
        staging_root_state="absent",
        quarantine_state="absent",
        free_disk_bytes=int(output["free_bytes"]),
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        generated_at=(now or datetime.now(timezone.utc)).isoformat(),
    )
    fingerprint = preflight_evidence_fingerprint(evidence)
    return {
        **asdict(evidence),
        "fingerprint": fingerprint,
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
    parser.add_argument("--immutable-commit", required=True)
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--approval-id", default=APPROVAL_ID)
    parser.add_argument("--output-evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run_preflight(
            repository_root=Path.cwd(), local_mapping_path=arguments.mapping,
            manifest_path=arguments.manifest, immutable_commit=arguments.immutable_commit,
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
