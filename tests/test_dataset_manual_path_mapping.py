from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.datasets import sample_aihub_dataset as cli
from scripts.datasets.analyzer import AnalyzerConfig, DatasetEntry
from scripts.datasets.manual_path_mapping import (
    DEFAULT_MANUAL_SEED,
    load_manual_mapping,
    manual_sample_output_root,
    sample_dataset_with_manual_mapping,
)
from scripts.datasets.safe_sampler import DEFAULT_EXTENSIONS, SamplerError


def dataset_entry(root: Path) -> DatasetEntry:
    return DatasetEntry("AIHUB-71748", "extracted/AIHUB-71748", root)


def write_zip(path: Path, entries: list[tuple[str, str]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapping_payload(**overrides):
    value = {
        "schema_version": "1.0",
        "dataset_id": "AIHUB-71748",
        "approval": {
            "status": "approved",
            "approved_by": "test-reviewer",
            "approved_at": "2026-07-24T00:00:00+09:00",
        },
        "rules": [
            {
                "source_prefix": "/approved/",
                "target_prefix": "mapped/",
                "allowed_extensions": [".json", ".txt"],
            }
        ],
    }
    value.update(overrides)
    return value


def write_mapping(path: Path, **overrides) -> Path:
    path.write_text(yaml.safe_dump(mapping_payload(**overrides), allow_unicode=True), encoding="utf-8")
    return path


def load_mapping(tmp_path: Path, **overrides):
    return load_manual_mapping(write_mapping(tmp_path / "mapping.yaml", **overrides), "AIHUB-71748")


def run_manual(root: Path, output: Path, mapping, *, dry_run: bool, **overrides):
    values = {
        "requested_archive": None,
        "sample_count": 20,
        "max_file_bytes": 5 * 1024 * 1024,
        "max_total_bytes": 50 * 1024 * 1024,
        "allowed_extensions": DEFAULT_EXTENSIONS,
        "dry_run": dry_run,
        "selection_seed": DEFAULT_MANUAL_SEED,
    }
    values.update(overrides)
    return sample_dataset_with_manual_mapping(dataset_entry(root), output, mapping, **values)


def read_manifest(output: Path, result: dict[str, object]) -> dict[str, object]:
    path = output / "AIHUB-71748" / str(result["run_id"]) / "mapped-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_unapproved_mapping_is_rejected(tmp_path: Path):
    approval = {"status": "pending_user_review", "approved_by": None, "approved_at": None}
    path = write_mapping(tmp_path / "mapping.yaml", approval=approval)

    with pytest.raises(SamplerError, match="approved"):
        load_manual_mapping(path, "AIHUB-71748")


def test_mapping_dataset_id_must_match_cli_dataset(tmp_path: Path):
    path = write_mapping(tmp_path / "mapping.yaml", dataset_id="AIHUB-653")

    with pytest.raises(SamplerError, match="dataset_id"):
        load_manual_mapping(path, "AIHUB-71748")


def test_mapping_schema_version_must_be_supported_string(tmp_path: Path):
    path = write_mapping(tmp_path / "mapping.yaml", schema_version=1.0)

    with pytest.raises(SamplerError, match="schema_version"):
        load_manual_mapping(path, "AIHUB-71748")


@pytest.mark.parametrize(
    "approval",
    [
        {"status": "approved", "approved_by": None, "approved_at": "2026-07-24"},
        {"status": "approved", "approved_by": "reviewer", "approved_at": None},
    ],
)
def test_approved_mapping_requires_approval_identity_and_time(tmp_path: Path, approval: dict[str, object]):
    path = write_mapping(tmp_path / "mapping.yaml", approval=approval)

    with pytest.raises(SamplerError, match="approved_by|approved_at"):
        load_manual_mapping(path, "AIHUB-71748")


def test_source_prefix_must_be_absolute_and_boundary_terminated(tmp_path: Path):
    rules = [{"source_prefix": "relative", "target_prefix": "mapped/", "allowed_extensions": [".json"]}]
    path = write_mapping(tmp_path / "mapping.yaml", rules=rules)

    with pytest.raises(SamplerError, match="source_prefix"):
        load_manual_mapping(path, "AIHUB-71748")


def test_mapping_allowed_extensions_are_restricted(tmp_path: Path):
    rules = [{"source_prefix": "/approved/", "target_prefix": "mapped/", "allowed_extensions": [".exe"]}]
    path = write_mapping(tmp_path / "mapping.yaml", rules=rules)

    with pytest.raises(SamplerError, match="allowed_extensions"):
        load_manual_mapping(path, "AIHUB-71748")


def test_duplicate_source_prefix_is_rejected(tmp_path: Path):
    duplicate = {
        "source_prefix": "/approved/",
        "target_prefix": "second/",
        "allowed_extensions": [".json"],
    }
    path = write_mapping(tmp_path / "mapping.yaml", rules=mapping_payload()["rules"] + [duplicate])

    with pytest.raises(SamplerError, match="source_prefix"):
        load_manual_mapping(path, "AIHUB-71748")


@pytest.mark.parametrize("target", ["../escape/", "/absolute/", "C:/drive/", "//server/share/"])
def test_dangerous_target_prefix_is_rejected(tmp_path: Path, target: str):
    rules = [{"source_prefix": "/approved/", "target_prefix": target, "allowed_extensions": [".json"]}]
    path = write_mapping(tmp_path / "mapping.yaml", rules=rules)

    with pytest.raises(SamplerError, match="target_prefix"):
        load_manual_mapping(path, "AIHUB-71748")


def test_target_prefix_collision_is_rejected(tmp_path: Path):
    rules = [
        {"source_prefix": "/one/", "target_prefix": "same/", "allowed_extensions": [".json"]},
        {"source_prefix": "/two/", "target_prefix": "same/nested/", "allowed_extensions": [".json"]},
    ]
    path = write_mapping(tmp_path / "mapping.yaml", rules=rules)

    with pytest.raises(SamplerError, match="target_prefix"):
        load_manual_mapping(path, "AIHUB-71748")


def test_entry_without_mapping_rule_is_rejected(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("/not-approved/file.json", "{}")])
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))

    assert result["samples_selected"] == 0
    assert rejected["rejected_entries"][0]["reason_code"] == "MAPPING_RULE_NOT_FOUND"


