from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

import scripts.datasets.issue_aihub_71748_sft_approval as issue_cli
import scripts.datasets.preflight_aihub_71748_sft_run as preflight_cli
import scripts.datasets.refresh_aihub_71748_sft_approval_run as refresh_cli
from src.data.aihub_71748_approval_refresh import (
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
    build_refresh_approval_draft,
    canonical_approval_refresh_evidence_path,
)
from src.data.aihub_71748_processing_preflight import (
    PreflightEvidence,
    GitFingerprints,
    LineageValidation,
    SourceMetadata,
    build_approval_draft,
    canonical_preflight_evidence_path,
    load_preflight_evidence_file,
    preflight_evidence_fingerprint,
    validate_approval_draft,
    write_preflight_evidence_file,
)
from src.data.aihub_71748_approval_refresh import write_approval_refresh_evidence_file
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping
from src.data.processing.approval import ProcessingApprovalError, load_approval


RUN_ID = "SYNTHETIC-RUN-0012"
APPROVAL_ID = "SYNTHETIC-APPROVAL-0012"
EXECUTION = "1" * 40
GOVERNANCE = "1" * 40
MANIFEST = "2" * 64
BACKEND = "3" * 64
NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


def _mapping(tmp_path: Path) -> ResolvedDatasetMapping:
    source = tmp_path / "source" / "AIHUB-71748"
    source.mkdir(parents=True)
    return ResolvedDatasetMapping(
        dataset_id="AIHUB-71748",
        component="SFT",
        source_root=source,
        processed_root=tmp_path / "processed",
        resolution_source="synthetic",
    )


def _zero_calls() -> dict[str, int]:
    return {
        "approval_issue_calls": 0,
        "approval_consume_calls": 0,
        "runtime_request_creations": 0,
        "runtime_execution_gate_activations": 0,
        "processing_engine_calls": 0,
        "payload_sessions": 0,
        "zip_entry_opens": 0,
        "archive_member_enumerations": 0,
        "json_parser_calls": 0,
        "record_parser_calls": 0,
        "join_calls": 0,
        "policy_dispatch_calls": 0,
        "output_writer_calls": 0,
        "checksum_calls": 0,
        "atomic_finalization_calls": 0,
    }


