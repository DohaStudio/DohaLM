"""Run deterministic synthetic greedy generation without a tokenizer."""

from __future__ import annotations

import argparse

import torch

from src.model import DohaLMTiny

from ._common import cli_error, print_result, resolve_device_and_dtype, smoke_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="작은 합성 token ID로 greedy generation을 검증합니다.")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-new-tokens", type=int, default=3)
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = smoke_config()
    device, dtype = resolve_device_and_dtype(args)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
    model = DohaLMTiny(config).to(device=device, dtype=dtype)
    prefix = torch.tensor([[2, 8, 9]], dtype=torch.long, device=device)
    generated = model.generate(prefix, max_new_tokens=args.max_new_tokens)
    return {
        "status": "generation_complete",
        "device": str(device),
        "dtype": str(dtype),
        "prefix": prefix.cpu().tolist(),
        "generated_ids": generated.cpu().tolist(),
        "generated_shape": list(generated.shape),
        "prefix_preserved": bool(torch.equal(generated[:, : prefix.shape[1]], prefix)),
        "tokens_in_range": bool(((generated >= 0) & (generated < config.vocab_size)).all().item()),
        "sampling_used": False,
        "tokenizer_used": False,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        print_result(run(_parser().parse_args(argv)))
        return 0
    except (RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
