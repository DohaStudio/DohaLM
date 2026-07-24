from __future__ import annotations

import json
import random
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from scripts.datasets import stratified_record_sampler
from scripts.datasets.analyzer import DatasetEntry
from scripts.datasets.large_json_inspector import LargeJsonCandidate
from scripts.datasets.manual_path_mapping import MappingRule, load_manual_mapping
from scripts.datasets.safe_sampler import SamplerError, _sha256_text
from scripts.datasets.schema_review_bundle import (
    analyze_review_record,
    build_schema_review_bundle,
    validate_preview_request,
)
from scripts.datasets.stratified_record_sampler import (
    record_stratum,
    review_stratified_records,
    select_stratified_entries,
    select_stratified_records,
    size_bucket,
)


MIB = 1024 * 1024


def candidate(archive: str, entry: str, size: int, *, rule_id: str = "rule-test") -> LargeJsonCandidate:
    info = zipfile.ZipInfo(f"/approved/{entry}.json")
    info.file_size = size
    info.compress_size = max(1, size // 4)
    rule = MappingRule(rule_id, "/approved/", "mapped/", frozenset({".json"}))
    return LargeJsonCandidate(
        archive_path=Path(archive),
        archive_relative_path=archive,
        info=info,
        rule=rule,
        entry_name_hash=_sha256_text(info.filename),
        selection_rank=_sha256_text(f"{archive}:{entry}"),
    )


def write_mapping(path: Path) -> Path:
    path.write_text(
        """schema_version: "1.0"
dataset_id: "AIHUB-71748"
approval:
  status: approved
  approved_by: tester
  approved_at: "2026-07-24T00:00:00+09:00"
rules:
  - source_prefix: "/approved/"
    target_prefix: "mapped/"
    allowed_extensions:
      - .json
""",
        encoding="utf-8",
    )
    return path


def write_archives(root: Path, *, records: int = 12) -> list[Path]:
    paths = []
    for archive_index in range(3):
        path = root / f"archive-{archive_index}.zip"
        payload = json.dumps([
            {
                "text": f"PRIVATE-{archive_index}-{record_index}",
                "metadata": {"source": f"SOURCE-{archive_index}"},
                **({"email": "hidden@example.invalid"} if archive_index == 1 and record_index == 0 else {}),
            }
            for record_index in range(records)
        ])
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"/approved/entry-{archive_index}.json", payload)
            archive.writestr(f"/approved/second-{archive_index}.json", payload)
        paths.append(path)
    return paths


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool = False,
    max_archives: int = 3,
    max_entries_per_archive: int = 1,
    records_per_entry: int = 5,
    max_read_bytes_per_entry: int = MIB,
    max_total_read_bytes: int = 3 * MIB,
    output_name: str = "review",
):
    root = tmp_path / "dataset"
    root.mkdir(exist_ok=True)
    archives = write_archives(root) if not list(root.glob("*.zip")) else sorted(root.glob("*.zip"))
    mapping = load_manual_mapping(write_mapping(tmp_path / "mapping.yaml"), "AIHUB-71748")
    monkeypatch.setattr(stratified_record_sampler, "DEFAULT_LARGE_THRESHOLD_BYTES", 0)
    result = review_stratified_records(
        DatasetEntry("AIHUB-71748", "dataset", root),
        tmp_path / output_name,
        mapping,
        max_archives=max_archives,
        max_entries_per_archive=max_entries_per_archive,
        records_per_entry=records_per_entry,
        max_record_bytes=MIB,
        max_read_bytes_per_entry=max_read_bytes_per_entry,
        max_total_read_bytes=max_total_read_bytes,
        selection_seed="fixed-seed",
        dry_run=dry_run,
    )
    run_root = tmp_path / output_name / "AIHUB-71748" / result["run_id"]
    return result, run_root, archives


def test_archive_selection_is_distributed_and_entry_cap_is_enforced():
    rows = [
        candidate("a.zip", "a1", 35 * MIB), candidate("a.zip", "a2", 45 * MIB), candidate("a.zip", "a3", 55 * MIB),
        candidate("b.zip", "b1", 35 * MIB), candidate("b.zip", "b2", 45 * MIB),
        candidate("c.zip", "c1", 55 * MIB),
    ]
    selected = select_stratified_entries(
        "AIHUB-71748", rows, max_archives=3, max_entries_per_archive=2, selection_seed="seed",
    )
    counts = Counter(item.archive_relative_path for item in selected)
    assert len(counts) == 3
    assert max(counts.values()) <= 2


def test_size_bucket_diversity_is_preferred_within_archive():
    rows = [
        candidate("a.zip", "small", 35 * MIB),
        candidate("a.zip", "medium", 45 * MIB),
        candidate("a.zip", "large", 55 * MIB),
    ]
    selected = select_stratified_entries(
        "AIHUB-71748", rows, max_archives=1, max_entries_per_archive=3, selection_seed="seed",
    )
    assert {size_bucket(item.info.file_size) for item in selected} == {
        "under_40_mib", "40_to_50_mib", "50_mib_or_more",
    }