def _common() -> dict[str, object]:
    return {
        "lineage": {
            "result_code": "DIRECT_ANCESTRY_VALID",
            "direct_ancestry": True,
            "squash_merge_mode": False,
            "execution_surface_file_count": 10,
            "execution_surface_paths_equal": True,
            "execution_surface_blobs_equal": True,
            "manifest_fingerprint_equal": True,
            "backend_fingerprint_equal": True,
            "governance_reachable_from_origin_develop": True,
            "valid": True,
        },
        "mapping_identity": {
            "dataset_id": "AIHUB-71748",
            "component": "SFT",
            "root_type": "external",
            "repository_internal": False,
            "read_only": True,
        },
        "source_snapshot": {
            "zip_count": 55,
            "total_bytes": 17_256_335_769,
            "filename_aggregate": "4" * 64,
            "modified_time_aggregate": "5" * 64,
        },
        "output_state": {
            "final_exists": False,
            "staging_exists": False,
            "failed_exists": False,
            "quarantine_exists": False,
            "parent_probe_passed": True,
            "parent_probe_residue_count": 0,
        },
        "resource_state": {
            "free_disk_bytes": 8_000_000_000,
            "memory_provider_available": True,
            "runtime_provider_available": True,
            "current_rss_bytes": 1,
        },
        "runtime_budget": {"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        "memory_budget": {"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        "disk_budget": {
            "minimum_free_bytes": 4_294_967_296,
            "staging_multiplier": 2,
            "safety_margin_ratio": 0.25,
        },
        "record_budget": {
            "expected_training": 10580,
            "expected_validation": 1322,
            "expected_total": 11902,
            "maximum_total": 11902,
        },
        "output_budget": {
            "expected_files": 6,
            "maximum_files": 6,
            "maximum_total_bytes": 536_870_912,
        },
        "zero_call_state": _zero_calls(),
    }


def _write_evidence(
    mapping: ResolvedDatasetMapping,
    *,
    initial_minutes: int = 60,
    refresh_minutes: int = 60,
) -> tuple[str, str]:
    common = _common()
    initial_expires = NOW + timedelta(minutes=initial_minutes)
    refresh_expires = NOW + timedelta(minutes=refresh_minutes)
    initial = PreflightEvidence(
        schema_version=2,
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND,
        lineage=common["lineage"],  # type: ignore[arg-type]
        mapping_identity=common["mapping_identity"],  # type: ignore[arg-type]
        source_snapshot=common["source_snapshot"],  # type: ignore[arg-type]
        registry_state={
            "run_id_unused": True,
            "approval_id_unused": True,
            "retired_run_count": 7,
            "conflicting_evidence_count": 0,
        },
        output_state=common["output_state"],  # type: ignore[arg-type]
        resource_state=common["resource_state"],  # type: ignore[arg-type]
        runtime_budget=common["runtime_budget"],  # type: ignore[arg-type]
        memory_budget=common["memory_budget"],  # type: ignore[arg-type]
        disk_budget=common["disk_budget"],  # type: ignore[arg-type]
        record_budget=common["record_budget"],  # type: ignore[arg-type]
        output_budget=common["output_budget"],  # type: ignore[arg-type]
        zero_call_state=common["zero_call_state"],  # type: ignore[arg-type]
        generated_at=(initial_expires - timedelta(hours=1)).isoformat(),
        expires_at=initial_expires.isoformat(),
    )
    initial_fingerprint = preflight_evidence_fingerprint(initial)
    initial_draft = build_approval_draft(
        initial, evidence_fingerprint=initial_fingerprint,
    )
    initial_document = {
        **asdict(initial),
        "lineage_validation": {
            "execution_source_commit": EXECUTION,
            "governance_record_commit": GOVERNANCE,
            "execution_source_exists": True,
            "governance_commit_exists": True,
            **common["lineage"],  # type: ignore[dict-item]
        },
        "fingerprint": initial_fingerprint,
        "approval_draft": initial_draft,
        "approval_draft_fingerprint": validate_approval_draft(
            initial_draft,
            evidence=initial,
            evidence_fingerprint=initial_fingerprint,
            expected_run_id=RUN_ID,
            expected_approval_id=APPROVAL_ID,
            synthetic=True,
        ),
        "status": "preflight_passed",
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "approval_issued": False,
        "approval_consumed": False,
        "execution_allowed": False,
    }
    initial_path = canonical_preflight_evidence_path(mapping.processed_root, RUN_ID)
    initial_path.parent.mkdir(parents=True)
    initial_path.write_text(json.dumps(initial_document), encoding="utf-8")
    refresh = ApprovalRefreshEvidence(
        schema_version=1,
        validation_phase="approval_refresh",
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        previous_preflight_evidence_fingerprint=initial_fingerprint,
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND,
        lineage=common["lineage"],  # type: ignore[arg-type]
        mapping_identity=common["mapping_identity"],  # type: ignore[arg-type]
        source_snapshot=common["source_snapshot"],  # type: ignore[arg-type]
        registry_state={
            "run_status": "preflight_passed",
            "run_id_unused": False,
            "approval_id_unused": True,
            "conflicting_evidence_count": 0,
        },
        runtime_state={
            "approval_artifact_exists": False,
            "approval_issue_calls": 0,
            "approval_consume_calls": 0,
            "runtime_request_exists": False,
            "processing_started": False,
            "payload_reads": 0,
            "processing_calls": 0,
            "output_writes": 0,
        },
        output_state=common["output_state"],  # type: ignore[arg-type]
        resource_state=common["resource_state"],  # type: ignore[arg-type]
        runtime_budget=common["runtime_budget"],  # type: ignore[arg-type]
        memory_budget=common["memory_budget"],  # type: ignore[arg-type]
        disk_budget=common["disk_budget"],  # type: ignore[arg-type]
        record_budget=common["record_budget"],  # type: ignore[arg-type]
        output_budget=common["output_budget"],  # type: ignore[arg-type]
        zero_call_state=common["zero_call_state"],  # type: ignore[arg-type]
        generated_at=(refresh_expires - timedelta(hours=1)).isoformat(),
        expires_at=refresh_expires.isoformat(),
    )
    refresh_fingerprint = approval_refresh_evidence_fingerprint(refresh)
    refresh_document = {
        **asdict(refresh),
        "fingerprint": refresh_fingerprint,
        "approval_draft": build_refresh_approval_draft(
            refresh, evidence_fingerprint=refresh_fingerprint,
        ),
        "status": "approval_refresh_validated",
        "approval_issued": False,
        "approval_consumed": False,
        "runtime_request_created": False,
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "execution_allowed": False,
    }
    canonical_approval_refresh_evidence_path(
        mapping.processed_root, RUN_ID,
    ).write_text(json.dumps(refresh_document), encoding="utf-8")
    return initial_fingerprint, refresh_fingerprint


def _prepare(monkeypatch, tmp_path, **times):
    mapping = _mapping(tmp_path)
    fingerprints = _write_evidence(mapping, **times)
    monkeypatch.setattr(issue_cli, "_validate_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        issue_cli,
        "fingerprints_for_refresh",
        lambda *args, **kwargs: (MANIFEST, BACKEND),
    )
    return mapping, fingerprints


def _issue(mapping, fingerprints):
    return issue_cli.issue_from_evidence(
        repository=Path.cwd(),
        mapping=mapping,
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        initial_fingerprint=fingerprints[0],
        refresh_fingerprint=fingerprints[1],
        approved_by="synthetic-user",
        now=NOW,
    )


def _approval_path(mapping):
    return mapping.processed_root / "approvals" / f"{APPROVAL_ID}.json"


def test_issue_cli_core_issues_once_without_execution(monkeypatch, tmp_path):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    result = _issue(mapping, fingerprints)
    stored = load_approval(_approval_path(mapping))
    assert result["status"] == stored.status == "issued"
    assert result["issued"] is True and result["consumed"] is False
    assert result["execution_allowed"] is False
    assert result["counters"]["approval_issue_calls"] == 1
    assert result["counters"]["approval_consume_calls"] == 0
    assert result["runtime_request_created"] is False


@pytest.mark.parametrize(
    ("initial_minutes", "refresh_minutes", "expected"),
    ((-1, -1, "PREFLIGHT_EVIDENCE_STALE"), (9, 60, "APPROVAL_EVIDENCE_INSUFFICIENT_VALIDITY_WINDOW")),
)
def test_issue_cli_blocks_expired_or_short_window(
    monkeypatch, tmp_path, initial_minutes, refresh_minutes, expected,
):
    mapping, fingerprints = _prepare(
        monkeypatch,
        tmp_path,
        initial_minutes=initial_minutes,
        refresh_minutes=refresh_minutes,
    )
    calls = []
    monkeypatch.setattr(issue_cli, "issue_approval", lambda *args, **kwargs: calls.append(1))
    with pytest.raises(RuntimeError, match=expected):
        _issue(mapping, fingerprints)
    assert calls == [] and not _approval_path(mapping).exists()


def test_issue_cli_blocks_fingerprint_mismatch(monkeypatch, tmp_path):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH"):
        _issue(mapping, ("f" * 64, fingerprints[1]))
    assert not _approval_path(mapping).exists()


def test_issue_cli_blocks_git_mismatch_before_issue(monkeypatch, tmp_path):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        issue_cli,
        "_validate_git_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            issue_cli.ApprovalIssueError("APPROVAL_ISSUE_GIT_LINEAGE_MISMATCH")
        ),
    )
    with pytest.raises(RuntimeError, match="APPROVAL_ISSUE_GIT_LINEAGE_MISMATCH"):
        _issue(mapping, fingerprints)
    assert not _approval_path(mapping).exists()


