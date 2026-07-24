"""Private preview 수동 검토 결과와 만료 상태를 검증하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.runtime.paths import repository_root

from .private_preview_review import inspect_private_review
from .safe_sampler import SamplerError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.review_private_previews",
        description="외부 private preview의 checksum·review checklist·보존 기한을 검증합니다.",
    )
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--check-expiration", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    return inspect_private_review(
        Path(args.review_dir), repository_root(), check_expiration=args.check_expiration,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (SamplerError, OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['dataset_id']}: run {result['run_id']}, expired={result['expired']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
