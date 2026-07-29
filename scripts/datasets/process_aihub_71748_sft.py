"""Fail-closed CLI for metadata preflight or separately approved processing."""

from __future__ import annotations

import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import shutil
import sys

import yaml

from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    compute_git_fingerprints,
    validate_immutable_commit,
    validate_preflight_evidence,
)
from src.data.processing.aihub_71748_manifest import validate_aihub_71748_processing_manifest
from src.data.processing.aihub_71748_mapping import DatasetMappingError, existing_parent, resolve_dataset_mapping
from src.data.processing.aihub_71748_processor import execute_approved_processing
from src.data.processing.aihub_71748_reader import discover_sft_sources
from src.data.processing.approval import load_approval
from src.data.processing.run_contract import ProcessingRunContract
from scripts.datasets.preflight_aihub_71748_sft_run import run_preflight


def _yaml(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.is_file():
        return None
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DatasetMappingError("DATASET_MAPPING_INVALID")
    return value


def _evidence(path: Path) -> tuple[PreflightEvidence, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = value.pop("fingerprint")
        allowed = {field.name for field in fields(PreflightEvidence)}
        metadata = {
            "status", "payload_reads", "processing_calls", "output_writes",
            "approval_issued", "approval_consumed", "execution_allowed",
            "approval_draft", "approval_draft_fingerprint", "zero_call_contract",
        }
        if set(value) != allowed | metadata or not isinstance(fingerprint, str):
            raise ValueError
        evidence_value = {name: value[name] for name in allowed}
        if (
            value["status"] != "preflight_passed"
            or any(value[name] != 0 for name in ("payload_reads", "processing_calls", "output_writes"))
            or any(value[name] is not False for name in ("approval_issued", "approval_consumed", "execution_allowed"))
        ):
            raise ValueError
        return PreflightEvidence(**evidence_value), fingerprint
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError("PREFLIGHT_EVIDENCE_REQUIRED") from None


def metadata_preflight(
    *,
    repository_root: Path,
    manifest_path: Path,
    mapping_path: Path | None,
    explicit_root: Path | None,
) -> dict[str, object]:
    manifest = _yaml(manifest_path)
    if manifest is None:
        raise RuntimeError("MANIFEST_NOT_FOUND")
    validate_aihub_71748_processing_manifest(manifest)
    resolved = resolve_dataset_mapping(
        repository_root=repository_root,
        explicit_root=explicit_root,
        local_config=_yaml(mapping_path),
    )
    sources = discover_sft_sources(resolved.source_root)
    return {
        "status": "preflight_passed_metadata_only",
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
    parser.add_argument("--mapping", "--local-mapping", dest="mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--approval-id")
    parser.add_argument("--approval", "--approval-path", dest="approval", type=Path)
    parser.add_argument("--immutable-commit")
    parser.add_argument("--preflight-evidence", type=Path)
    parser.add_argument("--preflight-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--synthetic-dry-run", action="store_true", default=False)
    parser.add_argument("--processing-allowed", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.synthetic_dry_run:
        print(json.dumps({"status": "blocked", "error_code": "SYNTHETIC_TEST_HARNESS_REQUIRED", "execution_allowed": False}))
        return 2
    if not arguments.preflight_only and (
        not arguments.processing_allowed
        or not arguments.run_id
        or arguments.approval is None
        or not arguments.immutable_commit
        or arguments.preflight_evidence is None
    ):
        print(json.dumps({"status": "blocked", "error_code": "PROCESSING_NOT_APPROVED", "execution_allowed": False}))
        return 2
    try:
        if arguments.preflight_only:
            if not arguments.run_id or not arguments.approval_id or not arguments.immutable_commit:
                raise RuntimeError("PREFLIGHT_IDENTITY_REQUIRED")
            result = run_preflight(
                repository_root=Path.cwd(),
                local_mapping_path=arguments.mapping,
                manifest_path=arguments.manifest,
                immutable_commit=arguments.immutable_commit,
                run_id=arguments.run_id,
                approval_id=arguments.approval_id,
            )
        else:
            commit = validate_immutable_commit(Path.cwd(), arguments.immutable_commit)
            fingerprints = compute_git_fingerprints(Path.cwd(), commit)
            evidence, evidence_fingerprint = _evidence(arguments.preflight_evidence)
            validate_preflight_evidence(evidence, expected_fingerprint=evidence_fingerprint)
            if evidence.immutable_git_commit != commit:
                raise RuntimeError("IMMUTABLE_SOURCE_COMMIT_MISMATCH")
            manifest = _yaml(arguments.manifest)
            if manifest is None:
                raise RuntimeError("MANIFEST_NOT_FOUND")
            resolved = resolve_dataset_mapping(
                repository_root=Path.cwd(), explicit_root=arguments.dataset_root,
                local_config=_yaml(arguments.mapping),
            )
            approval = load_approval(arguments.approval)
            contract = ProcessingRunContract(
                run_id=arguments.run_id,
                approval_id=approval.approval_id,
                processing_allowed=True,
                payload_read_allowed=True,
                output_write_allowed=True,
                execution_allowed=True,
            )
            result = execute_approved_processing(
                package_root=resolved.source_root,
                run_root=resolved.processed_root / arguments.run_id,
                repository_root=Path.cwd(),
                manifest=manifest,
                contract=contract,
                approval_path=arguments.approval,
                manifest_sha256=hashlib.sha256(arguments.manifest.read_bytes()).hexdigest(),
                backend_git_commit=commit,
                backend_fingerprint=fingerprints.backend_fingerprint,
                preflight_evidence_fingerprint=evidence_fingerprint,
            )
    except (RuntimeError, OSError, yaml.YAMLError) as exc:
        code = str(exc) if str(exc).isupper() else "DATASET_MAPPING_INVALID"
        print(json.dumps({"status": "blocked", "error_code": code, "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