def test_issue_cli_preserves_existing_final(monkeypatch, tmp_path):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    target = _approval_path(mapping)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing-final")
    with pytest.raises(RuntimeError, match="APPROVAL_ISSUE_ARTIFACT_COLLISION"):
        _issue(mapping, fingerprints)
    assert target.read_bytes() == b"existing-final"


@pytest.mark.parametrize("collision", ("runtime", "output"))
def test_issue_cli_blocks_runtime_request_or_processing_output(
    monkeypatch, tmp_path, collision,
):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    if collision == "runtime":
        path = mapping.processed_root / "runtime-evidence" / APPROVAL_ID
    else:
        path = mapping.processed_root / RUN_ID
    path.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="APPROVAL_ISSUE_ARTIFACT_COLLISION"):
        _issue(mapping, fingerprints)
    assert not _approval_path(mapping).exists()


def test_issue_cli_concurrent_publish_has_one_winner(monkeypatch, tmp_path):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)

    def attempt():
        try:
            return _issue(mapping, fingerprints)["status"]
        except RuntimeError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: attempt(), range(2)))
    assert results.count("issued") == 1
    assert len(list((_approval_path(mapping).parent).glob(f"{APPROVAL_ID}.json"))) == 1
    assert not _approval_path(mapping).with_name(_approval_path(mapping).name + ".tmp").exists()


