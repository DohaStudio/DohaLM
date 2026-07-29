from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import subprocess

import pytest
import yaml

import src.data.aihub_71748_processing_preflight as preflight
import scripts.datasets.process_aihub_71748_sft as process_cli
from src.data.aihub_71748_processing_preflight import (
    APPROVAL_ID,
    RUN_ID,
    PreflightEvidence,
    ProcessingPreflightError,
    build_approval_draft,
    compute_git_fingerprints,
    discover_source_metadata,
    preflight_evidence_fingerprint,
    probe_output_parent,
    validate_immutable_commit,
    validate_manifest_document,
    validate_approval_draft,
    validate_output_contract,
    validate_preflight_evidence,
    validate_run_unused,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping


MANIFEST_PATH = Path("configs/data/aihub-71748-sft-processing-v1.yaml")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
UNUSED_RUN_ID = "AIHUB-71748-SFT-PROCESSING-20990101-9999"
UNUSED_APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9999"


def _package(root: Path) -> tuple[Path, int]:
    files = (
        root / "Training" / "TS_02.synthetic.zip",
        root / "Training" / "TL_02.synthetic.zip",
        root / "Validation" / "VS_02.synthetic.zip",
        root / "Validation" / "VL.zip",
    )
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"metadata-only")
    for index in range(51):
        path = root / "Other" / f"package-{index:02d}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"metadata-only")
    return root, sum(path.stat().st_size for path in root.rglob("*.zip"))


def _mapping(source: Path, output: Path) -> ResolvedDatasetMapping:
    return ResolvedDatasetMapping("AIHUB-71748", "SFT", source, output, "synthetic")


