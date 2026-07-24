"""ZIP 내부 JSON array의 제한된 record 구조를 분석하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .manual_path_mapping import load_manual_mapping
from .safe_sampler import SamplerError
from .zip_json_record_sampler import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_READ_BYTES_PER_ENTRY,
    DEFAULT_MAX_RECORD_BYTES,
    DEFAULT_MAX_TOTAL_READ_BYTES,
    DEFAULT_RECORDS_PER_ENTRY,
    record_sample_output_root,
    sample_zip_json_records,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.sample_zip_json_records",
        description="ZIP 내부 대용량 JSON array에서 제한된 record 구조만 원문 없이 분석합니다.",
    )
    parser.add_argument("--config", required=True, help="Git에서 제외된 로컬 데이터셋 YAML 경로")
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--manual-mapping", required=True, help="사용자가 승인한 로컬 mapping YAML 경로")
    parser.add_argument("--archive", help="dataset root 기준 특정 ZIP 상대경로")
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--records-per-entry", type=int, default=DEFAULT_RECORDS_PER_ENTRY)
    parser.add_argument("--max-record-bytes", type=int, default=DEFAULT_MAX_RECORD_BYTES)
    parser.add_argument("--max-read-bytes-per-entry", type=int, default=DEFAULT_MAX_READ_BYTES_PER_ENTRY)
    parser.add_argument("--max-total-read-bytes", type=int, default=DEFAULT_MAX_TOTAL_READ_BYTES)
    parser.add_argument("--output-dir", default=None, help="external root 기준 analysis/record-samples 하위 경로")
    parser.add_argument("--dry-run", action="store_true", help="entry byte를 읽지 않고 mapping·후보·제한·출력 계획만 검증")
    parser.add_argument("--json", action="store_true", help="원문 없는 실행 요약을 JSON으로 출력")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    mapping = load_manual_mapping(args.manual_mapping, args.dataset)
    output_root = record_sample_output_root(config, args.output_dir, repository_root())
    return sample_zip_json_records(
        config.entries[args.dataset],
        output_root,
        mapping,
        requested_archive=args.archive,
        max_entries=args.max_entries,
        records_per_entry=args.records_per_entry,
        max_record_bytes=args.max_record_bytes,
        max_read_bytes_per_entry=args.max_read_bytes_per_entry,
        max_total_read_bytes=args.max_total_read_bytes,
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
            f"{result['dataset_id']}: entry 선택 {result['entries_selected']}개, "
            f"검사 {result['entries_inspected']}개, record 관측 {result['records_seen']}개, "
            f"선택 {result['records_selected']}개"
        )
        print(f"상태: {result['run_status']}")
        print("산출물: 저장소 외부 analysis/record-samples 경로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
