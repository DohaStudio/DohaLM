from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.datasets.create_aihub_71748_sft_runtime_request as cli
from src.data.aihub_71748_approval_refresh import (
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
)
from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    preflight_evidence_fingerprint,
)
from src.data.processing.approval import approval_checksum, issue_approval, load_approval, new_approval
from src.data.processing.run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    runtime_request_fingerprint,
)
from src.data.processing.runtime_request_artifact import (
    RUNTIME_REQUEST_TTL,
    RuntimeRequestArtifactError,
    canonical_runtime_request_path,
    issue_runtime_execution_request,
    load_runtime_execution_request,
    validate_runtime_execution_request_artifact,
)


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)
RUN_ID = "AIHUB-71748-SFT-PROCESSING-20990101-9999"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9999"
EXECUTION_COMMIT = "2" * 40
GOVERNANCE_COMMIT = "3" * 40
MANIFEST = "4" * 64
BACKEND = "5" * 64
NONCE = "A" * 43


def _zero() -> dict[str, int]:
    return {name: 0 for name in ExecutionCounters().snapshot()}


def _contract() -> ProcessingRunContract:
    return ProcessingRunContract(
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=False,
        synthetic=True,
    )


def _initial() -> tuple[dict[str, object], str]:
    evidence = PreflightEvidence(
        schema_version=2,
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        execution_source_commit=EXECUTION_COMMIT,
        governance_record_commit=EXECUTION_COMMIT,
        manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND,
        lineage={}, mapping_identity={}, source_snapshot={}, registry_state={},
        output_state={}, resource_state={}, runtime_budget={}, memory_budget={},
        disk_budget={}, record_budget={}, output_budget={}, zero_call_state=_zero(),
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    fingerprint = preflight_evidence_fingerprint(evidence)
    wrapper = {
        **asdict(evidence),
        "lineage_validation": {},
        "fingerprint": fingerprint,
        "approval_draft": {},
        "approval_draft_fingerprint": "6" * 64,
        "status": "preflight_passed",
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "approval_issued": False,
        "approval_consumed": False,
        "execution_allowed": False,
    }
    return wrapper, fingerprint


def _refresh(initial_fingerprint: str) -> tuple[dict[str, object], str]:
    evidence = ApprovalRefreshEvidence(
        schema_version=1,
        validation_phase="approval_refresh",
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        previous_preflight_evidence_fingerprint=initial_fingerprint,
        execution_source_commit=EXECUTION_COMMIT,
        governance_record_commit=GOVERNANCE_COMMIT,
        manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND,
        lineage={
            "result_code": "SQUASH_MERGE_EQUIVALENT",
            "direct_ancestry": False,
            "squash_merge_mode": True,
            "execution_surface_file_count": 10,
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
            "zip_count": 55, "total_bytes": 17_256_335_769,
            "filename_aggregate": "6" * 64, "modified_time_aggregate": "7" * 64,
        },
        registry_state={
            "run_status": "preflight_passed", "run_id_unused": False,
            "approval_id_unused": True, "conflicting_evidence_count": 0,
        },
        runtime_state={
            "approval_artifact_exists": False, "approval_issue_calls": 0,
            "approval_consume_calls": 0, "runtime_request_exists": False,
            "processing_started": False, "payload_reads": 0,
            "processing_calls": 0, "output_writes": 0,
        },
        output_state={
            "final_exists": False, "staging_exists": False, "failed_exists": False,
            "quarantine_exists": False, "parent_probe_passed": True,
            "parent_probe_residue_count": 0,
        },
        resource_state={
            "free_disk_bytes": 5_000_000_000, "memory_provider_available": True,
            "runtime_provider_available": True, "current_rss_bytes": 1,
        },
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={
            "minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2,
            "safety_margin_ratio": 0.25,
        },
        record_budget={
            "expected_training": 10580, "expected_validation": 1322,
            "expected_total": 11902, "maximum_total": 11902,
        },
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        zero_call_state=_zero(),
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    fingerprint = approval_refresh_evidence_fingerprint(evidence)
    wrapper = {
        **asdict(evidence), "fingerprint": fingerprint, "approval_draft": {},
        "status": "approval_refresh_validated", "approval_issued": False,
        "approval_consumed": False, "runtime_request_created": False,
        "payload_reads": 0, "processing_calls": 0, "output_writes": 0,
        "execution_allowed": False,
    }
    return wrapper, fingerprint


def _fixture(tmp_path: Path) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    processed = tmp_path / "processed"
    initial, initial_fingerprint = _initial()
    refresh, refresh_fingerprint = _refresh(initial_fingerprint)
    initial_path = tmp_path / "initial.json"
    refresh_path = tmp_path / "refresh.json"
    initial_path.write_text(json.dumps(initial), encoding="utf-8")
    refresh_path.write_text(json.dumps(refresh), encoding="utf-8")
    contract = _contract()
    approval = new_approval(
        contract,
        execution_source_commit=EXECUTION_COMMIT,
        governance_record_commit=GOVERNANCE_COMMIT,
        manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND,
        preflight_evidence_fingerprint=refresh_fingerprint,
        approved_by="synthetic-test",
        approved_at=NOW.isoformat(),
    )
    approval_path = processed / "approvals" / f"{APPROVAL_ID}.json"
    approval_path.parent.mkdir(parents=True)
    issue_approval(
        approval_path, approval, issued_at=NOW.isoformat(), contract=contract,
    )
    return {
        "repository_root": tmp_path,
        "processed_root": processed,
        "contract": contract,
        "approval_path": approval_path,
        "initial_evidence_path": initial_path,
        "refresh_evidence_path": refresh_path,
        "initial_evidence_fingerprint": initial_fingerprint,
        "refresh_evidence_fingerprint": refresh_fingerprint,
        "requested_by": "synthetic-test",
        "now": NOW,
        "nonce": NONCE,
        "lineage_validator": lambda *_args, **_kwargs: SimpleNamespace(
            valid=True, execution_surface_blobs_equal=True,
        ),
    }


def test_issue_publishes_canonical_request_without_consuming_approval(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    approval_path = values["approval_path"]
    before = approval_path.read_bytes()  # type: ignore[union-attr]
    counters = ExecutionCounters(approval_issue_calls=1)
    path, request = issue_runtime_execution_request(**values, counters=counters)
    assert path == canonical_runtime_request_path(values["processed_root"], APPROVAL_ID)
    assert load_runtime_execution_request(path) == request
    assert approval_path.read_bytes() == before  # type: ignore[union-attr]
    assert counters.runtime_request_creations == 1
    assert counters.approval_consume_calls == counters.runtime_execution_gate_activations == 0


def test_concurrent_publishers_allow_exactly_one_success(tmp_path: Path) -> None:
    values = _fixture(tmp_path)

    def publish() -> str:
        try:
            issue_runtime_execution_request(**values)
        except RuntimeRequestArtifactError as exc:
            return str(exc)
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: publish(), range(2)))
    assert results.count("success") == 1
    assert len(results) == 2
    assert canonical_runtime_request_path(values["processed_root"], APPROVAL_ID).is_file()


@pytest.mark.parametrize("collision", ["final", "temporary", "run", "staging", "failed", "quarantine"])
def test_issue_fails_closed_on_all_collisions(tmp_path: Path, collision: str) -> None:
    values = _fixture(tmp_path)
    processed = values["processed_root"]
    final = canonical_runtime_request_path(processed, APPROVAL_ID)
    target = {
        "final": final,
        "temporary": final.with_name(final.name + ".tmp"),
        "run": processed / RUN_ID,
        "staging": processed / f"{RUN_ID}.staging",
        "failed": processed / f"{RUN_ID}.failed",
        "quarantine": processed / "quarantine" / RUN_ID,
    }[collision]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("occupied", encoding="utf-8")
    with pytest.raises(RuntimeRequestArtifactError):
        issue_runtime_execution_request(**values)


def test_nonce_reuse_is_rejected_across_approvals(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    issue_runtime_execution_request(**values)
    second_root = tmp_path / "second"
    second = _fixture(second_root)
    request = load_runtime_execution_request(canonical_runtime_request_path(values["processed_root"], APPROVAL_ID))
    request = replace(
        request,
        request_id="AIHUB-71748-SFT-RUNTIME-REQUEST-20990101-9999-0000000000000000",
        request_fingerprint="",
    )
    request = replace(request, request_fingerprint=runtime_request_fingerprint(request))
    foreign = canonical_runtime_request_path(second["processed_root"], "OTHER")
    foreign.parent.mkdir(parents=True)
    foreign.write_text(json.dumps(asdict(request), sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(RuntimeRequestArtifactError, match="NONCE_REUSED"):
        issue_runtime_execution_request(**second)


def test_weak_nonce_and_nonsynthetic_injection_are_rejected(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    with pytest.raises(RuntimeRequestArtifactError, match="NONCE_INVALID"):
        issue_runtime_execution_request(**{**values, "nonce": "weak"})
    contract = replace(values["contract"], synthetic=False)
    with pytest.raises(RuntimeRequestArtifactError, match="SCHEMA_INVALID"):
        issue_runtime_execution_request(**{**values, "contract": contract})


def test_artifact_expiry_future_time_and_reuse_fail_closed(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    path, request = issue_runtime_execution_request(**values)
    approval = json.loads(values["approval_path"].read_text(encoding="utf-8"))  # type: ignore[union-attr]
    common = {
        "expected_approval_fingerprint": request.approval_fingerprint,
        "expected_refresh_fingerprint": request.preflight_evidence_fingerprint,
        "expected_execution_source_commit": EXECUTION_COMMIT,
        "expected_governance_record_commit": GOVERNANCE_COMMIT,
        "expected_manifest_sha256": MANIFEST,
        "expected_backend_fingerprint": BACKEND,
    }
    assert approval["consumed"] is False
    with pytest.raises(RuntimeRequestArtifactError, match="REQUEST_EXPIRED|REQUEST_STALE"):
        validate_runtime_execution_request_artifact(
            path, values["contract"], **common, now=NOW + RUNTIME_REQUEST_TTL + timedelta(seconds=1),
        )
    with pytest.raises(RuntimeRequestArtifactError, match="REQUEST_REUSED"):
        validate_runtime_execution_request_artifact(
            path, values["contract"], **common, now=NOW,
            used_fingerprints={request.request_fingerprint},
        )


def test_evidence_and_approval_state_mismatches_fail_closed(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    refresh = json.loads(values["refresh_evidence_path"].read_text(encoding="utf-8"))  # type: ignore[union-attr]
    refresh["fingerprint"] = "0" * 64
    values["refresh_evidence_path"].write_text(json.dumps(refresh), encoding="utf-8")  # type: ignore[union-attr]
    with pytest.raises(RuntimeRequestArtifactError, match="REFRESH_FINGERPRINT_MISMATCH"):
        issue_runtime_execution_request(**values)


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"status": "prepared_not_issued"}, "APPROVAL_NOT_ISSUED"),
        ({"status": "consumed", "consumed": True, "consumed_at": NOW.isoformat()}, "APPROVAL_ALREADY_CONSUMED"),
        ({"execution_allowed": True}, "EXECUTION_FLAG_REQUIRED"),
    ],
)
def test_approval_lifecycle_and_execution_flag_fail_closed(
    tmp_path: Path, changes: dict[str, object], error: str,
) -> None:
    values = _fixture(tmp_path)
    path = values["approval_path"]
    record = replace(load_approval(path), **changes, checksum="")  # type: ignore[arg-type]
    record = replace(record, checksum=approval_checksum(record))
    path.write_text(  # type: ignore[union-attr]
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    with pytest.raises(RuntimeRequestArtifactError, match=error):
        issue_runtime_execution_request(**values)


def test_writer_fsync_failure_leaves_no_final(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.data.processing.runtime_request_artifact as artifact

    values = _fixture(tmp_path)
    monkeypatch.setattr(artifact.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError()))
    with pytest.raises(RuntimeRequestArtifactError, match="ATOMIC_WRITE_FAILED"):
        issue_runtime_execution_request(**values)
    assert not canonical_runtime_request_path(values["processed_root"], APPROVAL_ID).exists()


def test_cli_requires_runtime_request_only_and_never_consumes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])
    request = SimpleNamespace(request_fingerprint="8" * 64)
    monkeypatch.setattr(cli, "create_runtime_request", lambda _arguments: {
        "status": "runtime_request_issued", "approval_consumed": False,
        "processing_calls": 0, "execution_allowed": False,
    })
    args = [
        "--run-id", RUN_ID, "--approval-id", APPROVAL_ID,
        "--approval-artifact", "approval.json", "--initial-evidence", "initial.json",
        "--refresh-evidence", "refresh.json", "--initial-evidence-fingerprint", "1" * 64,
        "--refresh-evidence-fingerprint", "2" * 64,
        "--execution-source-commit", EXECUTION_COMMIT,
        "--governance-record-commit", GOVERNANCE_COMMIT,
        "--requested-by", "synthetic", "--runtime-request-only",
    ]
    assert request.request_fingerprint
    assert cli.main(args) == 0
    assert '"approval_consumed": false' in capsys.readouterr().out
