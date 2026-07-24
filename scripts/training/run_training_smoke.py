"""Run bounded synthetic causal-LM optimization on CPU or one CUDA device."""

from __future__ import annotations

import argparse
import time

from src.training import TrainingConfig, TrainingError

from ._common import build_trainer, cli_error, dataset_metadata, print_result, small_model_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="합성 token으로 Trainer Foundation을 짧게 검증합니다.")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    parser.add_argument("--use-amp", action="store_true")
    parser.add_argument("--steps", type=int, default=10, help="이번 실행이 도달할 optimizer step")
    parser.add_argument("--max-steps", type=int, help="scheduler 전체 step; 기본값은 --steps")
    parser.add_argument("--batch-size", type=int, default=2, help="micro-batch size")
    parser.add_argument("--accumulation-steps", type=int, default=1)
    parser.add_argument("--sequence-length", type=int, default=8)
    parser.add_argument("--records", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--save-every", type=int, default=5)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", default="tests/output/training-smoke")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.use_amp != (args.dtype == "float16"):
        raise TrainingError("INVALID_TRAINING_CONFIG", "float16 smoke는 --use-amp와 함께 사용해야 합니다.")
    max_steps = args.max_steps if args.max_steps is not None else args.steps
    config = TrainingConfig(
        batch_size=args.batch_size * args.accumulation_steps,
        micro_batch_size=args.batch_size,
        gradient_accumulation_steps=args.accumulation_steps,
        max_steps=max_steps,
        learning_rate=args.learning_rate,
        warmup_steps=0,
        use_amp=args.use_amp,
        seed=args.seed,
        save_every=args.save_every,
        output_dir=args.output,
        device=args.device,
        num_workers=0,
        pin_memory=args.device == "cuda",
    )
    model_config = small_model_config(context_length=max(32, args.sequence_length))
    metadata = dataset_metadata(
        sequence_length=args.sequence_length,
        num_records=args.records,
        seed=args.seed,
        vocab_size=model_config.vocab_size,
    )
    trainer, dataset = build_trainer(model_config=model_config, training_config=config, metadata=metadata)
    started = time.perf_counter()
    result = trainer.train(target_steps=args.steps)
    return {
        "status": "training_smoke_complete",
        "device": args.device,
        "amp_enabled": args.use_amp,
        "amp_dtype": args.dtype if args.use_amp else None,
        "synthetic_only": True,
        "dataset_fingerprint": dataset.fingerprint,
        "tokenizer_fingerprint": result.state.tokenizer_fingerprint,
        "output_dir": config.output_dir,
        "duration_seconds": time.perf_counter() - started,
        **result.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(run(args), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
