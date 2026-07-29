from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import zipfile

import pytest
import yaml

from src.data.aihub_71748_processing_preflight import (
    BACKEND_PATHS,
    PreflightEvidence,
    ProcessingPreflightError,
    build_approval_draft,
    deserialize_preflight_evidence,
    preflight_evidence_fingerprint,
    serialize_preflight_evidence,
    validate_approval_draft,
    validate_preflight_evidence,
)
from src.data.processing.aihub_71748_processor import execute_approved_processing
from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_fingerprint,
    issue_approval,
    fail_approval,
    load_approval,
    new_approval,
    validate_approval,
)
from src.data.processing.output_writer import OutputWriterError, write_atomic_outputs
from src.data.processing.post_validation import (
    validate_checksums,
    validate_jsonl_and_splits,
    validate_output_budget,
    validate_processing_result,
)
from src.data.processing.run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RunContractError,
    deserialize_runtime_request,
    new_runtime_execution_request,
    validate_runtime_request,
)


MANIFEST = Path("configs/data/aihub-71748-sft-processing-v1.yaml")
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
RUN_ID = "SYNTHETIC-RUN-CONTRACT-V2"
APPROVAL_ID = "SYNTHETIC-APPROVAL-CONTRACT-V2"


def _zero() -> dict[str, int]:
    return ExecutionCounters().snapshot()


def _evidence(**changes: object) -> PreflightEvidence:
    value = PreflightEvidence(
        schema_version=2,
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        execution_source_commit="1" * 40,
        governance_record_commit="2" * 40,
        manifest_sha256="3" * 64,
        backend_fingerprint="4" * 64,
        lineage={
            "result_code": "DIRECT_ANCESTRY_VALID",
            "direct_ancestry": True,
            "squash_merge_mode": False,
            "execution_surface_file_count": len(BACKEND_PATHS) + 1,
            "execution_surface_paths_equal": True,
            "execution_surface_blobs_equal": True,
            "manifest_fingerprint_equal": True,
            "backend_fingerprint_equal": True,
            "governance_reachable_from_origin_develop": True,
            "valid": True,
        },
        mapping_identity={
            "dataset_id": "AIHUB-71748", "component": "SFT", "root_type": "external",
            "repository_internal": False, "read_only": True,
        },
        source_snapshot={
            "zip_count": 4, "total_bytes": 4,
            "filename_aggregate": "5" * 64, "modified_time_aggregate": "6" * 64,
        },
        registry_state={
            "run_id_unused": True, "approval_id_unused": True,
            "retired_run_count": 7, "conflicting_evidence_count": 0,
        },
        output_state={
            "final_exists": False, "staging_exists": False, "failed_exists": False,
            "quarantine_exists": False, "parent_probe_passed": True,
            "parent_probe_residue_count": 0,
        },
        resource_state={
            "free_disk_bytes": 8_000_000_000, "current_rss_bytes": 1,
            "memory_provider_available": True, "runtime_provider_available": True,
        },
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 4, "expected_validation": 2, "expected_total": 6, "maximum_total": 6},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        zero_call_state=_zero(),
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    return replace(value, **changes)


def _validate_evidence(evidence: PreflightEvidence) -> str:
    fingerprint = preflight_evidence_fingerprint(evidence)
    validate_preflight_evidence(
        evidence,
        expected_fingerprint=fingerprint,
        expected_run_id=RUN_ID,
        expected_approval_id=APPROVAL_ID,
        expected_execution_source_commit=evidence.execution_source_commit,
        expected_governance_record_commit=evidence.governance_record_commit,
        expected_manifest_sha256=evidence.manifest_sha256,
        expected_backend_fingerprint=evidence.backend_fingerprint,
        expected_source_zip_count=4,
        expected_source_total_bytes=4,
        expected_record_budget={"expected_training": 4, "expected_validation": 2, "expected_total": 6, "maximum_total": 6},
        synthetic=True,
        now=NOW,
    )
    return fingerprint


def _contract(*, execution: bool = True) -> ProcessingRunContract:
    return ProcessingRunContract(
        RUN_ID, APPROVAL_ID,
        processing_allowed=True, payload_read_allowed=True, output_write_allowed=True,
        execution_allowed=execution, synthetic=True,
    )


def _write_zip(path: Path, component: str, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"synthetic/{component}.json", json.dumps({"data_info": records}))


