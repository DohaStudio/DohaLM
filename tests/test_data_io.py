from __future__ import annotations

from pathlib import Path

import pytest

from src.data.checksums import file_checksum
from src.data.config import validate_data_config
from src.data.discovery import discover_inputs
from src.data.errors import DataPipelineError
from src.data.models import InputSource, RejectedRecord
from src.data.readers import read_source
from src.data.validation import canonicalize


def config(inputs):
    return validate_data_config({
        "dataset_id": "fixture-dataset", "dataset_version": "v1", "input_paths": inputs,
        "output_dir": "out", "split": {"seed": 42, "train_ratio": .8, "validation_ratio": .1, "test_ratio": .1, "ratio_tolerance": 1e-9},
        "source": {"license_status": "approved", "approval_status": "approved", "pii_status": "clear"},
    })


def source(path: Path, root: Path):
    return InputSource(path, path.relative_to(root).as_posix(), path.suffix[1:], path.stat().st_size, file_checksum(path))


def test_discovery_file_directory_multiple_sort_and_hidden(tmp_path: Path):
    folder = tmp_path / "inputs"; nested = folder / "nested"; nested.mkdir(parents=True)
    (folder / "b.txt").write_text("b", encoding="utf-8")
    (nested / "a.jsonl").write_text('{"id":"a","text":"a","source":"fixture-dataset"}\n', encoding="utf-8")
    (folder / ".hidden.txt").write_text("skip", encoding="utf-8")
    found = discover_inputs(config(["inputs"]), tmp_path)
    assert [item.relative_path for item in found] == ["inputs/b.txt", "inputs/nested/a.jsonl"]
    windows_style = discover_inputs(config(["inputs\\nested\\a.jsonl"]), tmp_path)
    assert windows_style[0].relative_path == "inputs/nested/a.jsonl"
    with pytest.raises(DataPipelineError):
        discover_inputs(config(["inputs/b.txt", "inputs/b.txt"]), tmp_path)
    with pytest.raises(DataPipelineError):
        discover_inputs(config(["missing"]), tmp_path)


def test_discovery_rejects_unsupported(tmp_path: Path):
    (tmp_path / "bad.csv").write_text("x", encoding="utf-8")
    with pytest.raises(DataPipelineError, match="UNSUPPORTED_FORMAT"):
        discover_inputs(config(["bad.csv"]), tmp_path)


def test_discovery_rejects_output_inside_input(tmp_path: Path):
    folder = tmp_path / "out"; folder.mkdir()
    (folder / "input.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DataPipelineError, match="입력과 출력 경로"):
        discover_inputs(config(["out"]), tmp_path)


def test_txt_reader_bom_crlf_and_invalid_utf8(tmp_path: Path):
    good = tmp_path / "good.txt"; good.write_bytes(b"\xef\xbb\xbf" + "첫 줄\r\n둘째 줄".encode())
    item = read_source(source(good, tmp_path), "fixture-dataset")[0]
    assert item.text == "첫 줄\r\n둘째 줄"
    bad = tmp_path / "bad.txt"; bad.write_bytes(b"\xff")
    with pytest.raises(DataPipelineError, match="INVALID_ENCODING"):
        read_source(source(bad, tmp_path), "fixture-dataset")


@pytest.mark.parametrize("content", ["[]\n", "{bad}\n", "\n", '{"id":"a","id":"b","text":"x","source":"fixture-dataset"}\n', '{"id":"a","text":"x","source":"fixture-dataset","metadata":{"x":NaN}}\n'])
def test_jsonl_structure_errors(tmp_path: Path, content: str):
    path = tmp_path / "bad.jsonl"; path.write_text(content, encoding="utf-8")
    with pytest.raises(DataPipelineError, match="INVALID_JSONL"):
        read_source(source(path, tmp_path), "fixture-dataset")


def test_jsonl_validation_rejections(tmp_path: Path):
    path = tmp_path / "records.jsonl"
    path.write_text('\n'.join([
        '{"id":"ok","text":"문장","source":"fixture-dataset"}',
        '{"id":"missing","source":"fixture-dataset"}',
        '{"id":"unknown","text":"문장","source":"fixture-dataset","x":1}',
        '{"id":1,"text":"문장","source":"fixture-dataset"}',
        '{"id":"nul","text":"\\u0000","source":"fixture-dataset"}',
        '{"id":"meta","text":"문장","source":"fixture-dataset","metadata":{"a":{"b":{"c":{"d":{"e":{"f":1}}}}}}}',
    ]) + '\n', encoding="utf-8")
    results = [canonicalize(item, config(["records.jsonl"])) for item in read_source(source(path, tmp_path), "fixture-dataset")]
    codes = [item.reason_code for item in results if isinstance(item, RejectedRecord)]
    assert codes == ["MISSING_REQUIRED_FIELD", "UNKNOWN_FIELD", "INVALID_FIELD_TYPE", "NUL_CHARACTER", "INVALID_FIELD_TYPE"]


def test_validation_identifier_and_text_limits(tmp_path: Path):
    path = tmp_path / "limits.jsonl"
    path.write_text('\n'.join([
        '{"id":"' + ('a' * 257) + '","text":"x","source":"fixture-dataset"}',
        '{"id":"ok","text":"' + ('가' * 1_000_001) + '","source":"fixture-dataset"}',
    ]) + '\n', encoding="utf-8")
    limited = config(["limits.jsonl"])
    results = [canonicalize(item, limited) for item in read_source(source(path, tmp_path), "fixture-dataset")]
    assert [item.reason_code for item in results] == ["INVALID_FIELD_TYPE", "TEXT_TOO_LONG"]