def test_rejection_observability_and_rule_statistics_are_exact(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [
        ("/approved/safe.json", "{}"),
        ("/approved/large.json", "12345"),
        ("/approved/note.txt", "x"),
        ("/unmatched/file.json", "{}"),
    ])
    rules = [{"source_prefix": "/approved/", "target_prefix": "mapped/", "allowed_extensions": [".json"]}]
    mapping = load_mapping(tmp_path, rules=rules)
    output = tmp_path / "analysis"

    result = run_manual(root, output, mapping, dry_run=True, max_file_bytes=4)
    final = output / "AIHUB-71748" / result["run_id"]
    manifest = read_manifest(output, result)
    summary = json.loads((final / "run-summary.json").read_text(encoding="utf-8"))
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))["rejected_entries"]
    stats = manifest["rule_statistics"][0]

    assert stats == summary["rule_statistics"][0]
    assert stats["matched_entries"] == 3
    assert stats["safe_entries"] == 1
    assert stats["rejected_entries"] == 2
    assert stats["entry_too_large"] == 1
    assert stats["unsupported_extension"] == 1
    assert stats["path_validation_failed"] == 0
    assert stats["selected_entries"] == 1
    assert manifest["unmatched_entries"] == 1
    assert manifest["unmatched_by_extension"] == {".json": 1}
    assert sum(manifest["unmatched_prefix_groups"].values()) == 1

    matched_rows = [row for row in rejected if row["mapping_matched"]]
    unmatched = next(row for row in rejected if not row["mapping_matched"])
    assert {row["rejection_stage"] for row in matched_rows} == {"size_validation", "extension_validation"}
    assert all(row["mapping_rule_id"] == stats["rule_id"] for row in matched_rows)
    assert all(row["source_prefix_hash"] for row in matched_rows)
    assert all(row["sanitized_source_prefix"] == "root/approved" for row in matched_rows)
    assert all(row["post_mapping_rejection"] is True for row in matched_rows)
    assert unmatched["mapping_rule_id"] is None
    assert unmatched["source_prefix_hash"] is None
    assert unmatched["sanitized_source_prefix"] is None
    assert unmatched["post_mapping_rejection"] is False
    assert unmatched["rejection_stage"] == "mapping_lookup"


