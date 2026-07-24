from __future__ import annotations

import hashlib
import io
import json
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import yaml

from scripts.datasets import large_json_inspector
from scripts.datasets.analyzer import AnalyzerConfig, DatasetEntry
from scripts.datasets.large_json_inspector import (
    inspect_large_json_entries,
    inspect_stream_prefix,
    large_json_output_root,
)
from scripts.datasets.manual_path_mapping import load_manual_mapping
from scripts.datasets.manual_prefix_inspector import (
    _candidate_comparisons,
    _component_profile,
    inspect_manual_prefixes,
    manual_prefix_output_root,
)
from scripts.datasets.safe_sampler import _sha256_text

class TrackingStream(io.BytesIO):
    def __init__(self, value: bytes):
        super().__init__(value)
        self.requests: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        return super().read(size)


def dataset_entry(root: Path) -> DatasetEntry:
    return DatasetEntry("AIHUB-71748", "extracted/AIHUB-71748", root)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_mapping(path: Path, *, rules: list[dict[str, object]] | None = None) -> Path:
    payload = {
        "schema_version": "1.0",
        "dataset_id": "AIHUB-71748",
        "approval": {
            "status": "approved",
            "approved_by": "test-reviewer",
            "approved_at": "2026-07-24T00:00:00+09:00",
        },
        "rules": rules or [{
            "source_prefix": "/approved/",
            "target_prefix": "mapped/",
            "allowed_extensions": [".json"],
        }],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_stream_reader_never_reads_entire_entry_and_respects_limit():
    stream = TrackingStream(b'{"text":"' + b"x" * 4096 + b'"}')

    result = inspect_stream_prefix(stream, max_read_bytes=128)

    assert result["bytes_read"] == 128
    assert result["truncated"] is True
    assert all(0 < request <= large_json_inspector.READ_CHUNK_BYTES for request in stream.requests)
    assert -1 not in stream.requests


def test_truncated_object_and_array_are_detected():
    object_result = inspect_stream_prefix(io.BytesIO(b'{"text":{"nested":1}}'), max_read_bytes=10)
    array_result = inspect_stream_prefix(io.BytesIO(b'[{"content":1},{"content":2}]'), max_read_bytes=12)

    assert object_result["json_root_type_candidate"] == "object"
    assert object_result["parse_completeness"] == "truncated"
    assert object_result["lexical_depth_at_limit"] > 0
    assert array_result["json_root_type_candidate"] == "array"
    assert array_result["parse_completeness"] == "truncated"


def test_top_level_keys_are_hashed_and_only_allowlisted_names_are_shown():
    secret_value = "원문 값은 출력되면 안 됨"
    payload = json.dumps({"text": secret_value, "private_key": "hidden"}, ensure_ascii=False).encode("utf-8")

    result = inspect_stream_prefix(io.BytesIO(payload), max_read_bytes=len(payload))
    rendered = json.dumps(result, ensure_ascii=False)
    rows = {row["key_name_hash"]: row for row in result["top_level_key_candidates"]}

    assert rows[_sha256_text("text")]["sanitized_name"] == "text"
    assert rows[_sha256_text("private_key")]["sanitized_name"] is None
    assert "private_key" not in rendered
    assert secret_value not in rendered


def test_invalid_utf8_bom_and_jsonl_candidates():
    invalid = inspect_stream_prefix(io.BytesIO(b'{"text":"\xff"}'), max_read_bytes=64)
    bom_payload = b"\xef\xbb\xbf" + b'{"text":1}'
    bom = inspect_stream_prefix(io.BytesIO(bom_payload), max_read_bytes=len(bom_payload))
    jsonl_payload = b'{"text":"a"}\n{"text":"b"}\n'
    jsonl = inspect_stream_prefix(io.BytesIO(jsonl_payload), max_read_bytes=len(jsonl_payload))

    assert invalid["utf8_decode_status"] == "invalid_utf8"
    assert invalid["parse_completeness"] == "invalid_utf8"
    assert bom["utf8_bom"] is True
    assert bom["json_root_type_candidate"] == "object"
    assert jsonl["json_lines_candidate"] is True


def test_large_json_inspection_is_limited_private_and_source_invariant(tmp_path: Path, monkeypatch):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    archive_path = root / "sample.zip"
    secret = "합성 원문 비밀값"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("/approved/large.json", json.dumps({"text": secret, "unknown_key": "x"}, ensure_ascii=False))
    before = sha256(archive_path)
    mapping = load_manual_mapping(write_mapping(tmp_path / "mapping.yaml"), "AIHUB-71748")
    monkeypatch.setattr(large_json_inspector, "DEFAULT_LARGE_THRESHOLD_BYTES", 16)
    output = external / "analysis" / "large-json-inspection"

    result = inspect_large_json_entries(
        dataset_entry(root), output, mapping, requested_archive=None,
        max_entries=1, max_read_bytes=32, max_total_read_bytes=32, dry_run=True,
    )
    final = output / "AIHUB-71748" / result["run_id"]
    report = json.loads((final / "large-json-inspection.json").read_text(encoding="utf-8"))
    rendered = json.dumps(report, ensure_ascii=False)

    assert result["inspected_count"] == 1
    assert result["total_bytes_read"] <= 32
    assert report["full_entry_extraction_performed"] is False
    assert not (final / "extracted").exists()
    assert str(tmp_path) not in rendered
    assert secret not in rendered
    assert "/approved/large.json" not in rendered
    assert before == sha256(archive_path)
    assert report["source_mutation_detected"] is False


def test_large_json_inspection_respects_total_read_limit(tmp_path: Path, monkeypatch):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    with zipfile.ZipFile(root / "sample.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("/approved/one.json", '[{"text":"' + "a" * 128 + '"}]')
        archive.writestr("/approved/two.json", '[{"text":"' + "b" * 128 + '"}]')
    mapping = load_manual_mapping(write_mapping(tmp_path / "mapping.yaml"), "AIHUB-71748")
    monkeypatch.setattr(large_json_inspector, "DEFAULT_LARGE_THRESHOLD_BYTES", 16)
    output = external / "analysis" / "large-json-inspection"

    result = inspect_large_json_entries(
        dataset_entry(root), output, mapping, requested_archive=None,
        max_entries=2, max_read_bytes=32, max_total_read_bytes=40, dry_run=True,
    )
    report = json.loads((
        output / "AIHUB-71748" / result["run_id"] / "large-json-inspection.json"
    ).read_text(encoding="utf-8"))

    assert result["inspected_count"] == 2
    assert result["total_bytes_read"] == 40
    assert [row["bytes_read"] for row in report["inspections"]] == [32, 8]


def test_prefix_unicode_normalization_and_dash_difference_are_non_disclosing(tmp_path: Path):
    candidate = "RaG-데이터"
    nfd_component = unicodedata.normalize("NFD", candidate)
    nfd_profile = _component_profile(nfd_component, 2, Counter({".json": 2}))
    dash_component = "RaG–데이터"
    dash_profile = _component_profile(dash_component, 3, Counter({".json": 3}))
    mapping = load_manual_mapping(write_mapping(
        tmp_path / "mapping.yaml",
        rules=[{"source_prefix": "/RaG-데이터/", "target_prefix": "rag/", "allowed_extensions": [".json"]}],
    ), "AIHUB-71748")
    comparisons = _candidate_comparisons(dash_component, dash_profile, mapping)

    assert nfd_profile["unicode_normalization"]["nfc_changes_original"] is True
    assert nfd_profile["first_component_hash"] != _sha256_text(candidate)
    assert dash_profile["has_dash"] is True
    assert dash_profile["sanitized_preview"] == "root/RaG-데이터"
    assert comparisons[0]["exact_match"] is False
    assert comparisons[0]["observed_component_hash"] != comparisons[0]["source_prefix_hash"]
    assert dash_component not in json.dumps(comparisons, ensure_ascii=False)


def test_prefix_review_records_hash_statistics_only_and_preserves_zip(tmp_path: Path):
    external = tmp_path / "external"
    root = external / "extracted" / "AIHUB-71748"
    root.mkdir(parents=True)
    archive_path = root / "sample.zip"
    component = "RaG–데이터"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"/{component}/one.json", "{}")
        archive.writestr(f"/{component}/two.txt", "text")
    before = sha256(archive_path)
    mapping = load_manual_mapping(write_mapping(
        tmp_path / "mapping.yaml",
        rules=[{"source_prefix": "/RaG-데이터/", "target_prefix": "rag/", "allowed_extensions": [".json"]}],
    ), "AIHUB-71748")
    output = external / "analysis" / "manual-prefix-review"

    result = inspect_manual_prefixes(dataset_entry(root), output, mapping, requested_archive=None, dry_run=True)
    final = output / "AIHUB-71748" / result["run_id"]
    report = json.loads((final / "prefix-summary.json").read_text(encoding="utf-8"))
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["entries_grouped"] == 2
    assert report["prefix_groups"][0]["entry_count"] == 2
    assert report["prefix_groups"][0]["extension_distribution"] == {".json": 1, ".txt": 1}
    assert report["mapping_candidate_comparisons"][0]["exact_match"] is False
    assert component not in rendered
    assert str(tmp_path) not in rendered
    assert before == sha256(archive_path)
    assert report["source_mutation_detected"] is False


def test_inspection_output_roots_are_external_and_isolated(tmp_path: Path):
    external = tmp_path / "external"
    source = external / "extracted" / "AIHUB-71748"
    source.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    config = AnalyzerConfig(external.resolve(), {"AIHUB-71748": dataset_entry(source)})

    assert large_json_output_root(config, None, repo) == (external / "analysis" / "large-json-inspection").resolve()
    assert manual_prefix_output_root(config, None, repo) == (external / "analysis" / "manual-prefix-review").resolve()
