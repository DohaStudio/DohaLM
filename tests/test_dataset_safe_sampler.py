from __future__ import annotations

import hashlib
import json
import stat
import struct
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.datasets import safe_sampler
from scripts.datasets import sample_aihub_dataset as cli
from scripts.datasets.analyzer import AnalyzerConfig, DatasetEntry
from scripts.datasets.safe_sampler import (
    DEFAULT_EXTENSIONS,
    SamplerError,
    build_schema_summary,
    profile_delimited,
    safe_sample_output_root,
    sample_dataset,
    validate_entry,
    validate_entry_path,
)


def dataset_entry(root: Path) -> DatasetEntry:
    return DatasetEntry("AIHUB-71748", "extracted/AIHUB-71748", root)


def write_zip(path: Path, entries: list[tuple[str, str]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_sample(root: Path, output: Path, *, dry_run: bool, **overrides):
    values = {
        "requested_archive": None,
        "sample_count": 20,
        "max_file_bytes": 5 * 1024 * 1024,
        "max_total_bytes": 50 * 1024 * 1024,
        "allowed_extensions": DEFAULT_EXTENSIONS,
        "dry_run": dry_run,
    }
    values.update(overrides)
    return sample_dataset(dataset_entry(root), output, **values)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("/etc/passwd", "ABSOLUTE_ENTRY_PATH"),
        ("\\Windows\\System32\\file.txt", "ABSOLUTE_ENTRY_PATH"),
        ("C:\\temp\\file.json", "WINDOWS_DRIVE_PATH"),
        ("//server/share/file.txt", "UNC_PATH"),
        ("\\\\server\\share\\file.txt", "UNC_PATH"),
        ("../../file.json", "PATH_TRAVERSAL"),
        ("folder\\..\\..\\file.json", "PATH_TRAVERSAL"),
        ("folder/../../file.json", "PATH_TRAVERSAL"),
        ("bad\x00name.json", "NUL_IN_ENTRY_NAME"),
        ("", "EMPTY_ENTRY_NAME"),
    ],
)
def test_entry_path_rejects_absolute_drive_unc_traversal_nul_and_empty(tmp_path: Path, name: str, reason: str):
    decision = validate_entry_path(name, tmp_path / "output")

    assert decision.reason_code == reason
    assert decision.safe_path is None


def test_entry_path_accepts_relative_and_rejects_long_path(tmp_path: Path):
    accepted = validate_entry_path("Training/한글 공간/file.json", tmp_path / "output")
    rejected = validate_entry_path("a" * 241 + ".json", tmp_path / "output")

    assert accepted.safe_path == "Training/한글 공간/file.json"
    assert rejected.reason_code == "ENTRY_PATH_TOO_LONG"


