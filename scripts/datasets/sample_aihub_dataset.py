"""AI Hub ZIP에서 제한된 안전 표본만 외부 격리 경로에 추출하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .safe_sampler import DEFAULT_EXTENSIONS, SamplerError, safe_sample_output_root, sample_dataset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.sample_aihub_dataset",
        description="위험한 ZIP entry를 거부하고 소수 text 표본만 외부 격리 경로에 추출합니다.",
    )
    parser.add_argument("--config", required=True, help="Git에서 제외된 로컬 데이터셋 YAML 경로")
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--archive", help="dataset root 기준 특정 ZIP 상대 경로")
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--max-file-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--allowed-extensions", nargs="+", default=list(DEFAULT_EXTENSIONS))
    parser.add_argument("--output-dir", default="analysis/samples", help="external root 기준 analysis 하위 경로")
    parser.add_argument("--dry-run", action="store_true", help="파일을 추출하지 않고 선택·거부 manifest만 생성")
    parser.add_argument("--json", action="store_true", help="안전한 실행 요약을 JSON으로 출력")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    output_root = safe_sample_output_root(config, args.output_dir, repository_root())
    return sample_dataset(
        config.entries[args.dataset],
        output_root,
        requested_archive=args.archive,
        sample_count=args.sample_count,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        allowed_extensions=args.allowed_extensions,
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
            f"{result['dataset_id']}: archive {result['archives_scanned']}개, "
            f"안전 entry {result['entries_safe']}개, 선택 {result['samples_selected']}개, "
            f"추출 {result['samples_extracted']}개"
        )
        print(f"상태: {result['run_status']}")
        print("산출물: 저장소 외부 analysis/samples 경로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