def test_issue_cli_reports_reload_failure_without_follow_on_actions(
    monkeypatch, tmp_path,
):
    mapping, fingerprints = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        issue_cli,
        "load_approval",
        lambda _path: (_ for _ in ()).throw(ProcessingApprovalError("APPROVAL_NOT_FOUND")),
    )
    with pytest.raises(ProcessingApprovalError, match="APPROVAL_NOT_FOUND"):
        _issue(mapping, fingerprints)
    assert _approval_path(mapping).exists()
    assert not (mapping.processed_root / "runtime-evidence" / APPROVAL_ID).exists()
    assert not (mapping.processed_root / RUN_ID).exists()


def test_production_builders_writers_loader_and_approval_cli_integrate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    live_now = datetime.now(timezone.utc)
    run_id = "AIHUB-71748-SFT-PROCESSING-20990101-0013"
    approval_id = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-0013"
    mapping = _mapping(tmp_path)
    lineage = LineageValidation(
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        execution_source_exists=True,
        governance_commit_exists=True,
        result_code="DIRECT_ANCESTRY_VALID",
        direct_ancestry=True,
        squash_merge_mode=False,
        execution_surface_file_count=10,
        execution_surface_paths_equal=True,
        execution_surface_blobs_equal=True,
        manifest_fingerprint_equal=True,
        backend_fingerprint_equal=True,
        governance_reachable_from_origin_develop=True,
        valid=True,
    )
    fingerprints = GitFingerprints(
        immutable_commit=EXECUTION, manifest_sha256=MANIFEST,
        backend_fingerprint=BACKEND, backend_file_count=10,
    )
    source = SourceMetadata(
        zip_files=55, total_bytes=17_256_335_769,
        filename_aggregate="4" * 64, modified_time_aggregate="5" * 64,
        modified_min_utc=live_now.isoformat(), modified_max_utc=live_now.isoformat(),
        components=("SFTdata", "SFTlabel"), splits=("Training", "Validation"),
    )
    monkeypatch.setattr(preflight_cli, "validate_immutable_commit", lambda *_: EXECUTION)
    monkeypatch.setattr(preflight_cli, "validate_immutable_lineage", lambda *_, **__: lineage)
    monkeypatch.setattr(preflight_cli, "compute_git_fingerprints", lambda *_: fingerprints)
    monkeypatch.setattr(preflight_cli, "validate_backend_worktree", lambda *_: None)
    monkeypatch.setattr(preflight_cli, "resolve_dataset_mapping", lambda **_: mapping)
    monkeypatch.setattr(preflight_cli, "discover_source_metadata", lambda *_: source)
    monkeypatch.setattr(preflight_cli, "validate_run_unused", lambda *_, **__: None)
    monkeypatch.setattr(preflight_cli, "validate_manifest_document", lambda *_: None)
    monkeypatch.setattr(
        preflight_cli, "validate_output_contract",
        lambda *_, **__: {"free_bytes": 8_000_000_000},
    )
    monkeypatch.setattr(preflight_cli, "probe_output_parent", lambda *_: True)
    monkeypatch.setattr(
        preflight_cli, "validate_resource_providers",
        lambda: {
            "memory_provider_available": True,
            "runtime_provider_available": True,
            "current_rss_bytes": 1,
        },
    )
    monkeypatch.setattr(preflight_cli, "_yaml", lambda *_: {})
    initial = preflight_cli.run_preflight(
        repository_root=tmp_path,
        local_mapping_path=tmp_path / "mapping.yaml",
        manifest_path=tmp_path / "manifest.yaml",
        immutable_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        run_id=run_id,
        approval_id=approval_id,
        now=live_now,
    )
    initial_path = canonical_preflight_evidence_path(mapping.processed_root, run_id)
    write_preflight_evidence_file(
        initial_path, initial, expected_fingerprint=str(initial["fingerprint"]),
    )
    loaded, loaded_document = load_preflight_evidence_file(
        initial_path, expected_fingerprint=str(initial["fingerprint"]), now=live_now,
    )
    assert loaded.run_id == run_id
    assert loaded_document == initial

    monkeypatch.setattr(refresh_cli, "validate_governance_refresh_checkout", lambda *_, **__: lineage)
    monkeypatch.setattr(refresh_cli, "fingerprints_for_refresh", lambda *_, **__: (MANIFEST, BACKEND))
    monkeypatch.setattr(refresh_cli, "resolve_dataset_mapping", lambda **_: mapping)
    monkeypatch.setattr(refresh_cli, "discover_source_metadata", lambda *_: source)
    monkeypatch.setattr(refresh_cli, "validate_manifest_document", lambda *_: None)
    monkeypatch.setattr(
        refresh_cli, "validate_output_contract",
        lambda *_, **__: {"free_bytes": 8_000_000_000},
    )
    monkeypatch.setattr(refresh_cli, "probe_output_parent", lambda *_: True)
    monkeypatch.setattr(
        refresh_cli, "validate_resource_providers",
        lambda: {
            "memory_provider_available": True,
            "runtime_provider_available": True,
            "current_rss_bytes": 1,
        },
    )
    monkeypatch.setattr(refresh_cli, "_yaml", lambda *_: {})
    refresh = refresh_cli.run_approval_refresh(
        repository_root=tmp_path,
        local_mapping_path=tmp_path / "mapping.yaml",
        manifest_path=tmp_path / "manifest.yaml",
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        run_id=run_id,
        approval_id=approval_id,
        preflight_evidence_path=initial_path,
        preflight_evidence_fingerprint=str(initial["fingerprint"]),
        now=live_now,
    )
    refresh_path = canonical_approval_refresh_evidence_path(
        mapping.processed_root, run_id,
    )
    write_approval_refresh_evidence_file(
        refresh_path, refresh, expected_fingerprint=str(refresh["fingerprint"]),
    )
    monkeypatch.setattr(issue_cli, "_validate_git_state", lambda *_, **__: None)
    monkeypatch.setattr(
        issue_cli, "fingerprints_for_refresh", lambda *_, **__: (MANIFEST, BACKEND),
    )
    result = issue_cli.issue_from_evidence(
        repository=tmp_path,
        mapping=mapping,
        run_id=run_id,
        approval_id=approval_id,
        execution_source_commit=EXECUTION,
        governance_record_commit=GOVERNANCE,
        initial_fingerprint=str(initial["fingerprint"]),
        refresh_fingerprint=str(refresh["fingerprint"]),
        approved_by="synthetic-user",
        now=live_now,
    )
    assert result["status"] == "issued"