def test_entry_kind_extension_size_encryption_and_temporary_filters(tmp_path: Path):
    output = tmp_path / "output"
    allowed = frozenset(DEFAULT_EXTENSIONS)

    symlink = zipfile.ZipInfo("link.json")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    device = zipfile.ZipInfo("device.json")
    device.external_attr = (stat.S_IFCHR | 0o600) << 16
    hardlink = zipfile.ZipInfo("hardlink.json")
    hardlink.external_attr = (stat.S_IFREG | 0o600) << 16
    hardlink.extra = struct.pack("<HH", 0x000D, 13) + b"x" * 13
    encrypted = zipfile.ZipInfo("secret.json")
    encrypted.flag_bits = 0x1
    too_large = zipfile.ZipInfo("large.json")
    too_large.file_size = 101
    unsupported = zipfile.ZipInfo("audio.wav")
    unsupported.file_size = 1
    temporary = zipfile.ZipInfo(".hidden.json")
    temporary.file_size = 1

    assert validate_entry(symlink, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "SYMLINK_ENTRY"
    assert validate_entry(device, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "DEVICE_ENTRY"
    assert validate_entry(hardlink, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "HARDLINK_ENTRY"
    assert validate_entry(encrypted, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "ENCRYPTED_ENTRY"
    assert validate_entry(too_large, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "ENTRY_TOO_LARGE"
    assert validate_entry(unsupported, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "UNSUPPORTED_EXTENSION"
    assert validate_entry(temporary, output, allowed_extensions=allowed, max_file_bytes=100).reason_code == "TEMPORARY_ENTRY"


def test_dry_run_classifies_partial_archive_and_extracts_nothing(tmp_path: Path):
    root = tmp_path / "external" / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    write_zip(root / "mixed.zip", [
        ("Training/safe.json", '{"text":"합성 원문"}'),
        ("/Training/unsafe.json", "{}"),
        ("audio.wav", "binary-like"),
    ])

    result = run_sample(root, tmp_path / "analysis" / "samples", dry_run=True, sample_count=1)
    final = tmp_path / "analysis" / "samples" / "AIHUB-71748" / result["run_id"]
    manifest = json.loads((final / "sample-manifest.json").read_text(encoding="utf-8"))

    assert result["archives_partially_safe"] == 1
    assert result["samples_selected"] == 1
    assert result["samples_extracted"] == 0
    assert manifest["samples"][0]["entry_checksum"] is None
    assert not (final / "extracted").exists()


def test_actual_sampling_extracts_namespaced_files_and_verifies_checksums(tmp_path: Path):
    root = tmp_path / "external" / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    write_zip(root / "one.zip", [("Training/sample.json", '{"text":"합성 A"}')])
    write_zip(root / "two.zip", [("Training/sample.json", '{"text":"합성 B"}')])
    before = {path.name: sha256(path) for path in root.glob("*.zip")}

    result = run_sample(root, tmp_path / "analysis" / "samples", dry_run=False, sample_count=2)
    final = tmp_path / "analysis" / "samples" / "AIHUB-71748" / result["run_id"]
    manifest = json.loads((final / "sample-manifest.json").read_text(encoding="utf-8"))
    outputs = [final / Path(*PurePath(item["output_relative_path"]).parts) for item in manifest["samples"]]

    assert result["samples_extracted"] == 2
    assert len({item["output_relative_path"] for item in manifest["samples"]}) == 2
    assert all(path.is_file() and not path.is_symlink() for path in outputs)
    assert all(item["entry_checksum"] == item["output_checksum"] for item in manifest["samples"])
    assert before == {path.name: sha256(path) for path in root.glob("*.zip")}


def PurePath(value: str) -> Path:
    return Path(*value.split("/"))


def test_duplicate_output_path_is_rejected(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(root / "duplicate.zip", "w") as archive:
            archive.writestr("same.json", "{}")
            archive.writestr("same.json", "{\"text\":\"second\"}")

    result = run_sample(root, tmp_path / "analysis", dry_run=True, sample_count=2)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))["rejected_entries"]

    assert result["samples_selected"] == 1
    assert any(item["reason_code"] == "DUPLICATE_OUTPUT_PATH" for item in rejected)


def test_total_byte_limit_rejects_candidate(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("a.json", "12345"), ("b.json", "67890")])

    result = run_sample(root, tmp_path / "analysis", dry_run=True, sample_count=2, max_total_bytes=5)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))["rejected_entries"]

    assert result["samples_selected"] == 1
    assert any(item["reason_code"] == "TOTAL_LIMIT_EXCEEDED" for item in rejected)


def test_deterministic_selection_is_archive_order_independent(tmp_path: Path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir(); two.mkdir()
    entries = [("z.json", "z"), ("a.json", "a"), ("m.txt", "m")]
    write_zip(one / "sample.zip", entries)
    write_zip(two / "sample.zip", list(reversed(entries)))

    first = run_sample(one, tmp_path / "analysis-one", dry_run=True, sample_count=2)
    second = run_sample(two, tmp_path / "analysis-two", dry_run=True, sample_count=2)
    first_manifest = json.loads((tmp_path / "analysis-one" / "AIHUB-71748" / first["run_id"] / "sample-manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((tmp_path / "analysis-two" / "AIHUB-71748" / second["run_id"] / "sample-manifest.json").read_text(encoding="utf-8"))

    assert [item["entry_relative_path"] for item in first_manifest["samples"]] == [
        item["entry_relative_path"] for item in second_manifest["samples"]
    ]
    assert [item["selection_rank"] for item in first_manifest["samples"]] == [
        item["selection_rank"] for item in second_manifest["samples"]
    ]
    # ZIP byte layout와 metadata digest가 다르면 run fingerprint는 달라질 수 있다.


def test_corrupted_zip_is_reported_without_traceback_or_extraction(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "broken.zip").write_bytes(b"not a zip")

    result = run_sample(root, tmp_path / "analysis", dry_run=True)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))["rejected_entries"]

    assert result["run_status"] == "manual_review_required"
    assert any(item["reason_code"] == "CORRUPTED_ENTRY" for item in rejected)
    assert not (final / "extracted").exists()


def test_unsupported_zip_compression_is_classified_without_reading_content(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    archive_path = root / "unsupported.zip"
    write_zip(archive_path, [("sample.json", "{}")])
    payload = bytearray(archive_path.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    struct.pack_into("<H", payload, local + 8, 99)
    struct.pack_into("<H", payload, central + 10, 99)
    archive_path.write_bytes(payload)

    result = run_sample(root, tmp_path / "analysis", dry_run=True)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    rejected = json.loads((final / "rejected-entries.json").read_text(encoding="utf-8"))["rejected_entries"]

    assert result["archives_unsupported"] == 1
    assert result["samples_selected"] == 0
    assert rejected[0]["reason_code"] == "UNSUPPORTED_ARCHIVE"


def test_atomic_publish_refuses_overwrite(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("sample.json", "{}")])
    output = tmp_path / "analysis"

    run_sample(root, output, dry_run=True)

    with pytest.raises(SamplerError, match="덮어쓰지"):
        run_sample(root, output, dry_run=True)


def test_failure_removes_staging_and_leaves_no_final(tmp_path: Path, monkeypatch):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "sample.zip", [("sample.json", "{}")])
    output = tmp_path / "analysis"

    monkeypatch.setattr(safe_sampler, "_extract_candidate", lambda *_: (_ for _ in ()).throw(SamplerError("injected")))

    with pytest.raises(SamplerError, match="injected"):
        run_sample(root, output, dry_run=False)
    dataset_output = output / "AIHUB-71748"
    assert not dataset_output.exists() or list(dataset_output.iterdir()) == []


def test_manifest_hides_dangerous_paths_absolute_roots_and_source_text(tmp_path: Path):
    root = tmp_path / "external" / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    secret = "문서나 manifest에 출력하면 안 되는 합성 원문"
    write_zip(root / "sample.zip", [("/private/secret.json", secret)])

    result = run_sample(root, tmp_path / "analysis", dry_run=True)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in final.glob("*.json"))

    assert "/private/secret.json" not in combined
    assert secret not in combined
    assert str(tmp_path) not in combined
    assert "configured_external_root" in combined
    assert "ABSOLUTE_ENTRY_PATH" in combined


def test_manual_review_report_is_created_when_all_candidates_are_unsafe(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    write_zip(root / "unsafe.zip", [("/Training/a.json", "{}"), ("/Validation/b.txt", "text")])

    result = run_sample(root, tmp_path / "analysis", dry_run=True)
    final = tmp_path / "analysis" / "AIHUB-71748" / result["run_id"]
    report = json.loads((final / "manual-review-required.json").read_text(encoding="utf-8"))

    assert result["entries_safe"] == 0
    assert result["samples_selected"] == 0
    assert report["unsafe_entry_count"] == 2
    assert report["automatic_normalization_prohibited"] is True
    assert set(report["sanitized_prefix_examples"]) == {"root/Training", "root/Validation"}
    assert "/Training/a.json" not in json.dumps(report, ensure_ascii=False)


def test_csv_tsv_schema_summary_records_headers_types_and_no_values(tmp_path: Path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    secret = "합성 셀 원문 비밀"
    (extracted / "sample.csv").write_text(f"text,label,name\n{secret},positive,person\n", encoding="utf-8")
    (extracted / "sample.tsv").write_text("content\tscore\n문장\t1\n", encoding="utf-8")

    csv_profile = profile_delimited(extracted / "sample.csv", delimiter=",")
    summary = build_schema_summary(extracted, "AIHUB-71748", 20, 1024 * 1024)
    rendered = json.dumps(summary, ensure_ascii=False)

    assert csv_profile["header_candidates"] == ["text", "label", "name"]
    assert csv_profile["rows_sampled"] == 1
    assert "text" in csv_profile["text_field_candidates"]
    assert "label" in csv_profile["label_field_candidates"]
    assert "name" in csv_profile["pii_field_name_warnings"]
    assert secret not in rendered
    assert summary["extension_counts"] == {".csv": 1, ".tsv": 1}


def test_output_root_must_be_external_analysis_and_not_source_or_repo(tmp_path: Path):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    config = AnalyzerConfig(external.resolve(), {"AIHUB-71748": dataset_entry(root)})
    repo = tmp_path / "repo"
    repo.mkdir()

    assert safe_sample_output_root(config, None, repo) == (external / "analysis" / "samples").resolve()
    with pytest.raises(SamplerError, match="analysis 아래"):
        safe_sample_output_root(config, tmp_path / "elsewhere", repo)
    with pytest.raises(SamplerError, match="원본 dataset"):
        safe_sample_output_root(config, root / "samples", repo)


def test_cli_json_dry_run_contract(tmp_path: Path, monkeypatch, capsys):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    write_zip(root / "sample.zip", [("safe.json", "{}")])
    config_path = tmp_path / "local.yaml"
    config_path.write_text(yaml.safe_dump({
        "datasets": {
            "external_root": str(external.resolve()).replace("\\", "/"),
            "entries": {"AIHUB-71748": {"root": "extracted/AIHUB-71748"}},
        }
    }), encoding="utf-8")
    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path / "repo")

    code = cli.main([
        "--config", str(config_path), "--dataset", "AIHUB-71748",
        "--sample-count", "1", "--dry-run", "--json",
    ])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["dry_run"] is True
    assert result["samples_selected"] == 1
    assert result["samples_extracted"] == 0
    assert "Traceback" not in captured.err
    assert str(external) not in captured.out
