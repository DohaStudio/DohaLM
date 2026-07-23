from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.datasets import analyze_aihub_dataset as cli
from scripts.datasets.analyzer import (
    AnalyzerError,
    DatasetEntry,
    analyze_dataset,
    detect_field_candidates,
    inspect_archives,
    inventory_dataset,
    load_dataset_config,
    profile_schema,
    profile_txt,
    render_markdown,
    safe_output_root,
    write_reports,
)


def entry(root: Path, dataset_id: str = "AIHUB-71748") -> DatasetEntry:
    return DatasetEntry(dataset_id, f"extracted/{dataset_id}", root)


def write_config(root: Path, dataset_root: Path, dataset_id: str = "AIHUB-71748") -> Path:
    relative = dataset_root.relative_to(root).as_posix()
    value = {
        "datasets": {
            "external_root": str(root.resolve()).replace("\\", "/"),
            "entries": {dataset_id: {"root": relative}},
        }
    }
    path = root / "local.yaml"
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_inventory_nested_korean_space_extensions_and_determinism(tmp_path: Path):
    root = tmp_path / "extracted" / "AIHUB-71748"
    nested = root / "Training 공간" / "한글경로"
    nested.mkdir(parents=True)
    (nested / "sample.json").write_text("{}", encoding="utf-8")
    (root / "Validation-data.txt").write_text("검증", encoding="utf-8")

    first = inventory_dataset(entry(root))
    second = inventory_dataset(entry(root))

    assert first == second
    assert first["directory_count"] == 2
    assert first["file_count"] == 2
    assert first["contains_korean_path"] is True
    assert first["contains_space_path"] is True
    assert first["training_candidates"] == ["Training 공간/한글경로/sample.json"]
    assert first["validation_candidates"] == ["Validation-data.txt"]
    assert {item["extension"] for item in first["extensions"]} == {".json", ".txt"}
    assert all(not Path(path).is_absolute() for row in first["extensions"] for path in row["representative_paths"])