def _evidence(**changes: object) -> PreflightEvidence:
    value = PreflightEvidence(
        schema_version=2,
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        execution_source_commit="a" * 40,
        governance_record_commit="f" * 40,
        manifest_sha256="b" * 64,
        backend_fingerprint="c" * 64,
        lineage={
            "result_code": "DIRECT_ANCESTRY_VALID",
            "direct_ancestry": True,
            "squash_merge_mode": False,
            "execution_surface_file_count": len(preflight.BACKEND_PATHS) + 1,
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
            "filename_aggregate": "d" * 64, "modified_time_aggregate": "e" * 64,
        },
        registry_state={
            "run_id_unused": True, "approval_id_unused": True,
            "retired_run_count": 7, "conflicting_evidence_count": 0,
        },
        output_state={
            "final_exists": False, "staging_exists": False,
            "failed_exists": False, "quarantine_exists": False,
            "parent_probe_passed": True, "parent_probe_residue_count": 0,
        },
        resource_state={
            "free_disk_bytes": 8_000_000_000, "memory_provider_available": True,
            "runtime_provider_available": True, "current_rss_bytes": 1,
        },
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        zero_call_state={
            "approval_issue_calls": 0, "approval_consume_calls": 0,
            "runtime_request_creations": 0, "runtime_execution_gate_activations": 0,
            "processing_engine_calls": 0, "payload_sessions": 0, "zip_entry_opens": 0,
            "archive_member_enumerations": 0, "json_parser_calls": 0,
            "record_parser_calls": 0, "join_calls": 0, "policy_dispatch_calls": 0,
            "output_writer_calls": 0, "checksum_calls": 0, "atomic_finalization_calls": 0,
        },
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    return replace(value, **changes)


def _validate(evidence: PreflightEvidence, fingerprint: str | None = None) -> None:
    validate_preflight_evidence(
        evidence,
        expected_fingerprint=fingerprint or preflight_evidence_fingerprint(evidence),
        expected_run_id=RUN_ID,
        expected_approval_id=APPROVAL_ID,
        expected_execution_source_commit="a" * 40,
        expected_governance_record_commit="f" * 40,
        expected_manifest_sha256="b" * 64,
        expected_backend_fingerprint="c" * 64,
        now=NOW,
    )


def test_run_0006_identity_is_retired_after_approval_contract_failure() -> None:
    assert RUN_ID.endswith("0006") and APPROVAL_ID.endswith("0006")
    source = Path("synthetic-unused")
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_RETIRED$"):
        validate_run_unused(
            _mapping(source, source / "processed"), repository_root=Path.cwd(),
            run_id=RUN_ID,
            approval_id=APPROVAL_ID,
        )


def test_immutable_commit_is_not_hardcoded() -> None:
    source = inspect.getsource(preflight)
    assert "af10abf3ef388f4efd8707489cebef2c22719751" not in source


def test_backend_fingerprint_uses_immutable_git_blobs(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    for relative in (preflight.MANIFEST_PATH, *preflight.BACKEND_PATHS):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"synthetic:{relative}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=repository, check=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=repository, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    before = compute_git_fingerprints(repository, commit)
    (repository / preflight.BACKEND_PATHS[0]).write_text("mutable worktree\n", encoding="utf-8")
    after = compute_git_fingerprints(repository, commit)
    assert before == after
    assert before.backend_file_count == len(preflight.BACKEND_PATHS)


def test_immutable_commit_is_required() -> None:
    with pytest.raises(ProcessingPreflightError, match="^IMMUTABLE_COMMIT_REQUIRED$"):
        validate_immutable_commit(Path.cwd(), None)
    with pytest.raises(ProcessingPreflightError, match="^IMMUTABLE_COMMIT_REQUIRED$"):
        compute_git_fingerprints(Path.cwd(), None)


def test_unreachable_commit_fails_closed() -> None:
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_COMMIT_NOT_REACHABLE$"):
        validate_immutable_commit(Path.cwd(), "0" * 40)


def test_source_metadata_reads_names_and_stats_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, total = _package(tmp_path / "AIHUB-71748")
    monkeypatch.setattr(preflight, "EXPECTED_TOTAL_BYTES", total)
    result = discover_source_metadata(root)
    assert (result.zip_files, result.total_bytes, result.payload_reads) == (55, total, 0)
    assert len(result.filename_aggregate) == 64
    assert len(result.modified_time_aggregate) == 64


def test_source_metadata_module_has_no_payload_reader() -> None:
    source = inspect.getsource(preflight)
    assert "import zipfile" not in source and "ZipFile" not in source and "json.load(" not in source


def test_source_package_drift_fails_closed(tmp_path: Path) -> None:
    root, _ = _package(tmp_path / "AIHUB-71748")
    next(root.rglob("*.zip")).unlink()
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_PACKAGE_DRIFT$"):
        discover_source_metadata(root)


def test_missing_component_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _package(tmp_path / "AIHUB-71748")
    for path in list(root.rglob("*.zip")):
        if path.name.casefold().startswith("tl_02.") or path.name.casefold() == "vl.zip":
            path.rename(path.with_name("ordinary.zip"))
    monkeypatch.setattr(preflight, "EXPECTED_TOTAL_BYTES", sum(path.stat().st_size for path in root.rglob("*.zip")))
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_COMPONENT_MISSING$"):
        discover_source_metadata(root)


def test_run_and_approval_ids_are_unused(tmp_path: Path) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    validate_run_unused(
        _mapping(source, tmp_path / "processed"), repository_root=Path.cwd(), immutable_commit="HEAD",
        run_id=UNUSED_RUN_ID, approval_id=UNUSED_APPROVAL_ID,
    )


@pytest.mark.parametrize("suffix", ["", ".staging", ".failed"])
def test_run_artifact_collision_fails_closed(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed"
    (output / f"{UNUSED_RUN_ID}{suffix}").mkdir(parents=True)
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_ALREADY_USED$"):
        validate_run_unused(
            _mapping(source, output), repository_root=Path.cwd(), immutable_commit="HEAD",
            run_id=UNUSED_RUN_ID, approval_id=UNUSED_APPROVAL_ID,
        )


def test_hardening_document_declaration_is_not_runtime_usage(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    hardening = repository / "docs/instruct/aihub-71748-run-0003-backend-hardening.md"
    hardening.parent.mkdir(parents=True)
    hardening.write_text(f"{UNUSED_RUN_ID}\n{UNUSED_APPROVAL_ID}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=repository, check=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=repository, check=True)
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    validate_run_unused(
        _mapping(source, tmp_path / "processed"), repository_root=repository, immutable_commit="HEAD",
        run_id=UNUSED_RUN_ID, approval_id=UNUSED_APPROVAL_ID,
    )


def test_tracked_preflight_document_is_not_runtime_usage(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    evidence = repository / "docs/instruct/aihub-71748-processing-run-20990101-preflight.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(f"{UNUSED_RUN_ID}\n{UNUSED_APPROVAL_ID}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=repository, check=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "synthetic"], cwd=repository, check=True)
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    validate_run_unused(
        _mapping(source, tmp_path / "processed"), repository_root=repository, immutable_commit="HEAD",
        run_id=UNUSED_RUN_ID, approval_id=UNUSED_APPROVAL_ID,
    )


def test_output_contract_and_disk_budget(tmp_path: Path) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed" / "instruct" / "AIHUB-71748"
    assert validate_output_contract(
        _mapping(source, output), minimum_free_bytes=1, run_id=RUN_ID,
    )["run_root_exists"] is False
    with pytest.raises(ProcessingPreflightError, match="^DISK_BUDGET_INSUFFICIENT$"):
        validate_output_contract(
            _mapping(source, output), minimum_free_bytes=2**63, run_id=RUN_ID,
        )


def test_parent_write_probe_leaves_no_residue(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "AIHUB-71748"
    source.mkdir(parents=True)
    output = tmp_path / "processed" / "instruct" / "AIHUB-71748"
    assert probe_output_parent(_mapping(source, output)) is True
    assert list(output.iterdir()) == []


def test_preflight_fingerprint_is_deterministic() -> None:
    assert preflight_evidence_fingerprint(_evidence()) == preflight_evidence_fingerprint(_evidence())


def test_preflight_evidence_validates() -> None:
    _validate(_evidence())


def test_preflight_fingerprint_mismatch_fails_closed() -> None:
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH$"):
        _validate(_evidence(), "0" * 64)


def test_stale_preflight_fails_closed() -> None:
    evidence = _evidence(generated_at=(NOW - timedelta(hours=2)).isoformat())
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_EVIDENCE_STALE$"):
        _validate(evidence)


@pytest.mark.parametrize("field", ["final_exists", "staging_exists", "failed_exists", "quarantine_exists"])
def test_preflight_output_collision_fails_closed(field: str) -> None:
    state = dict(_evidence().output_state)
    state[field] = True
    evidence = _evidence(output_state=state)
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_ALREADY_USED$"):
        _validate(evidence)


@pytest.mark.parametrize("field,value", [("zip_count", 54), ("total_bytes", 1)])
def test_preflight_source_drift_fails_closed(field: str, value: int) -> None:
    snapshot = dict(_evidence().source_snapshot)
    snapshot[field] = value
    evidence = _evidence(source_snapshot=snapshot)
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_PACKAGE_DRIFT$"):
        _validate(evidence)


def test_preflight_governance_and_registry_fail_closed() -> None:
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_GOVERNANCE_COMMIT_REQUIRED$"):
        _validate(_evidence(governance_record_commit=""))
    registry = dict(_evidence().registry_state)
    registry["processing_calls"] = 1
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_REGISTRY_STATE_MISMATCH$"):
        _validate(_evidence(registry_state=registry))


def test_approval_draft_is_prepared_but_grants_no_execution_rights() -> None:
    evidence = _evidence()
    fingerprint = preflight_evidence_fingerprint(evidence)
    draft = build_approval_draft(evidence, evidence_fingerprint=fingerprint)
    draft_fingerprint = validate_approval_draft(
        draft, evidence=evidence, evidence_fingerprint=fingerprint,
        expected_run_id=RUN_ID, expected_approval_id=APPROVAL_ID,
    )
    assert len(draft_fingerprint) == 64
    assert draft["status"] == "prepared_not_issued"
    assert all(
        draft[name] is False
        for name in (
            "processing_allowed", "payload_read_allowed", "output_write_allowed",
            "tokenization_allowed", "sft_backend_allowed", "training_allowed",
            "execution_allowed",
        )
    )


@pytest.mark.parametrize(
    "run_id,approval_id,error",
    [
        ("", APPROVAL_ID, "RUN_ID_REQUIRED"),
        (RUN_ID, "", "APPROVAL_ID_REQUIRED"),
        ("invalid", APPROVAL_ID, "RUN_ID_FORMAT_INVALID"),
        (RUN_ID, "invalid", "APPROVAL_ID_FORMAT_INVALID"),
        (RUN_ID, "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0007", "RUN_APPROVAL_SEQUENCE_MISMATCH"),
    ],
)
def test_explicit_identity_errors_are_distinct(run_id: str, approval_id: str, error: str) -> None:
    with pytest.raises(ProcessingPreflightError, match=f"^{error}$"):
        preflight.validate_explicit_identity(run_id, approval_id)


def test_preflight_identity_mismatch_is_not_reuse_error() -> None:
    evidence = _evidence(run_id="AIHUB-71748-SFT-PROCESSING-20260730-0007")
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_RUN_ID_MISMATCH$"):
        _validate(evidence)
    evidence = _evidence(approval_id="AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0007")
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_APPROVAL_ID_MISMATCH$"):
        _validate(evidence)


def test_approval_draft_identity_mismatches_are_distinct() -> None:
    evidence = _evidence()
    fingerprint = preflight_evidence_fingerprint(evidence)
    draft = build_approval_draft(evidence, evidence_fingerprint=fingerprint)
    wrong_run = dict(draft)
    wrong_run["processing_run_id"] = "AIHUB-71748-SFT-PROCESSING-20260730-0007"
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_DRAFT_RUN_ID_MISMATCH$"):
        validate_approval_draft(
            wrong_run, evidence=evidence, evidence_fingerprint=fingerprint,
            expected_run_id=RUN_ID, expected_approval_id=APPROVAL_ID,
        )
    wrong_approval = dict(draft)
    wrong_approval["approval_id"] = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0007"
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_DRAFT_APPROVAL_ID_MISMATCH$"):
        validate_approval_draft(
            wrong_approval, evidence=evidence, evidence_fingerprint=fingerprint,
            expected_run_id=RUN_ID, expected_approval_id=APPROVAL_ID,
        )


def test_preflight_only_cli_never_enters_processing_or_approval(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = {"preflight": 0, "processing": 0, "approval": 0, "payload": 0}

    def safe_preflight(**_: object) -> dict[str, object]:
        calls["preflight"] += 1
        return {
            "status": "preflight_passed", "processing_calls": 0,
            "payload_reads": 0, "output_writes": 0, "approval_issued": False,
            "approval_consumed": False, "execution_allowed": False,
        }

    def forbidden(*_: object, **__: object) -> None:
        calls["processing"] += 1
        raise AssertionError("forbidden processing path called")

    monkeypatch.setattr(process_cli, "run_preflight", safe_preflight)
    monkeypatch.setattr(process_cli, "execute_approved_processing", forbidden)
    monkeypatch.setattr(process_cli, "load_approval", forbidden)
    monkeypatch.setattr(process_cli, "discover_sft_sources", forbidden)
    result = process_cli.main([
        "--manifest", str(MANIFEST_PATH),
        "--mapping", "configs/local-datasets.yaml",
        "--run-id", RUN_ID,
        "--approval-id", APPROVAL_ID,
        "--immutable-commit", "a" * 40,
        "--governance-record-commit", "f" * 40,
        "--preflight-only",
    ])
    assert result == 0
    assert calls == {"preflight": 1, "processing": 0, "approval": 0, "payload": 0}
    assert '"execution_allowed": false' in capsys.readouterr().out


def test_manifest_remains_non_executable() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_manifest_document(manifest)
    manifest["processing_approval"]["execution_allowed"] = True
    with pytest.raises(Exception, match="APPROVAL_PERMISSION_ESCALATION"):
        validate_manifest_document(manifest)
