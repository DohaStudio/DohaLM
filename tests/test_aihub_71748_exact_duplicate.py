import json
import logging
import zipfile

import pytest

from src.data.aihub_71748_exact_duplicate import (
    ExactDuplicateScanError,
    _string_field,
    scan_aihub_71748_exact_duplicates,
    summarize_exact_duplicates,
)


def _summary(training=(), validation=()):
    return summarize_exact_duplicates({"training": training, "validation": validation})


def test_same_question_is_counted_without_value_output():
    result = _summary(training=[("Q-A", "Q-A", "A-1"), ("Q-A", "Q-A", "A-2")])
    assert result["question"]["duplicate_groups"] == 1
    assert result["question"]["duplicate_records"] == 1
    assert "Q-A" not in json.dumps(result)


def test_same_answer_is_counted():
    result = _summary(training=[("Q-1", "Q-1", "A-X"), ("Q-2", "Q-2", "A-X")])
    assert result["answer"]["duplicate_groups"] == 1
    assert result["different_question_same_answer"]["groups"] == 1


def test_same_qa_pair_is_counted():
    result = _summary(training=[("Q-1", "Q-1", "A-1"), ("Q-1", "Q-1", "A-1")])
    assert result["qa_pair"]["duplicate_groups"] == 1
    assert result["qa_pair"]["duplicate_records"] == 1


def test_same_question_different_answer_is_counted():
    result = _summary(training=[("Q-1", "Q-1", "A-1"), ("Q-1", "Q-1", "A-2")])
    assert result["same_question_different_answer"]["groups"] == 1


def test_training_validation_overlap_is_exact():
    result = _summary(
        training=[("Q-1", "Q-1", "A-1")],
        validation=[("Q-1", "Q-1", "A-1")],
    )
    assert result["split_overlap"] == {
        "training_validation_question": 1,
        "training_validation_answer": 1,
        "training_validation_pair": 1,
    }


def test_component_consistency_is_lockstep_exact():
    result = _summary(training=[("Q-1", "Q-1", "A-1"), ("Q-2", "Q-X", "A-2")])
    assert result["component_consistency"]["scanned"] == 2
    assert result["component_consistency"]["sftdata_vs_sftlabel_question"] == 1
    assert result["component_consistency"]["mismatched"] == 1


@pytest.mark.parametrize(
    "value",
    ["", " \t\n", "SYNTHETIC " * 4000, "line one\nline two"],
    ids=["empty", "whitespace", "long", "multiline"],
)
def test_empty_whitespace_long_and_multiline_strings_are_exact_values(value):
    result = _summary(training=[(value, value, value), (value, value, value)])
    assert result["question"]["duplicate_groups"] == 1
    assert value not in json.dumps(result) if value else True


@pytest.mark.parametrize("value,code", [(None, "FIELD_NULL"), (17, "FIELD_TYPE_MISMATCH")])
def test_null_and_non_string_fields_fail_closed(value, code):
    record = {"question": value}
    with pytest.raises(ExactDuplicateScanError, match=code):
        _string_field(record, "sftdata", ("question",))


def test_unknown_field_fails_closed_without_reading_value():
    with pytest.raises(ExactDuplicateScanError, match="FIELD_NOT_ALLOWED"):
        _string_field({"context": "SYNTHETIC_MUST_NOT_LEAK"}, "sftdata", ("context",))


def test_leak_and_output_guards_block_raw_or_unapproved_strings():
    from src.data.safety import guard_safe_output

    raw = "SYNTHETIC_RAW_DUPLICATE_VALUE"
    assert guard_safe_output({"status": "completed", "unsafe": raw}, raw)["error_code"] == "RAW_VALUE_LEAK_DETECTED"
    assert guard_safe_output({"status": "not approved prose"}, ())["error_code"] == "UNSAFE_OUTPUT_STRING"


def _write_archive(root, split, prefix, component, records):
    directory = root / split / ("01.source" if component == "sftdata" else "02.label")
    directory.mkdir(parents=True, exist_ok=True)
    name = "VL.zip" if prefix == "VL" else f"{prefix}.synthetic.zip"
    with zipfile.ZipFile(directory / name, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"synthetic/{component}.json",
            json.dumps({"data_info": records}),
        )


def _package(root):
    values = {
        ("Training", "TS_02", "sftdata"): [{"question": "T-Q1"}, {"question": "T-Q2"}],
        ("Training", "TL_02", "sftlabel"): [
            {"question": "T-Q1", "answer": {"contents": "T-A1"}},
            {"question": "T-Q2", "answer": {"contents": "T-A2"}},
        ],
        ("Validation", "VS_02", "sftdata"): [{"question": "V-Q1"}],
        ("Validation", "VL", "sftlabel"): [
            {"question": "V-Q1", "answer": {"contents": "V-A1"}},
        ],
    }
    for (split, prefix, component), records in values.items():
        _write_archive(root, split, prefix, component, records)
    return root


def test_scan_runs_exactly_once_and_emits_no_payload_or_logs(tmp_path, monkeypatch, capsys, caplog):
    import src.data.aihub_71748_exact_duplicate as module

    monkeypatch.setattr(module, "EXPECTED_RECORDS", {"training": 2, "validation": 1})
    calls = 0
    original = module._scan_once

    def counted(root):
        nonlocal calls
        calls += 1
        return original(root)

    monkeypatch.setattr(module, "_scan_once", counted)
    with caplog.at_level(logging.DEBUG):
        result = scan_aihub_71748_exact_duplicates(_package(tmp_path))
    captured = capsys.readouterr()
    encoded = json.dumps(result)
    assert calls == 1 and result["full_scan_count"] == 1 and result["status"] == "completed"
    assert "T-Q1" not in encoded and "T-A1" not in encoded
    assert captured.out == "" and captured.err == "" and caplog.text == ""


def test_missing_root_is_blocked_before_scan(tmp_path):
    result = scan_aihub_71748_exact_duplicates(tmp_path / "missing")
    assert result["status"] == "blocked"
    assert result["full_scan_count"] == 0
    assert result["execution_allowed"] is False