def test_entry_selection_is_deterministic_and_input_order_independent():
    rows = [candidate(f"{index % 3}.zip", str(index), (35 + index) * MIB) for index in range(12)]
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    first = select_stratified_entries(
        "AIHUB-71748", rows, max_archives=3, max_entries_per_archive=2, selection_seed="seed",
    )
    second = select_stratified_entries(
        "AIHUB-71748", shuffled, max_archives=3, max_entries_per_archive=2, selection_seed="seed",
    )
    assert [item.entry_name_hash for item in first] == [item.entry_name_hash for item in second]


def test_record_index_strata_cover_early_middle_and_late():
    assert record_stratum(0, 9) == "early"
    assert record_stratum(3, 9) == "middle"
    assert record_stratum(6, 9) == "late"
    records = [
        {"record_index": index, "schema_signature": "sha256:s", "fields": []}
        for index in range(9)
    ]
    selected = select_stratified_records(
        records,
        records_seen=9,
        records_per_entry=5,
        dataset_id="AIHUB-71748",
        archive_hash="sha256:a",
        entry_hash="sha256:e",
        selection_seed="seed",
    )
    assert {row["record_stratum"] for row in selected} == {"early", "middle", "late"}
    assert len(selected) == 5


def test_field_presence_ratio_and_schema_signature_aggregation():
    first = analyze_review_record({"text": "secret", "metadata": {"source": "hidden"}})
    second = analyze_review_record({"text": "other"})
    records = [
        {**first, "entry_name_hash": "e1", "record_index": 0, "record_stratum": "early"},
        {**second, "entry_name_hash": "e1", "record_index": 1, "record_stratum": "late"},
    ]
    bundle = build_schema_review_bundle(records)
    text = next(row for row in bundle["field_review_manifest"] if row["allowed_display_name"] == "text")
    metadata = next(row for row in bundle["field_review_manifest"] if row["allowed_display_name"] == "metadata")
    assert text["record_presence_ratio"] == 1.0
    assert metadata["record_presence_ratio"] == 0.5
    assert len(bundle["schema_signatures"]) == 2
    assert text["strata_presence"] == ["early", "late"]


def test_pii_checklist_never_auto_clears_and_hides_values():
    analyzed = analyze_review_record({"email": "hidden@example.invalid", "text": "PRIVATE"})
    bundle = build_schema_review_bundle([
        {**analyzed, "entry_name_hash": "e", "record_index": 0, "record_stratum": "early"},
    ])
    rendered = json.dumps(bundle, ensure_ascii=False)
    contact = next(row for row in bundle["pii_review_checklist"] if row["check"] == "contact_field_name")
    assert contact["status"] == "review_required"
    assert bundle["pii_absence_confirmed"] is False
    assert "hidden@example.invalid" not in rendered
    assert "PRIVATE" not in rendered


def test_dry_run_reads_no_entry_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_open = zipfile.ZipFile.open

    def guarded_open(*args, **kwargs):
        mode = kwargs.get("mode", args[2] if len(args) > 2 else "r")
        if mode == "r":
            raise AssertionError("dry-run에서 entry 내용을 읽으면 안 됩니다.")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded_open)
    result, run_root, _ = run_review(tmp_path, monkeypatch, dry_run=True)
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    assert result["entries_inspected"] == 0
    assert result["total_bytes_read"] == 0
    assert summary["preview_enabled"] is False


def test_actual_review_is_private_distributed_and_preserves_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, run_root, archives = run_review(tmp_path, monkeypatch)
    checksums_after = {path.name: sha256(path) for path in archives}
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    strata = json.loads((run_root / "strata-summary.json").read_text(encoding="utf-8"))
    field_manifest = json.loads((run_root / "field-review-manifest.json").read_text(encoding="utf-8"))
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in run_root.iterdir())
    assert result["archives_selected"] == 3
    assert result["entries_inspected"] == 3
    assert max(strata["archive_entry_counts"].values()) == 1
    assert {"early", "middle", "late"}.issubset(strata["record_strata_counts"])
    assert all(row["unchanged"] for row in summary["selected_archive_checksums"])
    assert checksums_after == {path.name: sha256(path) for path in archives}
    assert "PRIVATE-" not in rendered
    assert "SOURCE-" not in rendered
    assert "hidden@example.invalid" not in rendered
    assert "/approved/" not in rendered
    assert str(tmp_path) not in rendered
    assert field_manifest["fields"]


def test_total_read_limit_caps_inspection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, run_root, _ = run_review(
        tmp_path,
        monkeypatch,
        max_read_bytes_per_entry=256,
        max_total_read_bytes=128,
    )
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    assert result["total_bytes_read"] <= 128
    assert summary["total_read_limit_reached"] is True
    assert result["entries_inspected"] == 1


def test_preview_is_disabled_and_unapproved_request_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    validate_preview_request(requested=False)
    with pytest.raises(SamplerError, match="비활성화"):
        validate_preview_request(requested=True)
    result, run_root, _ = run_review(tmp_path, monkeypatch)
    review = json.loads((run_root / "manual-review-required.json").read_text(encoding="utf-8"))
    assert review["preview"]["enabled"] is False
    assert review["preview"]["implementation_status"] == "blocked_not_implemented"


def test_exact_six_review_artifacts_are_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _, run_root, _ = run_review(tmp_path, monkeypatch, dry_run=True)
    assert {path.name for path in run_root.iterdir()} == {
        "run-summary.json", "strata-summary.json", "schema-signatures.json",
        "field-review-manifest.json", "pii-review-checklist.json", "manual-review-required.json",
    }
