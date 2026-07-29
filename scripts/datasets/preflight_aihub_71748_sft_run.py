"""Metadata-only preflight for AIHUB-71748 SFT Processing Run 0002."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

from src.data.aihub_71748_processing_preflight import (
    APPROVAL_ID,
    EXPECTED_TOTAL_BYTES,
    EXPECTED_ZIP_FILES,
    IMMUTABLE_COMMIT,
    RUN_ID,
    ProcessingPreflightError,
    compute_git_fingerprints,
    discover_source_metadata,
    validate_approval_draft,
    validate_backend_worktree,
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
    draft_path: Path,
) -> dict[str, object]:
    fingerprints = compute_git_fingerprints(repository_root)
    validate_backend_worktree(repository_root)
    local_mapping = _yaml(local_mapping_path)
    mapping = resolve_dataset_mapping(
        repository_root=repository_root,
        local_config=local_mapping,
    )
    source = discover_source_metadata(mapping.source_root)
    validate_run_unused(mapping, repository_root=repository_root)
    manifest = _yaml(manifest_path)
    validate_manifest_document(manifest)
    draft = _yaml(draft_path)
    draft_fingerprint = validate_approval_draft(draft, fingerprints=fingerprints)
    output = validate_output_contract(
        mapping,
        minimum_free_bytes=int(draft["disk_budget"]["minimum_free_bytes"]),  # type: ignore[index]
    )
    return {
        "status": "preflight_passed",
        "immutable_commit": IMMUTABLE_COMMIT,
        "run_id": RUN_ID,
        "approval_id": APPROVAL_ID,
        "run_id_reserved": True,
        "approval_status": "prepared_not_issued",
        "mapping_status": "validated_metadata_only",
        "mapping_resolution": mapping.resolution_source,
        "source_zip_files": source.zip_files,
        "source_total_bytes": source.total_bytes,
        "source_expected_zip_files": EXPECTED_ZIP_FILES,
        "source_expected_total_bytes": EXPECTED_TOTAL_BYTES,
        "source_components": list(source.components),
        "source_splits": list(source.splits),
        "manifest_sha256": fingerprints.manifest_sha256,
        "backend_fingerprint": fingerprints.backend_fingerprint,
        "backend_file_count": fingerprints.backend_file_count,
        "approval_draft_fingerprint": draft_fingerprint,
        "run_root_exists": output["run_root_exists"],
        "staging_root_exists": output["staging_root_exists"],
        "quarantine_root_exists": output["quarantine_root_exists"],
        "free_disk_bytes": output["free_bytes"],
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "approval_consumed": False,
        "processed_dataset_created": False,
        "execution_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/data/aihub-71748-sft-processing-v1.yaml"))
    parser.add_argument("--approval-draft", type=Path, default=Path("configs/data/aihub-71748-processing-run-0002-preflight.yaml"))
    parser.add_argument("--preflight-only", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.preflight_only is not True:
        print(json.dumps({"status": "blocked", "error_code": "PROCESSING_NOT_APPROVED", "execution_allowed": False}))
        return 2
    try:
        result = run_preflight(
            repository_root=Path.cwd(),
            local_mapping_path=arguments.local_mapping,
            manifest_path=arguments.manifest,
            draft_path=arguments.approval_draft,
        )
    except (ProcessingPreflightError, RuntimeError) as exc:
        code = str(exc) if str(exc).isupper() else "PREFLIGHT_FAILED_CLOSED"
        print(json.dumps({"status": "blocked", "error_code": code, "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
