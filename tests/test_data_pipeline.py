from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.data.checksums import file_checksum
from src.data.errors import DataPipelineError
from src.data.pipeline import build_pipeline, validate_pipeline
import src.data.pipeline as pipeline_module


def write_config(root: Path, *, version="v1", inputs=None, output_dir="output", license_status="approved", approval_status="approved", pii_status="clear") -> Path:
    value = {"data": {
        "dataset_id": "fixture-dataset", "dataset_version": version, "input_paths": inputs or ["input"],
        "allowed_formats": [".txt", ".jsonl"], "output_dir": output_dir, "encoding": "utf-8",
        "unicode_normalization": "NFC", "max_text_chars": 1_000_000, "metadata_max_depth": 5,
        "reject_unknown_fields": True, "write_empty_split_files": True, "checksum_algorithm": "sha256",
        "split": {"seed": 42, "train_ratio": .8, "validation_ratio": .1, "test_ratio": .1, "ratio_tolerance": 1e-9},
        "source": {"license_status": license_status, "approval_status": approval_status, "pii_status": pii_status},
    }}
    path = root / f"config-{version}.yaml"
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def make_input(root: Path) -> dict[str, str]:
    folder = root / "input"; folder.mkdir()
    (folder / "note.txt").write_text("합성 TXT 문장입니다.\r\n둘째 줄입니다.  \n", encoding="utf-8", newline="")
    records = [
        {"id": f"id-{index}", "text": f"합성 문장 {index}입니다.", "source": "fixture-dataset", "group_id": f"group-{index}"}
        for index in range(12)
    ]
    records += [
        {"id": "empty", "text": "   ", "source": "fixture-dataset"},
        {"id": "normalized-duplicate", "text": "합성 문장 1입니다.", "source": "fixture-dataset", "group_id": "other"},
        {"id": "duplicate-id", "text": "A", "source": "fixture-dataset"},
        {"id": "duplicate-id", "text": "B", "source": "fixture-dataset"},
    ]
    with (folder / "records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {path.name: file_checksum(path) for path in folder.iterdir()}


def test_validate_is_dry_and_build_writes_ten_consistent_artifacts(tmp_path: Path):
    before = make_input(tmp_path); config = write_config(tmp_path)
    dry = validate_pipeline(config, root=tmp_path)
    assert dry.output_dir is None and not (tmp_path / "output").exists()
    result = build_pipeline(config, root=tmp_path)
    output = result.output_dir
    assert output is not None and len(list(output.iterdir())) == 10
    assert before == {path.name: file_checksum(path) for path in (tmp_path / "input").iterdir()}
    manifest = json.loads((output / "source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_count"] == manifest["accepted_count"] + manifest["rejected_count"] + manifest["duplicate_count"]
    assert sum(manifest["split_counts"].values()) == manifest["accepted_count"]
    assert manifest["duplicate_count"] == 1 and manifest["rejected_count"] == 2
    rejection_codes = {json.loads(line)["reason_code"] for line in (output / "rejections.jsonl").read_text(encoding="utf-8").splitlines()}
    duplicate_types = {json.loads(line)["duplicate_type"] for line in (output / "duplicates.jsonl").read_text(encoding="utf-8").splitlines()}
    assert rejection_codes == {"EMPTY_TEXT", "DUPLICATE_RECORD_ID"}
    assert duplicate_types == {"NORMALIZED_TEXT_DUPLICATE"}
    assert (output / "validation.jsonl").exists() and (output / "test.jsonl").exists()
    assert all(not Path(item["relative_path"]).is_absolute() for item in manifest["artifacts"])
    for name in ("records.jsonl", "train.jsonl", "validation.jsonl", "test.jsonl", "rejections.jsonl", "duplicates.jsonl"):
        content = (output / name).read_bytes()
        assert b"\r" not in content and (not content or (content.endswith(b"\n") and not content.endswith(b"\n\n")))
    record_ids = [json.loads(line)["record_id"] for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert record_ids == sorted(record_ids)
    assert sum(item["record_count"] for item in manifest["sources"]) == manifest["record_count"]
    for artifact in manifest["artifacts"]:
        assert file_checksum(output / artifact["relative_path"]) == artifact["checksum"]
    assert all(str(tmp_path) not in path.read_text(encoding="utf-8") for path in output.iterdir())
    with pytest.raises(DataPipelineError, match="ARTIFACT_WRITE_ERROR"):
        build_pipeline(config, root=tmp_path)


def test_deterministic_content_with_input_order_change(tmp_path: Path):
    first_root = tmp_path / "run-one"; second_root = tmp_path / "run-two"
    first_root.mkdir(); second_root.mkdir()
    make_input(first_root); make_input(second_root)
    one = build_pipeline(write_config(first_root, inputs=["input/note.txt", "input/records.jsonl"]), root=first_root)
    two = build_pipeline(write_config(second_root, inputs=["input/records.jsonl", "input/note.txt"]), root=second_root)
    for name in ("records.jsonl", "train.jsonl", "validation.jsonl", "test.jsonl", "statistics.json"):
        assert (one.output_dir / name).read_bytes() == (two.output_dir / name).read_bytes()
    assert one.dataset_fingerprint == two.dataset_fingerprint
    first_lineage = json.loads((one.output_dir / "lineage.json").read_text(encoding="utf-8"))
    second_lineage = json.loads((two.output_dir / "lineage.json").read_text(encoding="utf-8"))
    for field in ("dataset_fingerprint", "git_sha", "resolved_config_checksum", "input_artifacts", "processing_steps"):
        assert first_lineage[field] == second_lineage[field]
    first_outputs = [item for item in first_lineage["output_artifacts"] if item["artifact_type"] != "rejections"]
    second_outputs = [item for item in second_lineage["output_artifacts"] if item["artifact_type"] != "rejections"]
    assert first_outputs == second_outputs


@pytest.mark.parametrize("field,value,code", [
    ("license_status", "unknown", "UNAPPROVED_LICENSE"),
    ("approval_status", "pending", "UNAPPROVED_SOURCE"),
    ("pii_status", "suspected", "PII_NOT_CLEAR"),
])
def test_source_approval_blocks_entire_pipeline(tmp_path: Path, field: str, value: str, code: str):
    make_input(tmp_path)
    kwargs = {field: value}
    with pytest.raises(DataPipelineError, match=code):
        validate_pipeline(write_config(tmp_path, **kwargs), root=tmp_path)


def test_all_rejected_does_not_publish(tmp_path: Path):
    folder = tmp_path / "input"; folder.mkdir()
    (folder / "bad.jsonl").write_text('{"id":"bad","text":" ","source":"fixture-dataset"}\n', encoding="utf-8")
    with pytest.raises(DataPipelineError, match="MANIFEST_MISMATCH"):
        build_pipeline(write_config(tmp_path), root=tmp_path)
    assert not (tmp_path / "output" / "fixture-dataset" / "v1").exists()


def test_artifact_failure_cleans_staging_and_never_publishes(tmp_path: Path, monkeypatch):
    make_input(tmp_path); config = write_config(tmp_path)
    def fail_write(*args, **kwargs):
        raise DataPipelineError(pipeline_module.DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "injected"))
    monkeypatch.setattr(pipeline_module, "write_jsonl", fail_write)
    with pytest.raises(DataPipelineError, match="ARTIFACT_WRITE_ERROR"):
        build_pipeline(config, root=tmp_path)
    parent = tmp_path / "output" / "fixture-dataset"
    assert not (parent / "v1").exists()
    assert not list(parent.glob(".v1.staging-*"))


def test_detects_raw_file_mutation_before_publish(tmp_path: Path, monkeypatch):
    make_input(tmp_path); config = write_config(tmp_path)
    original = pipeline_module.discover_inputs
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        values = original(*args, **kwargs)
        if calls == 2:
            first = values[0]
            values[0] = type(first)(first.path, first.relative_path, first.format, first.size_bytes, "sha256:" + "0" * 64)
        return values
    monkeypatch.setattr(pipeline_module, "discover_inputs", changed)
    with pytest.raises(DataPipelineError, match="RAW_FILE_MUTATED"):
        validate_pipeline(config, root=tmp_path)
