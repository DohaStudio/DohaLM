import json
import logging
import zipfile

import pytest

from src.data.aihub_71748_pii import (
    ALLOWED_OUTPUT_FIELD_PATHS,
    PiiScanError,
    _detect_text,
    _field_value,
    _risk,
    _safe_output_field_path,
    scan_aihub_71748_pii,
)


@pytest.mark.parametrize(
    ("text", "candidate"),
    [
        ("synthetic.user@example.invalid", "email"),
        ("010-0000-0000", "phone"),
        ("02-000-0000", "phone"),
        ("M12345678", "passport_like"),
        ("11-22-123456-78", "driver_license_like"),
        ("4242 4242 4242 4242", "card_number_like"),
        ("000-000000-00000", "account_number_like"),
        ("192.0.2.10", "ip_address"),
        ("https://synthetic.invalid/path", "url"),
        ("합성시 시험구 가상로 0", "address"),
        ("우편 00000", "postal_code"),
        ("12가0000", "vehicle_number_like"),
        ("2000-01-01", "birth_date"),
        ("이름 홍길동", "person_name_candidate"),
        ("합성대학교 교수", "organization_role_combination"),
        ("합성 진단 기록", "medical_sensitive_candidate"),
        ("합성 우울증 기록", "mental_health_candidate"),
        ("합성 피고인 기록", "legal_sensitive_candidate"),
        ("합성 대출 기록", "financial_sensitive_candidate"),
        ("합성 종교 기록", "religion_candidate"),
        ("합성 정당 기록", "political_candidate"),
        ("합성 배우자 기록", "family_relation_candidate"),
        ("@synthetic_user", "social_handle"),
    ],
)
def test_candidate_detection_is_type_only(text, candidate):
    result = _detect_text(text)
    assert candidate in result["types"]
    assert text not in json.dumps(result)


def test_invalid_card_and_invalid_rrn_are_not_accepted():
    result = _detect_text("1234 5678 9012 3456 and 991399-1234567")
    assert "card_number_like" not in result["types"]
    assert "resident_id_like" not in result["types"]


def test_structurally_valid_synthetic_rrn_candidate_is_detected():
    result = _detect_text("900101-1000006")
    assert "resident_id_like" in result["types"]


def test_combination_risk_levels():
    assert _risk(set()) == "none"
    assert _risk({"person_name_candidate"}) == "low"
    assert _risk({"phone"}) == "medium"
    assert _risk({"phone", "address"}) == "high"
    assert _risk({"card_number_like"}) == "critical"


@pytest.mark.parametrize("value", ["", " \t\n", "SYNTHETIC " * 2000, "line one\nline two", '{"nested":"synthetic"}'])
def test_safe_text_shapes_emit_no_source(value):
    result = _detect_text(value)
    assert not value or value not in json.dumps(result)


def test_malformed_type_uses_fixed_error():
    error = PiiScanError("PII_FIELD_TYPE_MISMATCH")
    assert str(error) == "PII_FIELD_TYPE_MISMATCH"


@pytest.mark.parametrize("value", [None, 17])
def test_null_or_non_string_allowed_field_fails_closed(value):
    with pytest.raises(PiiScanError, match="PII_FIELD_TYPE_MISMATCH"):
        _field_value({"question": value}, ("question",))


def test_raw_value_leak_is_blocked():
    from src.data.safety import guard_safe_output

    source = "SYNTHETIC_PII_RAW_VALUE"
    blocked = guard_safe_output({"status": "ok", "unsafe": source}, source)
    assert blocked and blocked["error_code"] == "RAW_VALUE_LEAK_DETECTED"


def test_output_field_paths_are_exact_fixed_allowlist():
    assert ALLOWED_OUTPUT_FIELD_PATHS == {
        "$.sftdata.question",
        "$.sftlabel.question",
        "$.sftlabel.answer.contents",
    }


def test_unknown_or_dynamic_output_field_path_is_rejected():
    with pytest.raises(PiiScanError, match="UNSAFE_OUTPUT_STRING"):
        _safe_output_field_path("sftlabel", ("answer", "dynamic"))


def _write(root, split, prefix, component, count):
    directory = root / split / component
    directory.mkdir(parents=True, exist_ok=True)
    name = "VL.zip" if prefix == "VL" else f"{prefix}.synthetic.zip"
    records = []
    for index in range(count):
        record = {"data_id": f"SYNTHETIC-{split}-{component}-{index}", "question": "synthetic question"}
        if component == "sftlabel":
            record["answer"] = {"contents": "synthetic answer"}
        records.append(record)
    with zipfile.ZipFile(directory / name, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"synthetic/{component}.json", json.dumps({"data_info": records}))


def test_single_scan_contract_and_no_logging(tmp_path, monkeypatch, capsys, caplog):
    import src.data.aihub_71748_pii as module

    for split, count in (("Training", 2), ("Validation", 1)):
        _write(tmp_path, split, "TS_02" if split == "Training" else "VS_02", "sftdata", count)
        _write(tmp_path, split, "TL_02" if split == "Training" else "VL", "sftlabel", count)
    monkeypatch.setattr(module, "EXPECTED_RECORDS", {"training": 2, "validation": 1})
    calls = 0
    original = module._scan_once

    def counted(root):
        nonlocal calls
        calls += 1
        return original(root)

    monkeypatch.setattr(module, "_scan_once", counted)
    with caplog.at_level(logging.DEBUG):
        result = scan_aihub_71748_pii(tmp_path)
    captured = capsys.readouterr()
    assert calls == 1 and result["full_scan_count"] == 1
    assert result["status"] == "completed_no_candidates_detected"
    assert set(result["fields"]) == ALLOWED_OUTPUT_FIELD_PATHS
    assert captured.out == "" and captured.err == "" and caplog.text == ""
    encoded = json.dumps(result)
    assert "synthetic question" not in encoded and "synthetic answer" not in encoded


def test_missing_root_is_blocked(tmp_path):
    result = scan_aihub_71748_pii(tmp_path / "missing")
    assert result["full_scan_count"] == 0
    assert result["execution_allowed"] is False
