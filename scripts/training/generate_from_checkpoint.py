"""Greedy local generation from a compatible pilot checkpoint."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training.pilot_config import PilotPretrainingConfig
from src.training.pilot_pretraining import generate_from_pilot_checkpoint

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pilot checkpoint에서 결정론적 greedy generation을 실행합니다.")
    parser.add_argument("--config", default="configs/pilot-pretrain.yaml")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--prompt", required=True, help="로컬 실행 전용 prompt")
    parser.add_argument("--max-new-tokens", type=int)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = PilotPretrainingConfig.from_yaml(resolve_repository_path(args.config))
        if args.max_new_tokens is not None:
            from dataclasses import replace
            config = replace(config, max_new_tokens=args.max_new_tokens)
        print_result(generate_from_pilot_checkpoint(config, args.checkpoint, args.prompt), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
