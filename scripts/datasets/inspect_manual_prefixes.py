"""ZIP 첫 component를 hash·Unicode 통계로만 비교하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .manual_path_mapping import load_manual_mapping
from .manual_prefix_inspector import inspect_manual_prefixes, manual_prefix_output_root
from .safe_sampler import SamplerError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.inspect_manual_prefixes",
        description="ZIP entry 첫 component를 원문 없이 hash·Unicode 통계로 비교합니다.",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--manual-mapping", required=True)
    parser.add_argument("--archive", help="dataset root 기준 특정 ZIP 상대경로")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--dry-run", action="store_true", help="ZIP 중앙 디렉터리만 읽는 로컬 검사")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    mapping = load_manual_mapping(args.manual_mapping, args.dataset)
    output = manual_prefix_output_root(config, args.output_dir, repository_root())
    return inspect_manual_prefixes(
        config.entries[args.dataset],
        output,
        mapping,
        requested_archive=args.archive,
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
            f"{result['dataset_id']}: entry {result['entries_grouped']}개, "
            f"prefix group {result['prefix_group_count']}개"
        )
        print(f"상태: {result['run_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
