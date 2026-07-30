"""Issue one RuntimeExecutionRequest artifact; never consume or process data."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

import yaml

from src.data.processing.aihub_71748_mapping import DatasetMappingError, resolve_dataset_mapping
from src.data.processing.approval import ProcessingApprovalError, load_approval
from src.data.processing.run_contract import ExecutionCounters, ProcessingRunContract
from src.data.processing.runtime_request_artifact import (
    RuntimeRequestArtifactError,
    issue_runtime_execution_request,
    runtime_request_integrity_checksum,
)


def _yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_MAPPING_INVALID") from None
    if not isinstance(value, dict):
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_MAPPING_INVALID")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--approval-artifact", type=Path, required=True)
    parser.add_argument("--initial-evidence", type=Path, required=True)
    parser.add_argument("--refresh-evidence", type=Path, required=True)
    parser.add_argument("--initial-evidence-fingerprint", required=True)
    parser.add_argument("--refresh-evidence-fingerprint", required=True)
    parser.add_argument("--execution-source-commit", required=True)
    parser.add_argument("--governance-record-commit", required=True)
    parser.add_argument("--requested-by", required=True)
    parser.add_argument("--runtime-request-only", action="store_true", required=True)
    return parser


def create_runtime_request(arguments: argparse.Namespace) -> dict[str, object]:
    repository = Path.cwd()
    mapping = resolve_dataset_mapping(
        repository_root=repository,
        local_config=_yaml(arguments.mapping),
    )
    approval = load_approval(arguments.approval_artifact)
    if approval.processing_run_id != arguments.run_id or approval.approval_id != arguments.approval_id:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_APPROVAL_FINGERPRINT_MISMATCH")
    if approval.execution_source_commit != arguments.execution_source_commit:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH")
    if approval.governance_record_commit != arguments.governance_record_commit:
        raise RuntimeRequestArtifactError("RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH")
    contract = ProcessingRunContract(
        run_id=arguments.run_id,
        approval_id=arguments.approval_id,
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=False,
    )
    counters = ExecutionCounters()
    target, request = issue_runtime_execution_request(
        repository_root=repository,
        processed_root=mapping.processed_root,
        contract=contract,
        approval_path=arguments.approval_artifact,
        initial_evidence_path=arguments.initial_evidence,
        refresh_evidence_path=arguments.refresh_evidence,
        initial_evidence_fingerprint=arguments.initial_evidence_fingerprint,
        refresh_evidence_fingerprint=arguments.refresh_evidence_fingerprint,
        requested_by=arguments.requested_by,
        counters=counters,
    )
    return {
        "artifact": str(target),
        "request": asdict(request),
        "checksum": runtime_request_integrity_checksum(request),
        "counters": counters.snapshot(),
        "approval_consumed": False,
        "runtime_gate_activated": False,
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "execution_allowed": False,
        "status": "runtime_request_issued",
    }


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = create_runtime_request(arguments)
    except (
        DatasetMappingError,
        ProcessingApprovalError,
        RuntimeRequestArtifactError,
        RuntimeError,
    ) as exc:
        print(json.dumps({"status": "blocked", "error_code": str(exc), "execution_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
