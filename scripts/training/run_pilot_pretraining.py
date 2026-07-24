"""Run a bounded pilot from an explicit local configuration."""

from __future__ import annotations

import argparse
from dataclasses import replace

from src.runtime.paths import resolve_repository_path
from src.training.pilot_config import PilotPretrainingConfig
from src.training.pilot_pretraining import run_pilot_pretraining

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DohaLM-Tiny local-only pilot pretraining을 최대 100 step 실행합니다.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke", action="store_true", help="설정 범위 안에서 최대 5 step만 실행")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--use-amp", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = PilotPretrainingConfig.from_yaml(resolve_repository_path(args.config))
        if args.steps is not None:
            config = replace(config, max_steps=args.steps, validation_every=min(config.validation_every, args.steps), save_every=min(config.save_every, args.steps))
        if args.device is not None:
            config = replace(config, device=args.device, use_amp=args.use_amp)
        elif args.use_amp and not config.use_amp:
            config = replace(config, use_amp=True)
        if args.smoke:
            config = config.smoke()
        print_result(run_pilot_pretraining(config), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
