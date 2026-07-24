"""Run bounded full-scale DohaLM-Tiny validation with synthetic tokens."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training import TrainingError, run_tiny_validation

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="실제 DohaLM-Tiny config를 합성 token으로 제한 검증합니다.")
    parser.add_argument("--mode", choices=("smoke", "overfit"), default="smoke")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float16")
    parser.add_argument("--use-amp", action="store_true")
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--save-step", type=int)
    parser.add_argument("--sequence-length", type=int)
    parser.add_argument("--micro-batch-size", type=int, default=1)
    parser.add_argument("--accumulation-steps", type=int)
    parser.add_argument("--records", type=int, default=64)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--warmup-steps", type=int, default=1)
    parser.add_argument("--min-lr-ratio", type=float, default=0.1)
    parser.add_argument("--output", default="tests/output/tiny-validation")
    parser.add_argument("--no-continuity-reference", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    use_amp = args.use_amp
    if (args.dtype == "float16") != use_amp:
        raise TrainingError("INVALID_TRAINING_CONFIG", "float16은 --use-amp와 함께, float32는 AMP 없이 사용해야 합니다.")
    if args.device == "cpu" and use_amp:
        raise TrainingError("AMP_NOT_AVAILABLE", "CPU Tiny validation은 FP16 AMP를 지원하지 않습니다.")
    mode = "repeated_pattern" if args.mode == "overfit" else "deterministic_random"
    sequence_length = args.sequence_length or (64 if args.mode == "overfit" else 256)
    accumulation_steps = args.accumulation_steps or (1 if args.mode == "overfit" else 8)
    save_step = args.save_step or max(1, args.steps // 2)
    return run_tiny_validation(
        output_parent=resolve_repository_path(args.output),
        mode=mode,
        device=args.device,
        use_amp=use_amp,
        steps=args.steps,
        save_step=save_step,
        sequence_length=sequence_length,
        micro_batch_size=args.micro_batch_size,
        accumulation_steps=accumulation_steps,
        records=args.records,
        seed=args.seed,
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        min_lr_ratio=args.min_lr_ratio,
        compare_uninterrupted=not args.no_continuity_reference,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(run(args), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
