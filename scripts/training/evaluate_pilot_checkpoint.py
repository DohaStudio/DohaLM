"""Evaluate a compatible pilot checkpoint on the isolated validation split."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training.pilot_config import PilotPretrainingConfig
from src.training.pilot_pretraining import evaluate_pilot_checkpoint

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pilot checkpoint의 validation loss와 perplexity를 계산합니다.")
    parser.add_argument("--config", default="configs/pilot-pretrain.yaml")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = PilotPretrainingConfig.from_yaml(resolve_repository_path(args.config))
        print_result(evaluate_pilot_checkpoint(config, args.checkpoint).to_dict(), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
