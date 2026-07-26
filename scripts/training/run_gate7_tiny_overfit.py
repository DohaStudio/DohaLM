"""Prepare and run the explicitly bounded Gate 7 Tiny overfit experiment."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training.gate7_overfit import Gate7OverfitConfig, prepare_gate7_overfit, run_gate7_training

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIHUB-71748 Gate 7 Tiny Overfit을 최대 64문서·500 step으로 제한 실행합니다.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    train = sub.add_parser("train")
    train.add_argument("--target-steps", type=int, required=True)
    train.add_argument("--save-every", type=int, required=True)
    train.add_argument("--attempt", default="training")
    train.add_argument("--resume-checkpoint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = Gate7OverfitConfig.from_yaml(resolve_repository_path(args.config))
        if args.command == "prepare":
            result = prepare_gate7_overfit(config, args.run_id)
        else:
            result = run_gate7_training(config, args.run_id, target_steps=args.target_steps, save_every=args.save_every,
                                        attempt=args.attempt, resume_checkpoint=args.resume_checkpoint)
        print_result(result, json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
