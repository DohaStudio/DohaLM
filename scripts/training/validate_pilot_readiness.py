"""Inspect fail-closed pilot pretraining readiness."""

from __future__ import annotations

import argparse

from src.runtime.paths import repository_root, resolve_repository_path
from src.training.pilot_readiness import validate_pilot_readiness

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="실제 tokenizer/corpus 연결 전 pilot pretraining 준비 상태를 검사합니다.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_pilot_readiness(resolve_repository_path(args.config), repository_root() / "docs/quality/development-roadmap.md")
        print_result(report, json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
