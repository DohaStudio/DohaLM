"""Prepare and run the explicitly bounded Gate 7 Tiny overfit experiment."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training.gate7_overfit import (
    Gate7OverfitConfig,
    clone_gate7_prepared,
    evaluate_gate7_checkpoint,
    prepare_gate7_overfit,
    run_gate7_training,
)

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIHUB-71748 Gate 7 보완 검증을 동일 64문서·최대 1,000 step으로 제한 실행합니다.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    clone = sub.add_parser("clone-prepared")
    clone.add_argument("--source-run-id", required=True)
    train = sub.add_parser("train")
    train.add_argument("--target-steps", type=int, required=True)
    train.add_argument("--save-every", type=int, required=True)
    train.add_argument("--attempt", default="training")
    train.add_argument("--resume-checkpoint")
    train.add_argument("--learning-rate", type=float, choices=(3e-4, 5e-4, 1e-3))
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--attempt", required=True)
    evaluate.add_argument("--checkpoint", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = Gate7OverfitConfig.from_yaml(resolve_repository_path(args.config))
        if args.command == "prepare":
            result = prepare_gate7_overfit(config, args.run_id)
        elif args.command == "clone-prepared":
            result = clone_gate7_prepared(config, args.source_run_id, args.run_id)
        elif args.command == "evaluate":
            result = evaluate_gate7_checkpoint(config, args.run_id, attempt=args.attempt, checkpoint_name=args.checkpoint)
        else:
            result = run_gate7_training(config, args.run_id, target_steps=args.target_steps, save_every=args.save_every,
                                        attempt=args.attempt, resume_checkpoint=args.resume_checkpoint,
                                        learning_rate=args.learning_rate)
        print_result(result, json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
