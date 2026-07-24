from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.datasets.adapt_aihub_71748 import run
from src.data.adapters.aihub_71748 import AIHub71748Adapter
from src.data.adapters.base import AdapterArtifactWriter, iter_adapted, load_synthetic_json_records
from src.data.adapters.contracts import AdapterPolicy
from src.data.checksums import file_checksum
from src.data.errors import DataPipelineError


FIXTURES = Path("tests/fixtures/data/aihub_71748")


def accepted(record, *, adapter=None):
    result = (adapter or AIHub71748Adapter()).adapt_record(record)
    assert result.accepted is not None
    return result.accepted


def rejected(record, *, adapter=None):
    result = (adapter or AIHub71748Adapter()).adapt_record(record)
    assert result.rejected is not None
    return result.rejected


def test_normal_record_is_adapted_and_usage_remains_blocked():
    value = accepted({"text": "한국어 합성 문장입니다."})
    assert value["adapter_status"] == "adapted"
    assert value["usage_status"] == "blocked_pending_approval"
    assert value["split_eligibility"] == "blocked_pending_approval"
    assert set(value["usage_block_reasons"]) == {
        "LICENSE_NOT_APPROVED", "APPROVAL_NOT_APPROVED", "PII_REVIEW_REQUIRED"
    }


def test_only_text_is_used_as_body_and_metadata_source_are_not_mixed():
    value = accepted({
        "text": "본문만 남습니다.",
        "metadata": {"secret": "메타데이터 값"},
        "source": "출처 값",
    })
    rendered = json.dumps(value, ensure_ascii=False)
    assert value["text_normalized"] == "본문만 남습니다."
    assert "메타데이터 값" not in rendered
    assert "출처 값" not in rendered


def test_nfc_and_newline_normalization_follow_phase1_policy():
    value = accepted({"text": "한글  \r\n둘째 줄\r"})
    assert value["text_normalized"] == "한글\n둘째 줄\n"
    assert value["normalization_applied"] is True


def test_consecutive_spaces_are_preserved_and_nfkc_is_not_applied():
    value = accepted({"text": "전각 Ａ와  연속 공백"})
    assert value["text_normalized"] == "전각 Ａ와  연속 공백"


def test_record_id_and_output_hash_are_deterministic():
    record = {"text": "동일 입력", "metadata": {"kind": "synthetic"}}
    one = accepted(record)
    two = accepted(record)
    assert one["record_id"] == two["record_id"]
    assert one["lineage"]["output_record_hash"] == two["lineage"]["output_record_hash"]


def test_schema_signature_is_deterministic_and_value_free():
    one = accepted({"text": "첫 값", "metadata": {"category": "alpha"}})
    two = accepted({"metadata": {"category": "beta"}, "text": "둘째 값"})
    assert one["schema_signature"] == two["schema_signature"]
    assert "category" not in json.dumps(one, ensure_ascii=False)


@pytest.mark.parametrize(("record", "code"), [
    (["not-object"], "ROOT_NOT_OBJECT"),
    ({"metadata": {}}, "TEXT_FIELD_MISSING"),
    ({"text": None}, "TEXT_NOT_STRING"),
    ({"text": 1}, "TEXT_NOT_STRING"),
    ({"text": ""}, "TEXT_EMPTY"),
    ({"text": " \t\n"}, "TEXT_WHITESPACE_ONLY"),
    ({"text": "a\x00b"}, "TEXT_CONTAINS_NUL"),
])
def test_structural_rejection_codes(record, code):
    assert rejected(record)["reason_code"] == code


def test_invalid_unicode_is_rejected_without_storing_text():
    value = rejected({"text": "invalid-\ud800"})
    assert value["reason_code"] == "INVALID_UNICODE"
    assert "invalid" not in json.dumps(value)


def test_minimum_and_maximum_length_are_enforced_early():
    policy = AdapterPolicy(minimum_text_characters=3, maximum_text_characters=5)
    adapter = AIHub71748Adapter(policy)
    assert rejected({"text": "ab"}, adapter=adapter)["reason_code"] == "TEXT_TOO_SHORT"
    assert rejected({"text": "abcdef"}, adapter=adapter)["reason_code"] == "TEXT_TOO_LONG"


def test_unknown_field_is_ignored_and_only_warning_is_recorded():
    value = accepted({"text": "본문", "unknown_value": "저장 금지 값"})
    rendered = json.dumps(value, ensure_ascii=False)
    assert value["schema_warnings"] == ["UNKNOWN_FIELD_IGNORED"]
    assert "저장 금지 값" not in rendered
    assert "unknown_value" not in rendered


def test_pii_like_field_name_adds_warning_without_name_or_value():
    value = accepted({"text": "본문", "customer_phone": "000-0000"})
    rendered = json.dumps(value, ensure_ascii=False)
    assert "PII_LIKE_FIELD_NAME" in value["schema_warnings"]
    assert "customer_phone" not in rendered
    assert "000-0000" not in rendered


def test_lineage_contains_required_hashes_and_no_source_object():
    source = {"text": "계보 합성 문장", "source": "do-not-copy"}
    value = accepted(source)
    assert set(value["lineage"]) == {
        "source_record_hash", "adapter_version", "normalization_version",
        "schema_signature", "output_record_hash",
    }
    assert "do-not-copy" not in json.dumps(value, ensure_ascii=False)


def test_one_pass_iterable_is_consumed_incrementally():
    seen = []

    def records():
        for index in range(3):
            seen.append(index)
            yield {"text": f"합성 {index}"}

    outcomes = iter_adapted(records(), AIHub71748Adapter())
    assert seen == []
    next(outcomes)
    assert seen == [0]


