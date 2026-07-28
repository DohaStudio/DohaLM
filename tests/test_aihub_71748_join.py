import json
import logging
import zipfile
from pathlib import Path

import pytest

from src.data.aihub_71748_join import (
    JoinIntegrityError,
    _archive_contract,
    _scan_once,
    scan_aihub_71748_join,
    validate_determinism,
)


def _records(ids):
    return [{"data_id": value, "ignored_payload": "SYNTHETIC_PAYLOAD_MUST_NOT_LEAK"} for value in ids]


def _write_archive(root: Path, split: str, prefix: str, component: str, records) -> None:
    directory = root / split / ("01.source" if component == "sftdata" else "02.label")
    directory.mkdir(parents=True, exist_ok=True)
    name = "VL.zip" if prefix == "VL" else f"{prefix}.synthetic.zip"
    with zipfile.ZipFile(directory / name, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"synthetic/{component}.json",
            json.dumps({"dataset_info": {"ignored": "SYNTHETIC_METADATA"}, "data_info": records}),
        )


def _package(tmp_path: Path, *, train_data=None, train_label=None, val_data=None, val_label=None) -> Path:
    values = {
        ("Training", "TS_02", "sftdata"): train_data or ["SYNTHETIC_TRAIN_A", "SYNTHETIC_TRAIN_B"],
        ("Training", "TL_02", "sftlabel"): train_label or ["SYNTHETIC_TRAIN_A", "SYNTHETIC_TRAIN_B"],
        ("Validation", "VS_02", "sftdata"): val_data or ["SYNTHETIC_VALID_A"],
        ("Validation", "VL", "sftlabel"): val_label or ["SYNTHETIC_VALID_A"],
    }
    for (split, prefix, component), ids in values.items():
        _write_archive(tmp_path, split, prefix, component, _records(ids))
    return tmp_path


def test_synthetic_one_to_one_is_aggregate_only(tmp_path):
    result = _scan_once(_package(tmp_path))
    encoded = json.dumps(result)
    assert result["splits"]["training"]["relationship"] == "one_to_one"
    assert "SYNTHETIC_TRAIN_A" not in encoded
    assert "SYNTHETIC_PAYLOAD_MUST_NOT_LEAK" not in encoded


@pytest.mark.parametrize(
    ("field", "values", "relationship"),
    [
        ("train_data", ["SYNTHETIC_TRAIN_A", "SYNTHETIC_TRAIN_A"], "many_to_one"),
        ("train_label", ["SYNTHETIC_TRAIN_A", "SYNTHETIC_TRAIN_A"], "one_to_many"),
        ("train_data", ["SYNTHETIC_TRAIN_A", "SYNTHETIC_ORPHAN"], "incomplete"),
        ("train_label", ["SYNTHETIC_TRAIN_A", "SYNTHETIC_ORPHAN"], "incomplete"),
    ],
)
def test_relationship_variants(tmp_path, field, values, relationship):
    result = _scan_once(_package(tmp_path, **{field: values}))
    assert result["splits"]["training"]["relationship"] == relationship


def test_split_overlap_is_counted(tmp_path):
    result = _scan_once(_package(tmp_path, val_data=["SYNTHETIC_TRAIN_A"], val_label=["SYNTHETIC_TRAIN_A"]))
    assert result["cross_split"]["data_overlap"] == 1
    assert result["cross_split"]["joined_overlap"] == 1


def test_cross_component_mismatch_is_counted(tmp_path):
    result = _scan_once(_package(tmp_path, val_label=["SYNTHETIC_TRAIN_A"]))
    assert result["cross_split"]["training_data_validation_label"] == 1


@pytest.mark.parametrize(
    ("value", "code"),
    [(None, "DATA_ID_NULL"), ("", "DATA_ID_EMPTY"), ("  ", "DATA_ID_WHITESPACE_ONLY"), (17, "DATA_ID_TYPE_MISMATCH")],
)
def test_invalid_data_id_fails_closed(tmp_path, value, code):
    with pytest.raises(JoinIntegrityError, match=code):
        _scan_once(_package(tmp_path, train_data=[value]))


def test_missing_data_id_fails_closed(tmp_path):
    root = _package(tmp_path)
    archive_path = root / "Training" / "01.source" / "TS_02.synthetic.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic/sftdata.json", json.dumps({"data_info": [{"other": "SYNTHETIC"}]}))
    with pytest.raises(JoinIntegrityError, match="DATA_ID_MISSING"):
        _scan_once(root)


def test_ambiguous_split_fails_closed(tmp_path):
    root = _package(tmp_path)
    target = root / "Training" / "Validation" / "01.source"
    target.mkdir(parents=True)
    (root / "Training" / "01.source" / "TS_02.synthetic.zip").replace(target / "TS_02.synthetic.zip")
    with pytest.raises(JoinIntegrityError, match="SPLIT_AMBIGUOUS"):
        _archive_contract(root)


def test_unknown_split_fails_closed(tmp_path):
    root = _package(tmp_path)
    target = root / "Test" / "01.source"
    target.mkdir(parents=True)
    (root / "Training" / "01.source" / "TS_02.synthetic.zip").replace(target / "TS_02.synthetic.zip")
    with pytest.raises(JoinIntegrityError, match="SPLIT_UNRESOLVED"):
        _archive_contract(root)


def test_raw_id_leak_attempt_is_blocked():
    from src.data.safety import guard_safe_output

    source = "SYNTHETIC_RAW_JOIN_ID"
    result = guard_safe_output({"status": "passed", "unsafe": source}, source)
    assert result and result["error_code"] == "RAW_VALUE_LEAK_DETECTED"


def test_exception_contains_only_fixed_code():
    error = JoinIntegrityError("DATA_ID_TYPE_MISMATCH")
    assert str(error) == "DATA_ID_TYPE_MISMATCH"


def test_nondeterministic_results_fail_closed():
    with pytest.raises(JoinIntegrityError, match="NON_DETERMINISTIC_SCAN"):
        validate_determinism({"records": 1}, {"records": 2})


def test_scan_runs_exactly_twice_and_emits_no_logs(tmp_path, capsys, caplog, monkeypatch):
    import src.data.aihub_71748_join as module

    calls = 0
    original = module._scan_once

    def counted(root):
        nonlocal calls
        calls += 1
        return original(root)

    monkeypatch.setattr(module, "_scan_once", counted)
    with caplog.at_level(logging.DEBUG):
        result = scan_aihub_71748_join(_package(tmp_path))
    captured = capsys.readouterr()
    assert calls == 2 and result["full_scan_count"] == 2
    assert captured.out == "" and captured.err == "" and caplog.text == ""


def test_missing_package_is_blocked_without_scan(tmp_path):
    result = scan_aihub_71748_join(tmp_path / "missing")
    assert result["error_code"] == "PACKAGE_ROOT_MISSING"
    assert result["execution_allowed"] is False