def test_exact_prefix_and_boundary_are_enforced(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [
        ("/approved/file.json", "{}"),
        ("/approved-extra/file.json", "{}"),
    ])
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    manifest = read_manifest(output, result)

    assert result["samples_selected"] == 1
    assert manifest["samples"][0]["mapped_relative_path"] == "mapped/file.json"
    assert result["entries_rejected"] == 1


def test_traversal_is_rechecked_after_mapping(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("/approved/folder/../../escape.json", "{}")])
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))

    assert result["samples_selected"] == 0
    assert rejected["rejected_entries"][0]["reason_code"] == "PATH_TRAVERSAL"


def test_symlink_block_remains_active(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    info = zipfile.ZipInfo("/approved/link.json")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(root / "sample.zip", "w") as archive:
        archive.writestr(info, "target")
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))

    assert result["samples_selected"] == 0
    assert rejected["rejected_entries"][0]["reason_code"] == "SYMLINK_ENTRY"


def test_selection_is_deterministic_and_zip_order_independent(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir(); second_root.mkdir()
    entries = [("/approved/c.json", "c"), ("/approved/a.json", "a"), ("/approved/b.json", "b")]
    write_zip(first_root / "sample.zip", entries)
    write_zip(second_root / "sample.zip", list(reversed(entries)))
    mapping = load_mapping(tmp_path)

    first = run_manual(first_root, tmp_path / "out-one", mapping, dry_run=True, sample_count=2)
    second = run_manual(second_root, tmp_path / "out-two", mapping, dry_run=True, sample_count=2)
    first_samples = read_manifest(tmp_path / "out-one", first)["samples"]
    second_samples = read_manifest(tmp_path / "out-two", second)["samples"]

    assert [row["original_entry_name_hash"] for row in first_samples] == [
        row["original_entry_name_hash"] for row in second_samples
    ]
    assert [row["selection_rank"] for row in first_samples] == [row["selection_rank"] for row in second_samples]


def test_dry_run_creates_contract_artifacts_without_extracted_directory(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("/approved/file.json", "{}")])
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]

    assert result["samples_selected"] == 1
    assert result["samples_extracted"] == 0
    assert not (final / "extracted").exists()
    assert {path.name for path in final.iterdir()} == {
        "mapped-manifest.json", "mapping-validation.json", "rejected-entries.json",
        "schema-summary.json", "run-summary.json",
    }


def test_actual_limited_extraction_and_source_zip_invariance(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [
        ("/approved/one.json", '{"text":"합성 하나"}'),
        ("/approved/two.json", '{"text":"합성 둘"}'),
    ])
    before = sha256(root / "sample.zip")
    output = tmp_path / "analysis"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=False, sample_count=1)
    final = output / "AIHUB-71748" / result["run_id"]
    manifest = read_manifest(output, result)
    sample = manifest["samples"][0]
    extracted = final / Path(*sample["output_relative_path"].split("/"))

    assert result["samples_extracted"] == 1
    assert extracted.is_file() and not extracted.is_symlink()
    assert sample["entry_checksum"] == sample["output_checksum"]
    assert before == sha256(root / "sample.zip")
    assert manifest["source_mutation_detected"] is False


