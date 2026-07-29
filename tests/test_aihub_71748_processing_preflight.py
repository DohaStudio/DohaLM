from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import subprocess

import pytest
import yaml

import src.data.aihub_71748_processing_preflight as preflight
from src.data.aihub_71748_processing_preflight import (
    APPROVAL_ID,
    RUN_ID,
    PreflightEvidence,
    ProcessingPreflightError,
    compute_git_fingerprints,
    discover_source_metadata,
    preflight_evidence_fingerprint,
    validate_immutable_commit,
    validate_manifest_document,
    validate_output_contract,
    validate_preflight_evidence,
    validate_run_unused,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping


MANIFEST_PATH = Path("configs/data/aihub-71748-sft-processing-v1.yaml")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)


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
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        immutable_git_commit="a" * 40,
        manifest_sha256="b" * 64,
        backend_fingerprint="c" * 64,
        mapping_identity="AIHUB-71748:SFT:external:read_only",
        source_zip_count=55,
        source_total_bytes=17_256_335_769,
        output_root_state="absent",
        staging_root_state="absent",
        quarantine_state="absent",
        free_disk_bytes=8_000_000_000,
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        generated_at=NOW.isoformat(),
    )
    return replace(value, **changes)


def test_run_0003_identity_is_contract_only() -> None:
    assert RUN_ID.endswith("0003") and APPROVAL_ID.endswith("0003")


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
    validate_run_unused(_mapping(source, tmp_path / "processed"), repository_root=Path.cwd(), immutable_commit="HEAD")


@pytest.mark.parametrize("suffix", ["", ".staging", ".failed"])
def test_run_artifact_collision_fails_closed(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed"
    (output / f"{RUN_ID}{suffix}").mkdir(parents=True)
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_ALREADY_USED$"):
        validate_run_unused(_mapping(source, output), repository_root=Path.cwd(), immutable_commit="HEAD")


def test_output_contract_and_disk_budget(tmp_path: Path) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed" / "instruct" / "AIHUB-71748"
    assert validate_output_contract(_mapping(source, output), minimum_free_bytes=1)["run_root_exists"] is False
    with pytest.raises(ProcessingPreflightError, match="^DISK_BUDGET_INSUFFICIENT$"):
        validate_output_contract(_mapping(source, output), minimum_free_bytes=2**63)


def test_preflight_fingerprint_is_deterministic() -> None:
    assert preflight_evidence_fingerprint(_evidence()) == preflight_evidence_fingerprint(_evidence())


def test_preflight_evidence_validates() -> None:
    evidence = _evidence()
    validate_preflight_evidence(evidence, expected_fingerprint=preflight_evidence_fingerprint(evidence), now=NOW)


def test_preflight_fingerprint_mismatch_fails_closed() -> None:
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH$"):
        validate_preflight_evidence(_evidence(), expected_fingerprint="0" * 64, now=NOW)


def test_stale_preflight_fails_closed() -> None:
    evidence = _evidence(generated_at=(NOW - timedelta(hours=2)).isoformat())
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_EVIDENCE_STALE$"):
        validate_preflight_evidence(evidence, expected_fingerprint=preflight_evidence_fingerprint(evidence), now=NOW)


@pytest.mark.parametrize("field", ["output_root_state", "staging_root_state", "quarantine_state"])
def test_preflight_output_collision_fails_closed(field: str) -> None:
    evidence = _evidence(**{field: "present"})
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_ALREADY_USED$"):
        validate_preflight_evidence(evidence, expected_fingerprint=preflight_evidence_fingerprint(evidence), now=NOW)


@pytest.mark.parametrize("field,value", [("source_zip_count", 54), ("source_total_bytes", 1)])
def test_preflight_source_drift_fails_closed(field: str, value: int) -> None:
    evidence = _evidence(**{field: value})
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_PACKAGE_DRIFT$"):
        validate_preflight_evidence(evidence, expected_fingerprint=preflight_evidence_fingerprint(evidence), now=NOW)


def test_manifest_remains_non_executable() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_manifest_document(manifest)
    manifest["processing_approval"]["execution_allowed"] = True
    with pytest.raises(Exception, match="APPROVAL_PERMISSION_ESCALATION"):
        validate_manifest_document(manifest)
