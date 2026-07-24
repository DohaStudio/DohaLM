"""AI Hub ZIP JSON record의 층화 schema·PII review bundle CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .manual_path_mapping import load_manual_mapping
from .safe_sampler import SamplerError
from .stratified_record_sampler import (
    DEFAULT_MAX_ARCHIVES,
    DEFAULT_MAX_ENTRIES_PER_ARCHIVE,
    DEFAULT_MAX_READ_BYTES_PER_ENTRY,
    DEFAULT_MAX_RECORD_BYTES,
    DEFAULT_MAX_TOTAL_READ_BYTES,
    DEFAULT_RECORDS_PER_ENTRY,
    DEFAULT_SELECTION_SEED,
    review_stratified_records,
    schema_review_output_root,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.review_aihub_records",
        description="Archive·entry·bounded record 구간을 층화해 비노출 schema·PII review bundle을 만듭니다.",
    )
    parser.add_argument("--config", required=True, help="Git에서 제외된 로컬 데이터셋 YAML 경로")
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--manual-mapping", required=True, help="사용자가 승인한 로컬 mapping YAML 경로")
    parser.add_argument("--max-archives", type=int, default=DEFAULT_MAX_ARCHIVES)
    parser.add_argument("--max-entries-per-archive", type=int, default=DEFAULT_MAX_ENTRIES_PER_ARCHIVE)
    parser.add_argument("--records-per-entry", type=int, default=DEFAULT_RECORDS_PER_ENTRY)
    parser.add_argument("--max-record-bytes", type=int, default=DEFAULT_MAX_RECORD_BYTES)
    parser.add_argument("--max-read-bytes-per-entry", type=int, default=DEFAULT_MAX_READ_BYTES_PER_ENTRY)
    parser.add_argument("--max-total-read-bytes", type=int, default=DEFAULT_MAX_TOTAL_READ_BYTES)
    parser.add_argument("--selection-seed", default=DEFAULT_SELECTION_SEED)
    parser.add_argument("--output-dir", default=None, help="external root 기준 analysis/schema-review 하위 경로")
    parser.add_argument("--dry-run", action="store_true", help="entry byte를 읽지 않고 archive·entry strata와 budget만 검증")
    parser.add_argument("--json", action="store_true", help="원문 없는 실행 요약을 JSON으로 출력")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    mapping = load_manual_mapping(args.manual_mapping, args.dataset)
    output_root = schema_review_output_root(config, args.output_dir, repository_root())
    return review_stratified_records(
        config.entries[args.dataset],
        output_root,
        mapping,
        max_archives=args.max_archives,
        max_entries_per_archive=args.max_entries_per_archive,
        records_per_entry=args.records_per_entry,
        max_record_bytes=args.max_record_bytes,
        max_read_bytes_per_entry=args.max_read_bytes_per_entry,
        max_total_read_bytes=args.max_total_read_bytes,
        selection_seed=args.selection_seed,
        dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (SamplerError, ConfigError, OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{result['dataset_id']}: archive {result['archives_selected']}개, "
            f"entry 선택 {result['entries_selected']}개, 검사 {result['entries_inspected']}개, "
            f"record 선택 {result['records_selected']}개"
        )
        print(f"상태: {result['run_status']}")
        print("산출물: 저장소 외부 analysis/schema-review 경로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
