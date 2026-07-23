"""Deterministic checksums and identifiers."""

from __future__ import annotations

from .checksums import checksum_value


def txt_source_record_id(source_path: str, file_checksum: str) -> str:
    return checksum_value({"source_path": source_path, "file_checksum": file_checksum})


def record_id(source_name: str, source_path: str, source_record_id: str, raw_checksum: str) -> str:
    return checksum_value(
        {
            "source_name": source_name,
            "source_path": source_path,
            "source_record_id": source_record_id,
            "raw_record_checksum": raw_checksum,
        }
    )


def generated_group_id(source_name: str, source_path: str) -> str:
    return checksum_value({"source_name": source_name, "source_path": source_path})
