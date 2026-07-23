"""Deterministic exact duplicate removal."""

from __future__ import annotations

from collections.abc import Callable

from .models import CanonicalRecord, DuplicateRecord


def _sort_key(record: CanonicalRecord) -> tuple[str, str, str]:
    return record.source_path, record.source_record_id, record.record_id


def deduplicate(records: list[CanonicalRecord]) -> tuple[list[CanonicalRecord], list[DuplicateRecord]]:
    remaining = sorted(records, key=_sort_key)
    duplicates: list[DuplicateRecord] = []
    canonical_file: dict[str, str] = {}
    file_representatives: dict[tuple[str, str], CanonicalRecord] = {}
    kept_after_file: list[CanonicalRecord] = []
    for record in remaining:
        representative_path = canonical_file.setdefault(record.file_checksum, record.source_path)
        if record.source_path == representative_path:
            kept_after_file.append(record)
            file_representatives[(record.file_checksum, record.source_record_id)] = record
            continue
        representative = file_representatives.get((record.file_checksum, record.source_record_id))
        if representative is None:
            representative = min(
                (item for item in kept_after_file if item.file_checksum == record.file_checksum), key=_sort_key
            )
        duplicates.append(
            DuplicateRecord(
                "FILE_DUPLICATE",
                record.record_id,
                representative.record_id,
                record.file_checksum,
                record.source_path,
                record.source_record_id,
            )
        )
    remaining = kept_after_file
    checks: tuple[tuple[str, Callable[[CanonicalRecord], str]], ...] = (
        ("RAW_RECORD_DUPLICATE", lambda item: item.raw_record_checksum),
        ("NORMALIZED_TEXT_DUPLICATE", lambda item: item.normalized_record_checksum),
    )
    for duplicate_type, getter in checks:
        representatives: dict[str, CanonicalRecord] = {}
        kept: list[CanonicalRecord] = []
        for record in remaining:
            checksum = getter(record)
            representative = representatives.get(checksum)
            if representative is None:
                representatives[checksum] = record
                kept.append(record)
                continue
            duplicates.append(
                DuplicateRecord(
                    duplicate_type=duplicate_type,
                    duplicate_record_id=record.record_id,
                    canonical_record_id=representative.record_id,
                    checksum=checksum,
                    source_path=record.source_path,
                    source_record_id=record.source_record_id,
                )
            )
        remaining = kept
    return sorted(remaining, key=lambda item: item.record_id), sorted(
        duplicates, key=lambda item: (item.duplicate_record_id, item.duplicate_type)
    )
