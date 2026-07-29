from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path

import pytest
import yaml

import src.data.aihub_71748_processing_preflight as preflight
from scripts.datasets.preflight_aihub_71748_sft_run import run_preflight
from src.data.aihub_71748_processing_preflight import (
    APPROVAL_ID,
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
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping


DRAFT_PATH = Path("configs/data/aihub-71748-processing-run-0002-preflight.yaml")
MANIFEST_PATH = Path("configs/data/aihub-71748-sft-processing-v1.yaml")


@pytest.fixture(scope="module")
def fingerprints() -> preflight.GitFingerprints:
    return compute_git_fingerprints(Path.cwd())


def _draft() -> dict[str, object]:
    value = yaml.safe_load(DRAFT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _manifest() -> dict[str, object]:
    value = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


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
    total = sum(path.stat().st_size for path in root.rglob("*.zip"))
    return root, total


def _mapping(source: Path, output: Path) -> ResolvedDatasetMapping:
    return ResolvedDatasetMapping(
        dataset_id="AIHUB-71748",
        component="SFT",
        source_root=source,
        processed_root=output,
        resolution_source="synthetic",
    )


def test_git_fingerprints_are_fixed_to_immutable_commit(
    fingerprints: preflight.GitFingerprints,
) -> None:
    result = fingerprints
    assert result.immutable_commit == IMMUTABLE_COMMIT
    assert result.manifest_sha256 == "ca1f99996a459b0f6aa241ee20e2839645fea9a73cf40163169ab3fd9fbf3973"
    assert result.backend_fingerprint == "38570ac2a5126f731e9fef5bcd1cb8af2dbba6bdd696a7107503ea4e904db5d7"
    assert result.backend_file_count == 15


def test_backend_worktree_matches_immutable_execution_paths() -> None:
    validate_backend_worktree(Path.cwd())


def test_source_metadata_reads_names_and_stats_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, total = _package(tmp_path / "AIHUB-71748")
    monkeypatch.setattr(preflight, "EXPECTED_TOTAL_BYTES", total)
    result = discover_source_metadata(root)
    assert result.zip_files == 55
    assert result.total_bytes == total
    assert result.components == ("SFTdata", "SFTlabel")
    assert result.splits == ("Training", "Validation")
    assert result.payload_reads == 0


def test_source_metadata_module_has_no_archive_or_json_reader() -> None:
    source = inspect.getsource(preflight)
    assert "import zipfile" not in source
    assert "ZipFile" not in source
    assert "json.load(" not in source


def test_source_package_drift_fails_closed(tmp_path: Path) -> None:
    root, _ = _package(tmp_path / "AIHUB-71748")
    next(root.rglob("*.zip")).unlink()
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_PACKAGE_DRIFT$"):
        discover_source_metadata(root)


def test_missing_component_and_split_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _package(tmp_path / "AIHUB-71748")
    for path in list(root.rglob("*.zip")):
        if path.name.casefold().startswith("tl_02.") or path.name.casefold() == "vl.zip":
            path.rename(path.with_name("ordinary-label-package.zip"))
    total = sum(path.stat().st_size for path in root.rglob("*.zip"))
    monkeypatch.setattr(preflight, "EXPECTED_TOTAL_BYTES", total)
    with pytest.raises(ProcessingPreflightError, match="^SOURCE_COMPONENT_MISSING$"):
        discover_source_metadata(root)


def test_run_and_approval_ids_are_fixed_and_unused(tmp_path: Path) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    mapping = _mapping(source, tmp_path / "processed")
    validate_run_unused(mapping, repository_root=Path.cwd())
    assert RUN_ID.endswith("0002")
    assert APPROVAL_ID.endswith("0002")


@pytest.mark.parametrize("suffix", ["", ".staging", ".failed"])
def test_run_artifact_collision_fails_closed(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed"
    collision = output / f"{RUN_ID}{suffix}"
    collision.mkdir(parents=True)
    with pytest.raises(ProcessingPreflightError, match="^RUN_ID_ALREADY_USED$"):
        validate_run_unused(_mapping(source, output), repository_root=Path.cwd())


def test_output_contract_and_disk_budget(tmp_path: Path) -> None:
    source = tmp_path / "AIHUB-71748"
    source.mkdir()
    output = tmp_path / "processed" / "instruct" / "AIHUB-71748"
    result = validate_output_contract(_mapping(source, output), minimum_free_bytes=1)
    assert result["run_root_exists"] is False
    assert result["staging_root_exists"] is False
    with pytest.raises(ProcessingPreflightError, match="^DISK_BUDGET_INSUFFICIENT$"):
        validate_output_contract(_mapping(source, output), minimum_free_bytes=2**63)


def test_approval_draft_is_non_executable_and_fingerprinted(
    fingerprints: preflight.GitFingerprints,
) -> None:
    digest = validate_approval_draft(_draft(), fingerprints=fingerprints)
    assert len(digest) == 64
    assert _draft()["status"] == "prepared_not_issued"
    assert all(_draft()[key] is False for key in (
        "processing_allowed", "payload_read_allowed", "output_write_allowed",
        "tokenization_allowed", "training_allowed", "execution_allowed",
    ))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("processing_run_id", "AIHUB-71748-SFT-PROCESSING-20260729-0001"),
        ("approval_id", "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001"),
        ("immutable_git_commit", "0" * 40),
        ("manifest_sha256", "0" * 64),
        ("backend_fingerprint", "0" * 64),
        ("maximum_runs", 2),
        ("execution_allowed", True),
        ("status", "issued"),
    ],
)
def test_approval_identity_or_permission_drift_fails_closed(
    field: str,
    value: object,
    fingerprints: preflight.GitFingerprints,
) -> None:
    draft = _draft()
    draft[field] = value
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_DRAFT_INVALID$"):
        validate_approval_draft(draft, fingerprints=fingerprints)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("runtime_budget", "hard_limit_seconds", 3600),
        ("memory_budget", "hard_limit_mib", 6144),
        ("disk_budget", "minimum_free_bytes", 1),
        ("record_budget", "maximum_total", 11903),
        ("output_budget", "maximum_files", 7),
        ("processing_thresholds", "maximum_total_exclusion_rate", 0.11),
        ("near_duplicate", "review_min", 0.89),
    ],
)
def test_budget_or_threshold_drift_fails_closed(
    section: str,
    field: str,
    value: object,
    fingerprints: preflight.GitFingerprints,
) -> None:
    draft = _draft()
    nested = deepcopy(draft[section])
    nested[field] = value  # type: ignore[index]
    draft[section] = nested
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_DRAFT_INVALID$"):
        validate_approval_draft(draft, fingerprints=fingerprints)