def _package(root: Path) -> Path:
    prompts = {
        "t0": ("Calculate a synthetic sum", "A synthetic numeric result"),
        "t1": ("Rewrite a harmless test phrase", "A rewritten harmless phrase"),
        "t2": ("Classify an invented color", "An invented color category"),
        "t3": ("Summarize a fictional weather note", "A fictional weather summary"),
        "v0": ("Translate an artificial greeting", "An artificial translated greeting"),
        "v1": ("Extract a mock product code", "A mock extracted product code"),
    }
    for split, prefix, count in (("Training", "t", 4), ("Validation", "v", 2)):
        data = [
            {
                "data_id": f"{prefix}{index}", "question": prompts[f"{prefix}{index}"][0],
                "question_count": 1, "question_type": "qa", "data_category": "synthetic",
            }
            for index in range(count)
        ]
        labels = [
            {
                "data_id": f"{prefix}{index}", "question": prompts[f"{prefix}{index}"][0],
                "answer": {"contents": prompts[f"{prefix}{index}"][1], "answer_count": 1},
            }
            for index in range(count)
        ]
        data_name = "TS_02.synthetic.zip" if split == "Training" else "VS_02.synthetic.zip"
        label_name = "TL_02.synthetic.zip" if split == "Training" else "VL.zip"
        _write_zip(root / split / data_name, "sftdata", data)
        _write_zip(root / split / label_name, "sftlabel", labels)
    return root


def test_preflight_v2_round_trip_draft_and_legacy_block() -> None:
    evidence = _evidence()
    fingerprint = _validate_evidence(evidence)
    restored = deserialize_preflight_evidence(json.loads(serialize_preflight_evidence(evidence)))
    assert restored == evidence
    assert restored.immutable_git_commit == restored.execution_source_commit
    draft = build_approval_draft(restored, evidence_fingerprint=fingerprint)
    assert draft["schema_version"] == 2
    assert draft["execution_source_commit"] == "1" * 40
    assert draft["execution_allowed"] is False
    validate_approval_draft(
        draft, evidence=restored, evidence_fingerprint=fingerprint,
        expected_run_id=RUN_ID, expected_approval_id=APPROVAL_ID, synthetic=True,
    )
    legacy = asdict(evidence)
    legacy["schema_version"] = 1
    with pytest.raises(ProcessingPreflightError, match="^LEGACY_PREFLIGHT_EVIDENCE_NOT_EXECUTABLE$"):
        deserialize_preflight_evidence(legacy)


@pytest.mark.parametrize("field", ["failed_exists", "parent_probe_residue_count"])
def test_preflight_v2_output_state_fails_closed(field: str) -> None:
    state = dict(_evidence().output_state)
    state.pop(field)
    with pytest.raises(ProcessingPreflightError):
        _validate_evidence(_evidence(output_state=state))


def test_preflight_v2_zero_call_and_freshness_fail_closed() -> None:
    zero = _zero()
    zero.pop("runtime_request_creations")
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_ZERO_CALL_STATE_INVALID$"):
        _validate_evidence(_evidence(zero_call_state=zero))
    stale = _evidence(expires_at=(NOW - timedelta(seconds=1)).isoformat())
    with pytest.raises(ProcessingPreflightError):
        _validate_evidence(stale)


def test_runtime_request_v1_round_trip_expiry_fingerprint_and_reuse() -> None:
    contract = _contract()
    approval = new_approval(
        contract, execution_source_commit="1" * 40, governance_record_commit="2" * 40,
        manifest_sha256="3" * 64, backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64, approved_by="synthetic",
        approved_at=NOW.isoformat(),
    )
    request = new_runtime_execution_request(
        contract, request_id="SYNTHETIC-RUNTIME-REQUEST-V1",
        approval_fingerprint=approval_fingerprint(approval),
        preflight_evidence_fingerprint=approval.preflight_evidence_fingerprint,
        execution_source_commit=approval.execution_source_commit,
        governance_record_commit=approval.governance_record_commit,
        manifest_sha256=approval.manifest_sha256,
        backend_fingerprint=approval.backend_fingerprint,
        requested_by="synthetic", requested_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=5)).isoformat(), nonce="nonce-1",
    )
    assert deserialize_runtime_request(asdict(request)) == request
    with pytest.raises(RunContractError, match="^RUNTIME_REQUEST_EXPIRED$"):
        validate_runtime_request(request, contract, now=NOW + timedelta(minutes=6))
    damaged = replace(request, request_fingerprint="0" * 64)
    with pytest.raises(RunContractError, match="^RUNTIME_REQUEST_FINGERPRINT_MISMATCH$"):
        validate_runtime_request(damaged, contract, now=NOW)
    with pytest.raises(RunContractError, match="^RUNTIME_REQUEST_REUSED$"):
        validate_runtime_request(request, contract, now=NOW, used_fingerprints={request.request_fingerprint})


