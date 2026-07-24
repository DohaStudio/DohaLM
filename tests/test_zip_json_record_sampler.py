from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.datasets import json_record_stream, zip_json_record_sampler
from scripts.datasets.analyzer import DatasetEntry
from scripts.datasets.json_record_stream import (
    ENTRY_READ_LIMIT_REACHED,
    INVALID_UTF8,
    MALFORMED_JSON_STRUCTURE,
    RECORD_OK,
    RECORD_PARSE_FAILED,
    RECORD_TOO_LARGE,
    ROOT_NOT_ARRAY,
    scan_json_array_records,
)
from scripts.datasets.manual_path_mapping import load_manual_mapping
from scripts.datasets.zip_json_record_sampler import analyze_record, sample_zip_json_records


class TrackingStream(io.BytesIO):
    def __init__(self, value: bytes):
        super().__init__(value)
        self.requests: list[int] = []

    def read(self, size: int = -1) -> bytes:
        assert size >= 0, "전체 read 호출은 허용되지 않습니다."
        self.requests.append(size)
        return super().read(size)


def scan(value: bytes, *, max_record_bytes: int = 1024 * 1024, max_read_bytes: int | None = None):
    events = []
    source = TrackingStream(value)
    result = scan_json_array_records(
        source,
        max_record_bytes=max_record_bytes,
        max_read_bytes=max_read_bytes or len(value) + 1,
        on_record=events.append,
    )
    return result, events, source


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


def write_zip(path: Path, content: str, *, entry_name: str = "/approved/large.json") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, content)


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    *,
    dry_run: bool = False,
    max_entries: int = 1,
    records_per_entry: int = 2,
    max_record_bytes: int = 1024 * 1024,
    max_read_bytes_per_entry: int = 1024 * 1024,
    max_total_read_bytes: int = 1024 * 1024,
    output_name: str = "output",
):
    root = tmp_path / "dataset"
    root.mkdir(exist_ok=True)
    archive_path = root / "sample.zip"
    if not archive_path.exists():
        write_zip(archive_path, content)
    mapping = load_manual_mapping(write_mapping(tmp_path / "mapping.yaml"), "AIHUB-71748")
    monkeypatch.setattr(zip_json_record_sampler, "DEFAULT_LARGE_THRESHOLD_BYTES", 0)
    result = sample_zip_json_records(
        DatasetEntry("AIHUB-71748", "dataset", root),
        tmp_path / output_name,
        mapping,
        requested_archive=None,
        max_entries=max_entries,
        records_per_entry=records_per_entry,
        max_record_bytes=max_record_bytes,
        max_read_bytes_per_entry=max_read_bytes_per_entry,
        max_total_read_bytes=max_total_read_bytes,
        dry_run=dry_run,
    )
    run_root = tmp_path / output_name / "AIHUB-71748" / result["run_id"]
    return result, run_root, archive_path


def test_simple_object_array_and_nested_structures():
    result, events, _ = scan(b'[{"text":"a"},{"nested":{"items":[1,2]}}]')
    assert result.status == RECORD_OK
    assert [event.record_type for event in events] == ["object", "object"]
    assert events[1].value == {"nested": {"items": [1, 2]}}


@pytest.mark.parametrize(
    "payload",
    [
        '[{"text":"a,b"},{"text":"ok"}]',
        '[{"text":"{x}[y]"},{"text":"ok"}]',
        '[{"text":"a\\\"b"},{"text":"ok"}]',
        '[{"text":"\\uD55C\\uAE00"},{"text":"ok"}]',
        '[[1,{"nested":[2,3]}],{"text":"ok"}]',
    ],
)
def test_string_and_nested_delimiters_do_not_split_records(payload: str):
    result, events, _ = scan(payload.encode("utf-8"))
    assert result.status == RECORD_OK
    assert len(events) == 2
    assert all(event.status == RECORD_OK for event in events)


def test_utf8_multibyte_character_can_cross_chunk_boundary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(json_record_stream, "READ_CHUNK_BYTES", 2)
    result, events, source = scan('[{"text":"가나다"}]'.encode("utf-8"))
    assert result.status == RECORD_OK
    assert events[0].value == {"text": "가나다"}
    assert max(source.requests) == 2


def test_root_not_array_and_invalid_utf8_have_explicit_status():
    root_result, _, _ = scan(b'{"text":"x"}')
    utf8_result, _, _ = scan(b'["\xff"]')
    assert root_result.status == ROOT_NOT_ARRAY
    assert utf8_result.status == INVALID_UTF8


@pytest.mark.parametrize("payload", [b'[1,]', b'[,1]', b'[1,,2]', b'[{"x":1]'])
def test_malformed_structure_and_trailing_comma_are_rejected(payload: bytes):
    result, _, _ = scan(payload)
    assert result.status == MALFORMED_JSON_STRUCTURE


def test_primitive_array_items_record_only_their_types():
    result, events, _ = scan(b'["secret",1,true,false,null]')
    assert result.status == RECORD_OK
    assert [event.record_type for event in events] == ["string", "integer", "boolean", "boolean", "null"]


def test_record_parse_failure_is_reported_without_raw_value():
    result, events, _ = scan(b'[tru,{"text":"ok"}]')
    assert result.status == RECORD_OK
    assert result.parse_error is True
    assert events[0].status == RECORD_PARSE_FAILED
    assert events[0].value is None
    assert events[1].status == RECORD_OK