def test_manifest_remains_non_executable() -> None:
    validate_manifest_document(_manifest())
    changed = _manifest()
    changed["processing_approval"]["execution_allowed"] = True  # type: ignore[index]
    with pytest.raises(Exception, match="APPROVAL_PERMISSION_ESCALATION"):
        validate_manifest_document(changed)


def test_full_synthetic_preflight_has_zero_payload_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, total = _package(tmp_path / "AIHUB-71748")
    monkeypatch.setattr(preflight, "EXPECTED_TOTAL_BYTES", total)
    local = tmp_path / "local.yaml"
    local.write_text(
        yaml.safe_dump({
            "datasets": {
                "external_root": str(tmp_path),
                "entries": {
                    "AIHUB-71748": {
                        "root": package.name,
                        "dataset_id": "AIHUB-71748",
                        "component": "SFT",
                        "root_type": "external",
                        "repository_internal": False,
                        "read_only": True,
                        "raw_immutable": True,
                        "processed_root": "processed/instruct/AIHUB-71748",
                    }
                },
            }
        }),
        encoding="utf-8",
    )
    result = run_preflight(
        repository_root=Path.cwd(),
        local_mapping_path=local,
        manifest_path=MANIFEST_PATH,
        draft_path=DRAFT_PATH,
    )
    assert result["status"] == "preflight_passed"
    assert result["payload_reads"] == 0
    assert result["processing_calls"] == 0
    assert result["output_writes"] == 0
    assert result["approval_consumed"] is False
    assert result["execution_allowed"] is False