def test_approval_artifact_execution_flag_is_forbidden() -> None:
    contract = _contract()
    approval = new_approval(
        contract, execution_source_commit="1" * 40, governance_record_commit="2" * 40,
        manifest_sha256="3" * 64, backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64, approved_by="synthetic",
        approved_at=NOW.isoformat(),
    )
    invalid = replace(approval, execution_allowed=True, checksum="")
    from src.data.processing.approval import approval_checksum

    invalid = replace(invalid, checksum=approval_checksum(invalid))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ARTIFACT_EXECUTION_FLAG_FORBIDDEN$"):
        validate_approval(invalid, contract)


def test_approval_failed_lifecycle_supports_before_and_after_consumption() -> None:
    contract = _contract()
    prepared = new_approval(
        contract, execution_source_commit="1" * 40, governance_record_commit="2" * 40,
        manifest_sha256="3" * 64, backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64, approved_by="synthetic",
        approved_at=NOW.isoformat(),
    )
    failed = fail_approval(prepared, failed_at=NOW.isoformat())
    assert failed.status == "failed" and failed.consumed is False
    validate_approval(failed, contract)


def test_synthetic_contract_v2_full_e2e(tmp_path: Path) -> None:
    package = _package(tmp_path / "synthetic-package")
    run_root = tmp_path / "synthetic-output"
    approval_path = tmp_path / "synthetic-approval.json"
    counters = ExecutionCounters()
    contract = _contract()
    prepared = new_approval(
        contract, execution_source_commit="1" * 40, governance_record_commit="2" * 40,
        manifest_sha256="3" * 64, backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64, approved_by="synthetic",
        approved_at=NOW.isoformat(),
    )
    issued = issue_approval(
        approval_path, prepared, issued_at=NOW.isoformat(), contract=contract, counters=counters,
    )
    request = new_runtime_execution_request(
        contract, request_id="SYNTHETIC-RUNTIME-REQUEST-V1",
        approval_fingerprint=approval_fingerprint(issued),
        preflight_evidence_fingerprint=issued.preflight_evidence_fingerprint,
        execution_source_commit=issued.execution_source_commit,
        governance_record_commit=issued.governance_record_commit,
        manifest_sha256=issued.manifest_sha256,
        backend_fingerprint=issued.backend_fingerprint,
        requested_by="synthetic", requested_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=5)).isoformat(), nonce="nonce-e2e", counters=counters,
    )
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    result = execute_approved_processing(
        package_root=package, run_root=run_root, repository_root=Path.cwd(), manifest=manifest,
        contract=contract, approval_path=approval_path, manifest_sha256=issued.manifest_sha256,
        backend_git_commit=issued.execution_source_commit,
        backend_fingerprint=issued.backend_fingerprint,
        preflight_evidence_fingerprint=issued.preflight_evidence_fingerprint,
        runtime_request=request, enforce_expected_statistics=False, counters=counters,
        now=lambda: NOW.isoformat(),
    )
    assert load_approval(approval_path).status == "completed"
    assert result["approval_consumed"] is True
    assert result["counts"] == {"train": 4, "validation": 2}
    assert result["counters"] == {
        "approval_issue_calls": 1, "approval_consume_calls": 1,
        "runtime_request_creations": 1, "runtime_execution_gate_activations": 1,
        "processing_engine_calls": 1, "payload_sessions": 1, "zip_entry_opens": 4,
        "archive_member_enumerations": 4, "json_parser_calls": 4,
        "record_parser_calls": 12, "join_calls": 1, "policy_dispatch_calls": 1,
        "output_writer_calls": 1, "checksum_calls": 1, "atomic_finalization_calls": 1,
    }
    assert validate_output_budget(run_root) ["file_count"] == 6
    assert len(validate_checksums(run_root)) == 5
    post = validate_jsonl_and_splits(
        run_root, expected_training=4, expected_validation=2,
        minimum_training=4, minimum_validation=2,
    )
    assert post["jsonl_valid"] is True and post["split_isolation_valid"] is True
    persisted = yaml.safe_load((run_root / "processing-result.yaml").read_text(encoding="utf-8"))
    validate_processing_result(persisted)
    assert len(persisted["checksums_sha256"]) == 4
    assert not run_root.with_name(run_root.name + ".staging").exists()


def test_synthetic_failure_preserves_failed_evidence(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-failure"
    with pytest.raises(OutputWriterError, match="^OUTPUT_SCHEMA_MISMATCH$"):
        write_atomic_outputs(
            root, train_records=[{"unexpected": "field"}], validation_records=[],
            manifest={}, statistics={}, result={},
        )
    assert not root.exists()
    assert root.with_name(root.name + ".failed").is_dir()
    assert not root.with_name(root.name + ".staging").exists()
