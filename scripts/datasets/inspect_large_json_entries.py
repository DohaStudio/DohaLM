"""승인 mapping의 대용량 JSON entry를 제한 streaming 검사하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .large_json_inspector import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_READ_BYTES,
    DEFAULT_MAX_TOTAL_READ_BYTES,
    inspect_large_json_entries,
    large_json_output_root,
)
from .manual_path_mapping import load_manual_mapping
from .safe_sampler import SamplerError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.inspect_large_json_entries",
        description="대용량 ZIP JSON의 제한된 prefix byte만 stream으로 구조 검사합니다.",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--manual-mapping", required=True)
    parser.add_argument("--archive", help="dataset root 기준 특정 ZIP 상대경로")
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--max-read-bytes", type=int, default=DEFAULT_MAX_READ_BYTES)
    parser.add_argument("--max-total-read-bytes", type=int, default=DEFAULT_MAX_TOTAL_READ_BYTES)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--dry-run", action="store_true", help="원문 저장·추출 없는 읽기 전용 구조 검사")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    mapping = load_manual_mapping(args.manual_mapping, args.dataset)
    output = large_json_output_root(config, args.output_dir, repository_root())
    return inspect_large_json_entries(
        config.entries[args.dataset],
        output,
        mapping,
        requested_archive=args.archive,
        max_entries=args.max_entries,
        max_read_bytes=args.max_read_bytes,
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
            f"{result['dataset_id']}: 대용량 후보 {result['candidate_count']}개, "
            f"stream 검사 {result['inspected_count']}개, 읽은 byte {result['total_bytes_read']}"
        )
        print(f"상태: {result['run_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
