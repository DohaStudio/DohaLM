"""Verify the full private Candidate A allocation against its approved contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.candidate_a_allocation_fingerprint import (
    fingerprint_allocation,
    load_allocation_fingerprint_contract,
)
from src.data.candidate_a_production_dataset import (
    EXPECTED_SELECTED_GROUPS,
    EXPECTED_SELECTED_RECORDS,
    EXPECTED_SOURCE_RECORDS,
    EXPECTED_SPLIT_COUNTS,
    _iter_source_records,
    candidate_a_group_key,
    candidate_a_split,
)
from src.data.pilot_dataset import pii_categories


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--checksum-inventory", type=Path, required=True)
    parser.add_argument("--allocation-contract", type=Path, required=True)
    args = parser.parse_args()
    approved = load_allocation_fingerprint_contract(args.allocation_contract)
    rows: list[dict[str, str]] = []
    source_count = 0
    groups: dict[str, str] = {}
    split_records = {name: 0 for name in EXPECTED_SPLIT_COUNTS}
    split_groups = {name: set() for name in EXPECTED_SPLIT_COUNTS}
    for row in _iter_source_records(args.dataset_root, args.checksum_inventory):
        source_count += 1
        if pii_categories(row["text"]):
            continue
        group_key = candidate_a_group_key(str(row["data_file"]))
        split = candidate_a_split(group_key)
        previous = groups.setdefault(group_key, split)
        if previous != split:
            raise SystemExit("CROSS_SPLIT_GROUP")
        split_records[split] += 1
        split_groups[split].add(group_key)
        rows.append(
            {
                "source_id": str(row["source_id"]),
                "group_key": group_key,
                "split": split,
            }
        )
    result = fingerprint_allocation(rows)
    reversed_result = fingerprint_allocation(reversed(rows))
    observed_counts = {
        name: (split_records[name], len(split_groups[name]))
        for name in EXPECTED_SPLIT_COUNTS
    }
    if (
        source_count != EXPECTED_SOURCE_RECORDS
        or len(rows) != EXPECTED_SELECTED_RECORDS
        or len(groups) != EXPECTED_SELECTED_GROUPS
        or observed_counts != EXPECTED_SPLIT_COUNTS
        or result.fingerprint != approved.expected_fingerprint
        or result.canonical_bytes_size != approved.canonical_bytes_size
        or reversed_result != result
    ):
        raise SystemExit("CANDIDATE_A_PRODUCTION_ALLOCATION_MISMATCH")
    print(
        json.dumps(
            {
                "canonical_bytes_size": result.canonical_bytes_size,
                "contract_version": result.contract_version,
                "fingerprint": result.fingerprint,
                "selected_groups": len(groups),
                "selected_records": len(rows),
                "source_records": source_count,
                "split_counts": observed_counts,
                "reverse_order_equal": reversed_result == result,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
