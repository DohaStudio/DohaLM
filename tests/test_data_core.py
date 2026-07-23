from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.config.errors import ConfigValidationError
from src.data.checksums import checksum_value, file_checksum
from src.data.config import validate_data_config
from src.data.deduplicate import deduplicate
from src.data.errors import DataPipelineError
from src.data.identifiers import generated_group_id, record_id
from src.data.models import CanonicalRecord
from src.data.normalization import normalize_text
from src.data.splitting import assign_splits, validate_no_leakage


def data_mapping(**updates):
    value = {
        "dataset_id": "fixture-dataset", "dataset_version": "v1", "input_paths": ["input"],
        "output_dir": "output", "max_text_chars": 1_000_000, "metadata_max_depth": 5,
        "split": {"seed": 42, "train_ratio": .8, "validation_ratio": .1, "test_ratio": .1, "ratio_tolerance": 1e-9},
        "source": {"license_status": "approved", "approval_status": "approved", "pii_status": "clear"},
    }
    value.update(updates)
    return value


def record(name: str, *, file="sha256:" + "1" * 64, raw=None, normalized=None, group=None):
    raw = raw or f"sha256:{name.zfill(64)}"
    normalized = normalized or f"sha256:{name.zfill(64)}"
    return CanonicalRecord(name, name, "fixture-dataset", f"input/{name}.txt", group or name, name, name,
                           file, raw, normalized, {}, "approved", "approved", "clear")


def test_data_config_split_validation_and_zero_validation_test():
    config = validate_data_config(data_mapping(split={"seed": 42, "train_ratio": 1.0, "validation_ratio": 0.0, "test_ratio": 0.0, "ratio_tolerance": 1e-9}))
    assert config.train_ratio == 1.0
    with pytest.raises(ConfigValidationError):
        validate_data_config(data_mapping(split={"seed": 42, "train_ratio": 0.0, "validation_ratio": .5, "test_ratio": .5, "ratio_tolerance": 1e-9}))
    without_source = data_mapping(); without_source.pop("source")
    with pytest.raises(ConfigValidationError, match="source"):
        validate_data_config(without_source)


def test_normalization_contract():
    assert normalize_text("A  B  \r\ne\u0301! 😀\t\r") == "A  B\né! 😀\n"
    with pytest.raises(ValueError):
        normalize_text(" \t\n")
    with pytest.raises(ValueError):
        normalize_text("x\0y")


def test_canonical_checksum_is_stable_and_file_keeps_bom(tmp_path: Path):
    assert checksum_value({"b": 2, "a": 1}) == checksum_value({"a": 1, "b": 2})
    assert checksum_value("a") != checksum_value("b")
    assert checksum_value("a").startswith("sha256:") and len(checksum_value("a")) == 71
    plain = tmp_path / "plain.txt"; bom = tmp_path / "bom.txt"
    plain.write_bytes("문장".encode()); bom.write_bytes(b"\xef\xbb\xbf" + "문장".encode())
    assert file_checksum(plain) != file_checksum(bom)


def test_ids_are_deterministic_and_use_canonical_paths():
    one = record_id("s", "input/a.txt", "id", checksum_value("x"))
    assert one == record_id("s", "input/a.txt", "id", checksum_value("x"))
    assert one != record_id("s", "input/a.txt", "id", checksum_value("y"))
    assert generated_group_id("s", "input/a.txt") == generated_group_id("s", "input/a.txt")


def test_dedup_priority_and_input_order_independence():
    a = record("a")
    b = record("b", file=a.file_checksum)
    c = record("c", file="sha256:" + "2" * 64, raw=a.raw_record_checksum)
    d = record("d", file="sha256:" + "3" * 64, normalized=a.normalized_record_checksum)
    first, duplicates = deduplicate([d, c, b, a])
    second, duplicates_again = deduplicate([a, b, c, d])
    assert [item.record_id for item in first] == [item.record_id for item in second] == ["a"]
    assert {item.duplicate_type for item in duplicates} == {"FILE_DUPLICATE", "RAW_RECORD_DUPLICATE", "NORMALIZED_TEXT_DUPLICATE"}
    assert duplicates == duplicates_again


def test_split_is_stable_and_preserves_groups():
    config = validate_data_config(data_mapping())
    values = [record("a", group="same"), record("b", file="sha256:" + "2" * 64, group="same"), record("c", file="sha256:" + "3" * 64)]
    splits, assignments = assign_splits(values, config)
    reversed_splits, reversed_assignments = assign_splits(list(reversed(values)), config)
    assert assignments == reversed_assignments
    assert {item.split for item in assignments if item.group_id == "same"}.__len__() == 1
    validate_no_leakage(splits)
    assert {key: [r.record_id for r in value] for key, value in splits.items()} == {key: [r.record_id for r in value] for key, value in reversed_splits.items()}


@pytest.mark.parametrize("dimension", ["group", "normalized", "record", "source"])
def test_leakage_dimensions_raise(dimension: str):
    left = record("left", file="sha256:" + "1" * 64)
    right = record("right", file="sha256:" + "2" * 64)
    if dimension == "group":
        right = CanonicalRecord(**{**right.__dict__, "group_id": left.group_id})
    elif dimension == "normalized":
        right = CanonicalRecord(**{**right.__dict__, "normalized_record_checksum": left.normalized_record_checksum})
    elif dimension == "record":
        right = CanonicalRecord(**{**right.__dict__, "record_id": left.record_id})
    else:
        right = CanonicalRecord(**{**right.__dict__, "source_path": left.source_path, "source_record_id": left.source_record_id})
    with pytest.raises(DataPipelineError, match="SPLIT_LEAKAGE"):
        validate_no_leakage({"train": [left], "validation": [right], "test": []})
