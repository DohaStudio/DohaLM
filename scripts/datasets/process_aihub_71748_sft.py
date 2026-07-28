"""Fail-closed CLI for a future separately approved AIHUB-71748 SFT run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from src.data.processing.aihub_71748_manifest import validate_aihub_71748_processing_manifest
from src.data.processing.aihub_71748_mapping import (
    DatasetMappingError,
    resolve_dataset_mapping,
    existing_parent,
)
from src.data.processing.aihub_71748_reader import (
    discover_sft_sources,
)
from src.data.processing.aihub_71748_processor import execute_approved_processing
from src.data.processing.approval import load_approval
from src.data.processing.run_contract import ProcessingRunContract


def _mapping_document(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.is_file():
        return None
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    return value


def metadata_preflight(
    *,
    repository_root: Path,
    manifest_path: Path,
    local_mapping_path: Path | None,
    explicit_root: Path | None,
) -> dict[str, object]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    validate_aihub_71748_processing_manifest(manifest)
    resolved = resolve_dataset_mapping(
        repository_root=repository_root,
        explicit_root=explicit_root,
        local_config=_mapping_document(local_mapping_path),
    )
    sources = discover_sft_sources(resolved.source_root)
    return {
        "status": "preflight_passed",
        "mapping_resolution": resolved.resolution_source,
        "dataset_id": resolved.dataset_id,
        "component": resolved.component,
        "source_archives": len(sources),
        "source_bytes": sum(source.path.stat().st_size for source in sources),
        "disk_free_bytes": shutil.disk_usage(existing_parent(resolved.processed_root)).free,
        "payload_opened": False,
        "approval_created": False,
        "approval_consumed": False,
        "processing_calls": 0,
        "dataset_written": False,
        "execution_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("configs/data/aihub-71748-sft-processing-v1.yaml"))
    parser.add_argument("--local-mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--approval-path", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--processing-allowed", action="store_true", default=False)
    return parser


def _immutable_git_commit(repository_root: Path) -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repository_root,
        check=True, capture_output=True, text=True,
    )
    if status.stdout.strip():
        raise RuntimeError("WORKING_TREE_NOT_CLEAN")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if len(commit) != 40:
        raise RuntimeError("GIT_COMMIT_MISMATCH")
    return commit


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.preflight_only and (
        arguments.dry_run
        or not arguments.processing_allowed
        or not arguments.run_id
        or arguments.approval_path is None
    ):
        print(json.dumps({"status": "blocked", "error_code": "PROCESSING_NOT_APPROVED", "execution_allowed": False}))
        return 2
    try:
        if arguments.preflight_only:
            result = metadata_preflight(
                repository_root=Path.cwd(),
                manifest_path=arguments.manifest,
                local_mapping_path=arguments.local_mapping,
                explicit_root=arguments.dataset_root,
            )
        else:
            manifest = yaml.safe_load(arguments.manifest.read_text(encoding="utf-8"))
            local_config = _mapping_document(arguments.local_mapping)
            resolved = resolve_dataset_mapping(
                repository_root=Path.cwd(),
                explicit_root=arguments.dataset_root,
                local_config=local_config,
            )
            approval = load_approval(arguments.approval_path)
            contract = ProcessingRunContract(
                run_id=arguments.run_id,
                approval_id=approval.approval_id,
                processing_allowed=True,
                execution_allowed=True,
            )
            result = execute_approved_processing(
                package_root=resolved.source_root,
                run_root=resolved.processed_root / arguments.run_id,
                repository_root=Path.cwd(),
                manifest=manifest,
                contract=contract,
                approval_path=arguments.approval_path,
                manifest_sha256=hashlib.sha256(arguments.manifest.read_bytes()).hexdigest(),
                backend_git_commit=_immutable_git_commit(Path.cwd()),
            )
    except (RuntimeError, OSError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        code = str(exc) if str(exc).isupper() else "DATASET_MAPPING_INVALID"
        print(json.dumps({"status": "blocked", "error_code": code, "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
