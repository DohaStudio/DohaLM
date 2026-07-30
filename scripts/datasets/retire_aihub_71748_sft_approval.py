"""Retire one issued Approval artifact; never consume, request, or process data."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import yaml

from src.data.processing.aihub_71748_mapping import (
    DatasetMappingError,
    resolve_dataset_mapping,
)
from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_retirement_evidence_path,
    retire_approval_file,
)
from src.data.processing.run_contract import ExecutionCounters


def _yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND") from None
    if not isinstance(value, dict):
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_ARTIFACT_NOT_FOUND")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--approval-artifact", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--expected-file-sha256", required=True)
    parser.add_argument("--expected-checksum", required=True)
    parser.add_argument("--expected-stable-fingerprint", required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--retirement-only", action="store_true", required=True)
    return parser


def retire_artifact(arguments: argparse.Namespace) -> dict[str, object]:
    repository = Path.cwd()
    mapping = resolve_dataset_mapping(
        repository_root=repository,
        local_config=_yaml(arguments.mapping),
    )
    target = arguments.approval_artifact.resolve()
    canonical = (
        mapping.processed_root / "approvals" / f"{arguments.approval_id}.json"
    ).resolve()
    if target != canonical:
        raise ProcessingApprovalError("APPROVAL_RETIREMENT_IDENTITY_MISMATCH")
    counters = ExecutionCounters()
    retired = retire_approval_file(
        target,
        expected_approval_id=arguments.approval_id,
        expected_run_id=arguments.run_id,
        expected_file_sha256=arguments.expected_file_sha256,
        expected_checksum=arguments.expected_checksum,
        expected_stable_fingerprint=arguments.expected_stable_fingerprint,
        retired_at=datetime.now(timezone.utc).isoformat(),
        reason_code=arguments.reason_code,
        counters=counters,
    )
    return {
        "status": "approval_retired_before_consumption",
        "approval": asdict(retired),
        "retirement_evidence": str(approval_retirement_evidence_path(target)),
        "counters": counters.snapshot(),
        "approval_consumed": False,
        "runtime_request_created": False,
        "runtime_gate_activated": False,
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "execution_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = retire_artifact(arguments)
    except (DatasetMappingError, ProcessingApprovalError, RuntimeError) as exc:
        print(json.dumps({
            "status": "blocked",
            "error_code": str(exc),
            "execution_allowed": False,
        }))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
