"""Validate and inspect a local synthetic training checkpoint."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training import CheckpointManager

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="checksum 검증 후 checkpoint metadata를 출력합니다.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = CheckpointManager.inspect(resolve_repository_path(args.checkpoint)).to_dict()
        print_result({"status": "checkpoint_valid", **report}, json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
