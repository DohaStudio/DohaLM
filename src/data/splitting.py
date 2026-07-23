"""Group-preserving deterministic split and leakage checks."""

from __future__ import annotations

import hashlib

from .config import DataConfig
from .errors import DataIssue, DataPipelineError
from .models import CanonicalRecord, SplitAssignment


def _bucket(seed: int, group_id: str) -> float:
    digest = hashlib.sha256(f"{seed}\n{group_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign_splits(records: list[CanonicalRecord], config: DataConfig) -> tuple[dict[str, list[CanonicalRecord]], list[SplitAssignment]]:
    boundaries = (config.train_ratio, config.train_ratio + config.validation_ratio)
    split_records = {"train": [], "validation": [], "test": []}
    assignments: list[SplitAssignment] = []
    group_splits: dict[str, str] = {}
    for record in sorted(records, key=lambda item: item.record_id):
        value = _bucket(config.split_seed, record.group_id)
        split = "train" if value < boundaries[0] else "validation" if value < boundaries[1] else "test"
        prior = group_splits.setdefault(record.group_id, split)
        if prior != split:
            raise DataPipelineError(DataIssue("SPLIT_LEAKAGE", "split", "동일 group이 여러 split에 배정됐습니다."))
        split_records[split].append(record)
        assignments.append(SplitAssignment(record.record_id, split, record.group_id))
    validate_no_leakage(split_records)
    for values in split_records.values():
        values.sort(key=lambda item: item.record_id)
    return split_records, sorted(assignments, key=lambda item: item.record_id)


def validate_no_leakage(splits: dict[str, list[CanonicalRecord]]) -> None:
    dimensions = {
        "group_id": lambda item: item.group_id,
        "raw_record_checksum": lambda item: item.raw_record_checksum,
        "normalized_record_checksum": lambda item: item.normalized_record_checksum,
        "record_id": lambda item: item.record_id,
        "source_record": lambda item: (item.source_path, item.source_record_id),
    }
    for name, getter in dimensions.items():
        owners: dict[object, str] = {}
        for split_name, records in splits.items():
            for record in records:
                key = getter(record)
                previous = owners.setdefault(key, split_name)
                if previous != split_name:
                    raise DataPipelineError(
                        DataIssue("SPLIT_LEAKAGE", "split", f"{name} 값이 {previous}/{split_name}에 중복됩니다.")
                    )
