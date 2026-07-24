"""Run a bounded synthetic forward, loss, and backward smoke."""

from __future__ import annotations

import argparse

import torch

from src.model import DohaLMTiny

from ._common import cli_error, print_result, resolve_device_and_dtype, smoke_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="작은 합성 token으로 모델 forward/loss/backward를 검증합니다.")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--sequence-length", type=int, default=8)
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.batch_size <= 0 or args.sequence_length < 2:
        raise ValueError("batch-size는 양수, sequence-length는 2 이상이어야 합니다.")
    config = smoke_config()
    if args.sequence_length > config.context_length:
        raise ValueError("sequence-length가 smoke context length를 초과합니다.")
    device, dtype = resolve_device_and_dtype(args)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    model = DohaLMTiny(config).to(device=device, dtype=dtype)
    input_ids = torch.randint(0, config.vocab_size, (args.batch_size, args.sequence_length), device=device)
    output = model(input_ids, labels=input_ids)
    assert output.loss is not None
    output.loss.backward()
    gradients = [parameter.grad for parameter in model.parameters() if parameter.requires_grad]
    finite_gradients = bool(gradients) and all(
        gradient is not None and bool(torch.isfinite(gradient).all().item()) for gradient in gradients
    )
    result: dict[str, object] = {
        "status": "smoke_complete",
        "device": str(device),
        "dtype": str(dtype),
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "logits_shape": list(output.logits.shape),
        "loss": float(output.loss.detach().float().cpu().item()),
        "loss_finite": bool(torch.isfinite(output.loss).item()),
        "gradients_finite": finite_gradients,
        "parameter_count": model.parameter_breakdown()["total_parameters"],
    }
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        result["peak_allocated_mib"] = round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3)
        result["peak_reserved_mib"] = round(torch.cuda.max_memory_reserved(device) / (1024 * 1024), 3)
    else:
        result["peak_allocated_mib"] = None
        result["peak_reserved_mib"] = None
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        print_result(run(_parser().parse_args(argv)))
        return 0
    except (RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
