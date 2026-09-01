"""Build the rights-first Candidate A production Dataset artifacts."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Iterator

import psycopg

from src.data.candidate_a_production_dataset import (
    build_candidate_a_production_dataset,
    verify_candidate_a_production_dataset,
)
from src.data.postgres_current_evidence import PostgresCurrentRightsAuthority


class _RightsReaderConnections:
    role = "doharights_reader"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with psycopg.connect(self._dsn) as connection:
            yield connection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--checksum-inventory", type=Path, required=True)
    parser.add_argument("--tokenizer-model", type=Path, required=True)
    parser.add_argument("--eligibility-material", type=Path, required=True)
    parser.add_argument("--allocation-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rights-subject-id", required=True)
    parser.add_argument("--rights-source-authority-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    dsn = os.environ.get("DOHALM_DOHARIGHTS_READER_DSN")
    if not dsn:
        raise SystemExit("DOHALM_DOHARIGHTS_READER_DSN is required")
    authority = PostgresCurrentRightsAuthority(
        _RightsReaderConnections(dsn),
        source_authority_id=args.rights_source_authority_id,
    )
    rights = authority.get_current_rights(args.rights_subject_id)
    if not authority.verify_currentness(rights.token):
        raise SystemExit("RIGHTS_TOKEN_NOT_CURRENT")
    result = build_candidate_a_production_dataset(
        dataset_root=args.dataset_root,
        checksum_inventory=args.checksum_inventory,
        tokenizer_model=args.tokenizer_model,
        eligibility_material=args.eligibility_material,
        allocation_contract=args.allocation_contract,
        rights=rights,
        output=args.output,
        reviewed_at=datetime.now(timezone.utc),
    )
    verified = verify_candidate_a_production_dataset(
        result.output, allocation_contract=args.allocation_contract
    )
    print(f"status={verified['status']}")
    print(f"dataset_fingerprint={verified['dataset_fingerprint']}")
    print(
        f"artifact_checksums_fingerprint={verified['artifact_checksums_fingerprint']}"
    )
    print(f"selected_records={verified['selected_records']}")
    print(f"selected_groups={verified['selected_groups']}")
    print(f"cross_split_group_overlap={verified['cross_split_group_overlap']}")
    print("actual_dataset_publication=0")
    print("actual_training_workload=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