def test_archive_inspector_reads_only_central_directory_and_handles_damage(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    with zipfile.ZipFile(root / "good.zip", "w") as archive:
        archive.writestr("Training/원천데이터/sample.json", '{"secret":"원문을 읽으면 안 됨"}')
        archive.writestr("Validation/라벨링데이터/labels.json", "{}")
        archive.writestr("../outside.json", "never exposed")
    (root / "broken.zip").write_bytes(b"not-a-zip")
    (root / "part.z01").write_bytes(b"split")

    report = inspect_archives(entry(root))
    rows = {item["archive_relative_path"]: item for item in report["archives"]}

    assert rows["good.zip"]["unsafe_entry_path_count"] == 1
    assert "../outside.json" not in rows["good.zip"]["representative_entry_paths"]
    assert "[unsafe-archive-entry-path]" in rows["good.zip"]["representative_entry_paths"]

    assert rows["good.zip"]["status"] == "ok"
    assert rows["good.zip"]["entry_count"] == 3
    assert rows["good.zip"]["training_entry_count"] == 1
    assert rows["good.zip"]["validation_entry_count"] == 1
    assert rows["broken.zip"]["status"] == "archive_read_failed"
    assert report["unsupported_archives"][0]["status"] == "unsupported_archive"
    assert report["unsupported_archives"][0]["split_archive_suspected"] is True
    assert "원문을 읽으면 안 됨" not in json.dumps(report, ensure_ascii=False)


def test_schema_profiler_json_array_jsonl_fields_and_no_values(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    secret = "문서에 절대 기록하지 않을 합성 원문"
    (root / "object.json").write_text(
        json.dumps({"content": secret, "label": "긍정", "name": "가상 이름"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "array.json").write_text(
        json.dumps([{"question": "합성 질문", "answer": "합성 답변"}, {"question": None}], ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "records.jsonl").write_text(
        '{"text":"합성 문장","metadata":{"speaker":"user"}}\n{bad}\n\n',
        encoding="utf-8",
    )

    profile = profile_schema(entry(root), sample_files=20, max_json_bytes=1024 * 1024)
    candidates = detect_field_candidates(profile)
    rendered = json.dumps(profile, ensure_ascii=False)

    assert secret not in rendered
    assert "합성 질문" not in rendered
    assert any(item["path"].endswith("content") for item in candidates["text_field_candidates"])
    assert any(item["path"].endswith("label") for item in candidates["label_metadata_candidates"])
    assert any(item["path"].endswith("name") for item in candidates["pii_field_warnings"])
    jsonl = next(item for item in profile["files"] if item["format"] == "jsonl")
    assert jsonl["parse_success"] == 1
    assert jsonl["parse_failure"] == 1
    assert jsonl["empty_lines"] == 1


def test_txt_profile_bom_statistics_and_invalid_utf8(tmp_path: Path):
    good = tmp_path / "good.txt"
    good.write_bytes(b"\xef\xbb\xbf" + "첫 줄 123\nSecond".encode("utf-8"))
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00")

    valid = profile_txt(good)
    invalid = profile_txt(bad)

    assert valid["strict_utf8_decode"] is True
    assert valid["bom"] is True
    assert valid["line_count"] == 2
    assert valid["script_counts"]["korean"] > 0
    assert invalid["strict_utf8_decode"] is False
    assert invalid["status"] == "manual_review_required"
    assert "CP949" not in json.dumps(invalid)


def test_large_json_is_skipped_without_reading(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "large.json").write_text(json.dumps({"text": "x" * 1000}), encoding="utf-8")

    profile = profile_schema(entry(root), sample_files=1, max_json_bytes=10)

    assert profile["files"][0]["skipped_reason"] == "file_exceeds_max_json_bytes"
    assert profile["fields"] == []


def test_analysis_report_has_no_absolute_path_or_source_text(tmp_path: Path):
    root = tmp_path / "external" / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    secret = "외부로 노출하면 안 되는 합성 원문"
    (root / "records.jsonl").write_text(json.dumps({"text": secret}, ensure_ascii=False) + "\n", encoding="utf-8")

    report = analyze_dataset(entry(root), sample_files=20, max_json_bytes=1024, inventory_only=False)
    output = tmp_path / "analysis"
    written = write_reports(report, output)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in written)

    assert report["source_mutation_detected"] is False
    assert str(tmp_path) not in combined
    assert secret not in combined
    assert "configured_locally" in combined
    assert render_markdown(report).startswith("# AIHUB-71748 구조 분석")
    assert {path.name for path in written} == {
        "inventory.json", "archive-inventory.json", "schema-profile.json",
        "text-field-candidates.json", "dataset-analysis.json", "dataset-analysis.md",
    }


def test_config_validation_and_output_safety(tmp_path: Path):
    external = tmp_path / "external"
    dataset = external / "extracted" / "AIHUB-71748"
    dataset.mkdir(parents=True)
    config = load_dataset_config(write_config(external, dataset))

    assert config.entries["AIHUB-71748"].root == dataset.resolve()
    assert safe_output_root(config, None, tmp_path / "different-repository") == (external / "analysis").resolve()
    with pytest.raises(AnalyzerError, match="원본 dataset"):
        safe_output_root(config, dataset / "analysis", tmp_path / "different-repository")
    with pytest.raises(AnalyzerError, match="Git 저장소 밖"):
        safe_output_root(config, tmp_path / "repo" / "artifacts", tmp_path / "repo")


def test_cli_inventory_json_contract_and_no_traceback(tmp_path: Path, monkeypatch, capsys):
    external = tmp_path / "external"
    dataset = external / "extracted" / "AIHUB-71748"
    dataset.mkdir(parents=True)
    with zipfile.ZipFile(dataset / "sample.zip", "w") as archive:
        archive.writestr("Training/sample.json", "{}")
    config = write_config(external, dataset)
    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path / "unrelated-repository")

    code = cli.main([
        "--config", str(config), "--dataset", "AIHUB-71748", "--inventory-only", "--json",
    ])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["success"] is True
    assert result["output_location"] == "external_analysis_root"
    assert result["datasets"][0]["file_count"] == 1
    assert "Traceback" not in captured.err
    assert str(external) not in captured.out
    assert (external / "analysis" / "AIHUB-71748" / "dataset-analysis.json").is_file()


def test_inventory_only_does_not_profile_text(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "text.txt").write_text("합성 문장", encoding="utf-8")

    report = analyze_dataset(entry(root), sample_files=20, max_json_bytes=1024, inventory_only=True)

    assert report["schema_profile"]["status"] == "not_run_inventory_only"
    assert report["field_candidates"]["text_field_candidates"] == []


def test_profile_without_direct_text_files_reports_explicit_status(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    with zipfile.ZipFile(root / "only.zip", "w") as archive:
        archive.writestr("Training/sample.json", "{}")

    report = analyze_dataset(entry(root), sample_files=20, max_json_bytes=1024, inventory_only=False)

    assert report["schema_profile"]["status"] == "no_direct_sample_files"
    assert report["approval"]["tokenizer"] == "pending"
