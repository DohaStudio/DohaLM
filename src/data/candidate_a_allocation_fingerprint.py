"""Versioned canonical fingerprint contract for Candidate A production allocation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .checksums import canonical_json_bytes, sha256_bytes


CONTRACT_VERSION = "aihub-71748-production-allocation-fingerprint-v1"
LOGICAL_FIELDS = ("source_id", "group_key", "split")
_IDENTIFIER = re.compile(r"^(?:sha256|group:sha256):[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SPLITS = frozenset(("train", "validation", "test"))


@dataclass(frozen=True, slots=True)
class AllocationFingerprintContract:
    version: str
    expected_fingerprint: str
    canonical_bytes_size: int


@dataclass(frozen=True, slots=True)
class AllocationFingerprint:
    contract_version: str
    fingerprint: str
    canonical_bytes_size: int
    allocation_count: int


def load_allocation_fingerprint_contract(
    path: Path,
) -> AllocationFingerprintContract:
    """Load the approved machine-readable reference without fallback literals."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("status") != "approved"
            or value.get("contract_version") != CONTRACT_VERSION
            or value.get("logical_fields") != list(LOGICAL_FIELDS)
            or value.get("record_order") != "source_id_utf8_bytes_ascending"
            or value.get("unicode_normalization") != "none_ascii_identifiers_required"
            or value.get("serialization") != "canonical_json"
            or value.get("json_sort_keys") is not True
            or value.get("json_separators") != [",", ":"]
            or value.get("json_ensure_ascii") is not False
            or value.get("trailing_newline") != "LF_exactly_one"
            or value.get("encoding") != "UTF-8"
            or value.get("hash_algorithm") != "SHA-256"
            or not _FINGERPRINT.fullmatch(str(value.get("expected_fingerprint", "")))
            or type(value.get("canonical_bytes_size")) is not int
            or value["canonical_bytes_size"] <= 0
        ):
            raise ValueError
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("ALLOCATION_FINGERPRINT_CONTRACT_INVALID") from None
    return AllocationFingerprintContract(
        CONTRACT_VERSION,
        str(value["expected_fingerprint"]),
        int(value["canonical_bytes_size"]),
    )


def canonical_allocation_bytes(
    rows: Iterable[Mapping[str, Any]], *, contract_version: str = CONTRACT_VERSION
) -> bytes:
    """Serialize only allocation semantics in a deterministic total order."""

    if not isinstance(contract_version, str) or not contract_version.isascii():
        raise ValueError("ALLOCATION_CONTRACT_VERSION_INVALID")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            source_id = row["source_id"]
            group_key = row["group_key"]
            split = row["split"]
        except (KeyError, TypeError):
            raise ValueError("ALLOCATION_ROW_INVALID") from None
        if (
            not isinstance(source_id, str)
            or not isinstance(group_key, str)
            or not isinstance(split, str)
            or not source_id.isascii()
            or not group_key.isascii()
            or not _IDENTIFIER.fullmatch(source_id)
            or not _IDENTIFIER.fullmatch(group_key)
            or not source_id.startswith("sha256:")
            or not group_key.startswith("group:sha256:")
            or split not in _SPLITS
            or source_id in seen
        ):
            raise ValueError("ALLOCATION_ROW_INVALID")
        seen.add(source_id)
        normalized.append(
            {"source_id": source_id, "group_key": group_key, "split": split}
        )
    normalized.sort(key=lambda value: value["source_id"].encode("utf-8"))
    return canonical_json_bytes(
        {"contract_version": contract_version, "allocations": normalized}
    )


def fingerprint_allocation(
    rows: Iterable[Mapping[str, Any]], *, contract_version: str = CONTRACT_VERSION
) -> AllocationFingerprint:
    canonical = canonical_allocation_bytes(rows, contract_version=contract_version)
    payload = json.loads(canonical)
    return AllocationFingerprint(
        contract_version,
        sha256_bytes(canonical),
        len(canonical),
        len(payload["allocations"]),
    )


__all__ = [
    "AllocationFingerprint",
    "AllocationFingerprintContract",
    "CONTRACT_VERSION",
    "LOGICAL_FIELDS",
    "canonical_allocation_bytes",
    "fingerprint_allocation",
    "load_allocation_fingerprint_contract",
]