def test_mapping_fingerprint_changes_when_rule_changes(tmp_path: Path):
    first = load_manual_mapping(write_mapping(tmp_path / "one.yaml"), "AIHUB-71748")
    changed_rules = [{
        "source_prefix": "/approved/",
        "target_prefix": "changed/",
        "allowed_extensions": [".json", ".txt"],
    }]
    second = load_manual_mapping(write_mapping(tmp_path / "two.yaml", rules=changed_rules), "AIHUB-71748")

    assert first.fingerprint != second.fingerprint
    assert first.rules[0].rule_id != second.rules[0].rule_id


def test_reports_hide_local_absolute_and_original_entry_paths(tmp_path: Path):
    root = tmp_path / "external" / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    original_path = "/approved/private-folder/file.json"
    write_zip(root / "sample.zip", [(original_path, '{"text":"합성 비밀 원문"}')])
    output = tmp_path / "external" / "analysis" / "manual-samples"

    result = run_manual(root, output, load_mapping(tmp_path), dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in final.glob("*.json"))

    assert str(tmp_path) not in rendered
    assert original_path not in rendered
    assert "합성 비밀 원문" not in rendered
    assert "original_entry_name_hash" in rendered


def test_manual_output_root_is_isolated_from_default_samples_source_and_repo(tmp_path: Path):
    external = tmp_path / "external"
    source = external / "extracted" / "AIHUB-71748"
    source.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    config = AnalyzerConfig(external.resolve(), {"AIHUB-71748": dataset_entry(source)})

    assert manual_sample_output_root(config, None, repo) == (external / "analysis" / "manual-samples").resolve()
    with pytest.raises(SamplerError, match="manual-samples"):
        manual_sample_output_root(config, "analysis/samples", repo)
    with pytest.raises(SamplerError, match="원본 dataset"):
        manual_sample_output_root(config, source / "output", repo)


def test_cli_rejects_pending_mapping_without_creating_output(tmp_path: Path, monkeypatch, capsys):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    write_zip(root / "sample.zip", [("/approved/file.json", "{}")])
    dataset_config = tmp_path / "datasets.yaml"
    dataset_config.write_text(yaml.safe_dump({
        "datasets": {
            "external_root": str(external.resolve()).replace("\\", "/"),
            "entries": {"AIHUB-71748": {"root": "extracted/AIHUB-71748"}},
        }
    }), encoding="utf-8")
    pending = mapping_payload(approval={"status": "pending_user_review", "approved_by": None, "approved_at": None})
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(yaml.safe_dump(pending, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path / "repo")

    code = cli.main([
        "--config", str(dataset_config), "--dataset", "AIHUB-71748",
        "--manual-mapping", str(mapping_path), "--dry-run", "--json",
    ])
    captured = capsys.readouterr()

    assert code == 2
    assert "approved" in captured.err
    assert "Traceback" not in captured.err
    assert not (external / "analysis" / "manual-samples").exists()


def test_cli_approved_mapping_dry_run_uses_manual_output(tmp_path: Path, monkeypatch, capsys):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    write_zip(root / "sample.zip", [("/approved/file.json", "{}")])
    dataset_config = tmp_path / "datasets.yaml"
    dataset_config.write_text(yaml.safe_dump({
        "datasets": {
            "external_root": str(external.resolve()).replace("\\", "/"),
            "entries": {"AIHUB-71748": {"root": "extracted/AIHUB-71748"}},
        }
    }), encoding="utf-8")
    mapping_path = write_mapping(tmp_path / "mapping.yaml")
    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path / "repo")

    code = cli.main([
        "--config", str(dataset_config), "--dataset", "AIHUB-71748",
        "--manual-mapping", str(mapping_path), "--sample-count", "1", "--dry-run", "--json",
    ])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["manual_mapping"] is True
    assert result["samples_selected"] == 1
    assert result["samples_extracted"] == 0
    assert "Traceback" not in captured.err
    assert (external / "analysis" / "manual-samples" / "AIHUB-71748" / result["run_id"]).is_dir()