def test_oversized_record_drops_buffer_and_finds_next_boundary():
    result, events, _ = scan(b'["01234567890123456789",{"text":"ok"}]', max_record_bytes=16)
    assert result.status == RECORD_OK
    assert events[0].status == RECORD_TOO_LARGE
    assert events[0].value is None
    assert events[1].status == RECORD_OK


def test_read_limit_is_respected_and_never_uses_unbounded_read():
    payload = b'[{"text":"' + (b"x" * 1000) + b'"}]'
    result, events, source = scan(payload, max_read_bytes=64)
    assert result.status == ENTRY_READ_LIMIT_REACHED
    assert result.bytes_read == 64
    assert events[-1].status != RECORD_OK
    assert all(request >= 0 for request in source.requests)


def test_record_analysis_hides_values_and_hashes_unknown_keys():
    analysis = analyze_record({
        "text": "TOP-SECRET-VALUE",
        "private_field": "HIDDEN-VALUE",
        "label": 1,
        "metadata": {"source": "INTERNAL"},
    })
    rendered = json.dumps(analysis, ensure_ascii=False)
    assert "TOP-SECRET-VALUE" not in rendered
    assert "HIDDEN-VALUE" not in rendered
    assert "INTERNAL" not in rendered
    assert "private_field" not in rendered
    assert {"text", "label", "metadata", "source"}.issubset(analysis["allowed_key_names"])
    assert analysis["hashed_key_names"]
    assert analysis["metadata_field_candidates"]


def test_pii_field_name_warning_contains_signal_not_original_value():
    analysis = analyze_record({"email": "person@example.invalid", "text": "secret"})
    rendered = json.dumps(analysis, ensure_ascii=False)
    assert "person@example.invalid" not in rendered
    assert analysis["pii_field_name_warnings"][0]["warning"] == "pii_field_name_signal"


def test_actual_inspection_is_deterministic_private_and_preserves_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    content = json.dumps([
        {"text": "SECRET-A", "unknown": "VALUE-A"},
        {"text": "SECRET-B", "unknown": "VALUE-B"},
        {"text": "SECRET-C", "email": "hidden@example.invalid"},
    ], ensure_ascii=False)
    result, run_root, archive_path = run_sample(tmp_path, monkeypatch, content)
    before = sha256(archive_path)
    manifest = json.loads((run_root / "record-manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    after = sha256(archive_path)
    rendered = json.dumps(manifest, ensure_ascii=False)
    assert result["records_seen"] == 3
    assert result["records_selected"] == 2
    assert before == after
    assert result["source_mutation_detected"] is False
    assert "SECRET-" not in rendered
    assert "VALUE-" not in rendered
    assert "hidden@example.invalid" not in rendered
    assert "/approved/large.json" not in rendered
    assert str(archive_path) not in rendered
    ranks = [row["selection_rank"] for row in manifest["records"]]
    assert ranks == sorted(ranks)
    assert summary["selected_archive_checksums"][0]["unchanged"] is True


def test_dry_run_reads_no_entry_content_and_writes_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_open = zipfile.ZipFile.open

    def forbidden_open(*args, **kwargs):
        if kwargs.get("mode", args[2] if len(args) > 2 else "r") == "r":
            raise AssertionError("dry-run에서 entry byte를 읽으면 안 됩니다.")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(zip_json_record_sampler, "DEFAULT_LARGE_THRESHOLD_BYTES", 0)
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden_open)
    result, run_root, _ = run_sample(tmp_path, monkeypatch, '[{"text":"secret"}]', dry_run=True)
    monkeypatch.setattr(zipfile.ZipFile, "open", original_open)
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    assert result["run_status"] == "dry_run_planned"
    assert summary["total_bytes_read"] == 0
    assert summary["entries_inspected"] == 0


def test_total_read_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    content = '[{"text":"' + ("x" * 1000) + '"}]'
    result, run_root, _ = run_sample(
        tmp_path,
        monkeypatch,
        content,
        max_read_bytes_per_entry=512,
        max_total_read_bytes=64,
    )
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    assert result["total_bytes_read"] <= 64
    assert summary["total_read_limit_reached"] is True


def test_manifest_selection_is_repeatable_across_output_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    content = json.dumps([{"text": f"secret-{index}"} for index in range(10)])
    first, first_root, _ = run_sample(tmp_path, monkeypatch, content, output_name="one", records_per_entry=3)
    second, second_root, _ = run_sample(tmp_path, monkeypatch, content, output_name="two", records_per_entry=3)
    first_manifest = json.loads((first_root / "record-manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second_root / "record-manifest.json").read_text(encoding="utf-8"))
    assert first["run_id"] == second["run_id"]
    assert first_manifest["records"] == second_manifest["records"]


def test_all_expected_artifacts_exist_and_no_record_file_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _, run_root, _ = run_sample(tmp_path, monkeypatch, '[{"text":"secret"}]')
    expected = {
        "run-summary.json", "entry-summary.json", "record-manifest.json",
        "schema-summary.json", "rejected-records.json", "manual-review-required.json",
    }
    assert {path.name for path in run_root.iterdir()} == expected
    assert not any(path.suffix in {".txt", ".jsonl"} for path in run_root.rglob("*"))
