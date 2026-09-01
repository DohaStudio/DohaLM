from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.candidate_a_allocation_fingerprint import (
    CONTRACT_VERSION,
    canonical_allocation_bytes,
    fingerprint_allocation,
    load_allocation_fingerprint_contract,
)


SOURCE_A = "sha256:" + "a" * 64
SOURCE_B = "sha256:" + "b" * 64
GROUP_A = "group:sha256:" + "c" * 64
GROUP_B = "group:sha256:" + "d" * 64


def _rows() -> list[dict[str, object]]:
    return [
        {"source_id": SOURCE_B, "group_key": GROUP_B, "split": "test"},
        {"source_id": SOURCE_A, "group_key": GROUP_A, "split": "train"},
    ]


def _contract(path: Path, fingerprint: str, size: int) -> Path:
    value = {
        "schema_version": 1,
        "status": "approved",
        "contract_version": CONTRACT_VERSION,
        "logical_fields": ["source_id", "group_key", "split"],
        "record_order": "source_id_utf8_bytes_ascending",
        "unicode_normalization": "none_ascii_identifiers_required",
        "serialization": "canonical_json",
        "json_sort_keys": True,
        "json_separators": [",", ":"],
        "json_ensure_ascii": False,
        "trailing_newline": "LF_exactly_one",
        "encoding": "UTF-8",
        "hash_algorithm": "SHA-256",
        "expected_fingerprint": fingerprint,
        "canonical_bytes_size": size,
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_allocation_fingerprint_is_order_and_mapping_order_independent() -> None:
    expected = fingerprint_allocation(_rows())
    reversed_with_different_key_order = [
        {
            "split": row["split"],
            "group_key": row["group_key"],
            "source_id": row["source_id"],
        }
        for row in reversed(_rows())
    ]
    assert fingerprint_allocation(reversed_with_different_key_order) == expected
    assert canonical_allocation_bytes(_rows()).endswith(b"\n")
    assert b"\r" not in canonical_allocation_bytes(_rows())


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "sha256:" + "e" * 64),
        ("group_key", "group:sha256:" + "e" * 64),
        ("split", "validation"),
    ],
)
def test_allocation_fingerprint_is_sensitive_to_semantic_fields(
    field: str, value: str
) -> None:
    baseline = fingerprint_allocation(_rows())
    changed = _rows()
    changed[0][field] = value
    assert fingerprint_allocation(changed).fingerprint != baseline.fingerprint


def test_allocation_fingerprint_is_sensitive_to_contract_version() -> None:
    assert (
        fingerprint_allocation(
            _rows(), contract_version=CONTRACT_VERSION + "-changed"
        ).fingerprint
        != fingerprint_allocation(_rows()).fingerprint
    )


def test_allocation_fingerprint_ignores_non_semantic_runtime_fields() -> None:
    baseline = fingerprint_allocation(_rows())
    changed = [
        {**row, "processed_at": "2099-01-01", "temporary_path": "C:/tmp"}
        for row in _rows()
    ]
    assert fingerprint_allocation(changed) == baseline


def test_allocation_fingerprint_rejects_duplicate_or_noncanonical_identity() -> None:
    with pytest.raises(ValueError, match="ALLOCATION_ROW_INVALID"):
        fingerprint_allocation([_rows()[0], _rows()[0]])
    with pytest.raises(ValueError, match="ALLOCATION_ROW_INVALID"):
        fingerprint_allocation(
            [{"source_id": "source-a", "group_key": GROUP_A, "split": "train"}]
        )


def test_approved_contract_loader_is_fail_closed(tmp_path: Path) -> None:
    result = fingerprint_allocation(_rows())
    contract = _contract(
        tmp_path / "contract.json", result.fingerprint, result.canonical_bytes_size
    )
    assert (
        load_allocation_fingerprint_contract(contract).expected_fingerprint
        == result.fingerprint
    )
    value = json.loads(contract.read_text(encoding="utf-8"))
    value["record_order"] = "filesystem"
    contract.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="ALLOCATION_FINGERPRINT_CONTRACT_INVALID"):
        load_allocation_fingerprint_contract(contract)
