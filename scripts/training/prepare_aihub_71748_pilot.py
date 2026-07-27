"""Prepare the approved AIHUB-71748 Pilot dataset without printing source text."""

from __future__ import annotations

import argparse

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.data.pilot_dataset import (
    PilotDatasetConfig,
    audit_aihub_71748_source_lineage,
    finalize_existing_pilot_dataset,
    prepare_aihub_71748_pilot_dataset,
    verify_existing_pilot_dataset,
)
from src.runtime.paths import resolve_repository_path

from ._common import cli_error, print_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIHUB-71748 Training 전용 Pilot dataset을 준비합니다.")
    parser.add_argument("--output", required=True, help="configured external root 아래 상대경로")
    parser.add_argument("--finalize-existing", action="store_true", help="불완전 게시물 checksum을 검증하고 완료 마커만 추가")
    parser.add_argument("--audit-lineage", action="store_true", help="canonical selector와 legacy Pilot selector를 hash metadata로 비교")
    parser.add_argument("--verify-existing", action="store_true", help="완료된 Pilot dataset checksum과 fingerprint를 재계산")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        external, dataset = resolve_local_paths(resolve_repository_path("configs/local-datasets.yaml"))
        output = (external / args.output).resolve()
        if external not in output.parents:
            raise ValueError("output이 configured external root 밖입니다.")
        if args.verify_existing:
            result = verify_existing_pilot_dataset(output)
        elif args.audit_lineage:
            result = audit_aihub_71748_source_lineage(
                dataset_root=dataset,
                checksum_inventory=resolve_repository_path("docs/data/aihub-71748-zip-checksums.manifest.yaml"),
                historical_manifest=external / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/corpus/corpus-manifest.json",
                output=output,
            )
        elif args.finalize_existing:
            result = finalize_existing_pilot_dataset(output)
        else:
            result = prepare_aihub_71748_pilot_dataset(
                dataset_root=dataset,
                checksum_inventory=resolve_repository_path("docs/data/aihub-71748-zip-checksums.manifest.yaml"),
                tokenizer_bundle=external / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v2/tokenizers/unigram-16k",
                source_corpus_manifest=external / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/corpus/corpus-manifest.json",
                output=output,
                config=PilotDatasetConfig(),
            )
        print_result(result, json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