def test_atomic_publish_separates_results_and_manifest_counts(tmp_path: Path):
    adapter = AIHub71748Adapter()
    records = [{"text": "정상"}, {"text": ""}, {"text": "다른 정상"}]
    output = tmp_path / "adapter-output"
    manifest = AdapterArtifactWriter(output, adapter).publish(iter_adapted(records, adapter))
    assert sorted(path.name for path in output.iterdir()) == [
        "accepted.jsonl", "adapter-manifest.json", "rejections.jsonl", "schema-summary.json"
    ]
    assert manifest["input_record_count"] == 3
    assert manifest["accepted_record_count"] == 2
    assert manifest["rejected_record_count"] == 1
    assert manifest["rejection_reason_counts"] == {"TEXT_EMPTY": 1}
    assert len((output / "accepted.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert len((output / "rejections.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_manifest_fingerprints_ignore_input_order_and_creation_time(tmp_path: Path):
    adapter = AIHub71748Adapter()
    records = [{"text": "가"}, {"text": "나"}, {"text": ""}]
    one = AdapterArtifactWriter(tmp_path / "one", adapter).publish(iter_adapted(records, adapter))
    two = AdapterArtifactWriter(tmp_path / "two", adapter).publish(iter_adapted(reversed(records), adapter))
    assert one["input_fingerprint"] == two["input_fingerprint"]
    assert one["output_fingerprint"] == two["output_fingerprint"]
    assert one["fingerprint"] == two["fingerprint"]


def test_artifacts_do_not_expose_absolute_paths_or_rejected_source(tmp_path: Path):
    adapter = AIHub71748Adapter()
    output = tmp_path / "out"
    secret = "synthetic-secret-value"
    AdapterArtifactWriter(output, adapter).publish(iter_adapted([{"text": None, "secret": secret}], adapter))
    combined = "".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert str(tmp_path) not in combined
    assert secret not in combined


def test_source_fixture_checksum_is_unchanged(tmp_path: Path):
    source = FIXTURES / "valid_records.json"
    before = file_checksum(source)
    adapter = AIHub71748Adapter()
    records = load_synthetic_json_records(source, max_read_bytes=1_000_000)
    AdapterArtifactWriter(tmp_path / "out", adapter).publish(iter_adapted(records, adapter), source_path=source)
    assert file_checksum(source) == before


def test_existing_output_is_not_overwritten(tmp_path: Path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(DataPipelineError, match="ARTIFACT_WRITE_ERROR"):
        AdapterArtifactWriter(output, AIHub71748Adapter()).publish([])
    assert marker.read_text(encoding="utf-8") == "keep"


def test_synthetic_fixture_contract_and_expected_rejections():
    valid = list(load_synthetic_json_records(FIXTURES / "valid_records.json", max_read_bytes=1_000_000))
    invalid = list(load_synthetic_json_records(FIXTURES / "invalid_records.json", max_read_bytes=1_000_000))
    expected = json.loads((FIXTURES / "expected_records.json").read_text(encoding="utf-8"))
    assert len(valid) == expected["valid_count"]
    assert [rejected(record)["reason_code"] for record in invalid] == expected["invalid_reason_codes"]


def _args(**overrides):
    values = {
        "input": None, "output": None, "synthetic": False,
        "config": Path("configs/local-datasets.yaml"), "dataset": "AIHUB-71748",
        "manual_mapping": Path("configs/aihub-71748-path-mapping.yaml"),
        "approval_log": Path("docs/data/dataset-approval-log.md"),
        "max_records": None, "max_read_bytes": 1_000_000,
        "dry_run": True, "json": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_actual_dataset_dry_run_is_blocked_and_reads_zero_content(monkeypatch):
    def forbidden_open(*args, **kwargs):
        raise AssertionError("actual dry-run must not open dataset-related files")

    monkeypatch.setattr(Path, "open", forbidden_open)
    result = run(_args())
    assert result["status"] == "blocked_pending_approval"
    assert result["records_read"] == 0
    assert result["content_bytes_read"] == 0
    assert result["artifacts_published"] == 0


def test_actual_execution_without_dry_run_is_rejected():
    with pytest.raises(ValueError, match="blocked"):
        run(_args(dry_run=False))


def test_synthetic_mode_rejects_paths_outside_fixture_and_output_roots(tmp_path: Path):
    input_path = tmp_path / "actual.json"
    input_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="fixtures"):
        run(_args(
            input=input_path, output=Path("tests/output/out"), synthetic=True,
            config=None, manual_mapping=None, approval_log=None, dry_run=False,
        ))


def test_synthetic_cli_contract_publishes_only_fixture_records(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    fixture_dir = root / "tests" / "fixtures" / "data" / "aihub_71748"
    fixture_dir.mkdir(parents=True)
    output_dir = root / "tests" / "output" / "adapter"
    source = fixture_dir / "valid_records.json"
    source.write_bytes((FIXTURES / "valid_records.json").read_bytes())
    monkeypatch.chdir(root)
    result = run(_args(
        input=source, output=output_dir, synthetic=True,
        config=None, manual_mapping=None, approval_log=None, dry_run=False,
    ))
    assert result["status"] == "synthetic_adapter_completed"
    assert result["accepted_record_count"] == 8
    assert result["development_corpus_publish"] == "blocked"


def test_bounded_reader_rejects_oversized_synthetic_input():
    source = FIXTURES / "valid_records.json"
    with pytest.raises(ValueError, match="max-read-bytes"):
        list(load_synthetic_json_records(source, max_read_bytes=1))
